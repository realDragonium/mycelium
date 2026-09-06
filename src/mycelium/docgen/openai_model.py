"""Responses transport for the documentation loop's existing tool protocol."""

from __future__ import annotations

import os
from typing import Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from .config import DocgenConfig

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ToolUse(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, JsonValue]


class ResponseHistory(BaseModel):
    type: Literal["openai_response"] = "openai_response"
    output: list[dict[str, JsonValue]]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


class ModelResponse(BaseModel):
    content: list[ResponseHistory | ToolUse]
    usage: Usage


class _FunctionCall(BaseModel):
    type: Literal["function_call"]
    call_id: str
    name: str
    arguments: str


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    output: list[dict[str, JsonValue]]
    usage: dict[str, JsonValue] = Field(default_factory=dict)


def _input(messages: list[dict[str, object]]) -> list[dict[str, JsonValue]]:
    items: list[dict[str, JsonValue]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            role = message.get("role")
            if role not in ("user", "assistant"):
                raise ValueError("unsupported documentation message role")
            items.append({"role": str(role), "content": content})
        elif isinstance(content, list):
            items.extend(_blocks(content))
        else:
            raise ValueError("unsupported documentation message content")
    return items


def _blocks(content: list[object]) -> list[dict[str, JsonValue]]:
    items: list[dict[str, JsonValue]] = []
    for block in content:
        if isinstance(block, ResponseHistory):
            # Keep every item, including encrypted reasoning, in API order.
            items.extend(block.output)
        elif isinstance(block, ToolUse):
            continue  # The original function call is already in ResponseHistory.
        else:
            result = _JSON_OBJECT.validate_python(block)
            if result.get("type") != "tool_result":
                raise ValueError("unsupported documentation history block")
            call_id, output = result.get("tool_use_id"), result.get("content")
            if not isinstance(call_id, str) or not isinstance(output, str):
                raise ValueError("invalid documentation tool result")
            items.append(
                {"type": "function_call_output", "call_id": call_id, "output": output}
            )
    return items


def _tools(tools: list[dict[str, object]]) -> list[dict[str, JsonValue]]:
    definitions: list[dict[str, JsonValue]] = []
    for tool in tools:
        schema = _JSON_OBJECT.validate_python(tool)
        definitions.append(
            {
                "type": "function",
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema["input_schema"],
                # Existing read tools have optional fields. Strict normalization
                # would require them all; runtime tool validation stays authoritative.
                "strict": False,
            }
        )
    return definitions


def _parse(response: httpx.Response) -> ModelResponse:
    if response.is_error:
        guidance = {
            400: "Check that the configured model supports Responses API function calling.",
            401: "Check OPENAI_API_KEY on the server.",
            403: "Check the OpenAI project's access to the configured model.",
            404: "Check MYCELIUM_DOCGEN_OPENAI_MODEL and model access.",
            429: "Check OpenAI quota or retry after the rate limit clears.",
        }.get(response.status_code, "Retry when the OpenAI service is available.")
        raise ValueError(
            f"OpenAI documentation request failed (HTTP {response.status_code}). {guidance}"
        )
    envelope = _Response.model_validate_json(response.content)
    if envelope.status != "completed":
        raise ValueError("OpenAI documentation response did not complete")
    calls = [
        _FunctionCall.model_validate(item)
        for item in envelope.output
        if item.get("type") == "function_call"
    ]
    if len(calls) > 1:
        raise ValueError("OpenAI returned parallel documentation tool calls")
    blocks: list[ResponseHistory | ToolUse] = [ResponseHistory(output=envelope.output)]
    for call in calls:
        blocks.append(
            ToolUse(
                id=call.call_id,
                name=call.name,
                input=_JSON_OBJECT.validate_json(call.arguments),
            )
        )
    details = envelope.usage.get("input_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    usage = Usage.model_validate(
        {
            "input_tokens": envelope.usage.get("input_tokens", 0),
            "output_tokens": envelope.usage.get("output_tokens", 0),
            "cache_read_input_tokens": cached,
        }
    )
    return ModelResponse(content=blocks, usage=usage)


class OpenAIModel:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def turn(
        self,
        *,
        config: DocgenConfig,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        system: str,
        force_tool: str | None,
    ) -> ModelResponse:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ValueError("Set OPENAI_API_KEY on the server.")
        if not config.model:
            raise ValueError("Set MYCELIUM_DOCGEN_OPENAI_MODEL on the server.")
        payload: dict[str, JsonValue] = {
            "model": config.model,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "instructions": system,
            "input": _input(messages),
            "tools": _tools(tools),
            "parallel_tool_calls": False,
            "tool_choice": {"type": "function", "name": force_tool}
            if force_tool
            else "auto",
            "max_output_tokens": config.max_tokens,
        }
        try:
            if self._client is not None:
                response = self._client.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=config.request_timeout_s,
                )
            else:
                with httpx.Client() as client:
                    response = client.post(
                        "https://api.openai.com/v1/responses",
                        json=payload,
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=config.request_timeout_s,
                    )
        except httpx.HTTPError:
            raise ValueError(
                "OpenAI documentation request failed to reach the API"
            ) from None
        try:
            return _parse(response)
        except ValidationError:
            raise ValueError("OpenAI returned malformed documentation output") from None
