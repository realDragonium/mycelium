"""Responses requests with complete, ordered, stateless continuation history."""

from __future__ import annotations

import os
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .types import (
    JSON_OBJECT,
    MESSAGES,
    TOOLS,
    ModelConfig,
    ModelError,
    ModelResponse,
    Output,
    ProviderHistory,
    StructuredTask,
    ToolTask,
    ToolUse,
    Usage,
    history,
    json_block,
    validate_calls,
)


class Response(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    output: list[dict[str, JsonValue]]
    usage: dict[str, JsonValue] = Field(default_factory=dict)


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    call_id: str
    name: str
    arguments: str


def _input(task: ToolTask) -> list[dict[str, JsonValue]]:
    items: list[dict[str, JsonValue]] = []
    for message in MESSAGES.validate_python(task.messages):
        if isinstance(message.content, str):
            items.append({"role": message.role, "content": message.content})
            continue
        continuation = [
            item for block in message.content if (item := history(block)) is not None
        ]
        if any(item.provider != "openai" for item in continuation):
            raise ModelError("Cannot change providers within a model conversation")
        for block in message.content:
            original = history(block)
            if original is not None:
                items.extend(original.output)
                continue
            data = json_block(block)
            kind = data.get("type")
            if kind == "tool_use" and continuation:
                continue
            if kind == "tool_result":
                identity, content = data.get("tool_use_id"), data.get("content")
                if not isinstance(identity, str) or not isinstance(content, str):
                    raise ModelError("Invalid model tool result")
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": identity,
                        "output": content,
                    }
                )
            elif kind == "text" and isinstance(data.get("text"), str):
                items.append({"role": message.role, "content": data["text"]})
            else:
                raise ModelError("Unsupported OpenAI conversation block")
    return items


def _request(
    payload: dict[str, JsonValue], config: ModelConfig, client: httpx.Client | None
) -> Response:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ModelError("OPENAI_API_KEY is required on the server")
    owned = client is None
    transport = client or httpx.Client()
    try:
        for attempt in range(config.max_retries + 1):
            try:
                response = transport.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=config.request_timeout_s,
                )
            except httpx.RequestError:
                if attempt == config.max_retries:
                    raise ModelError("OpenAI request failed to reach the API") from None
            else:
                retryable = (
                    response.status_code in (408, 409, 429)
                    or response.status_code >= 500
                )
                if not retryable or attempt == config.max_retries:
                    if response.is_error:
                        guidance = {
                            400: "Check that the model supports the requested Responses API features.",
                            401: "Check OPENAI_API_KEY on the server.",
                            403: "Check the OpenAI project's access to the configured model.",
                            404: "Check the configured model ID and model access.",
                            429: "Check OpenAI quota or retry after the rate limit clears.",
                        }.get(
                            response.status_code,
                            "Retry when the OpenAI service is available.",
                        )
                        raise ModelError(
                            f"OpenAI request failed (HTTP {response.status_code}). {guidance}"
                        )
                    parsed = Response.model_validate_json(response.content)
                    if parsed.status != "completed":
                        raise ModelError(
                            "OpenAI response was incomplete or unsuccessful"
                        )
                    return parsed
            time.sleep(min(0.5 * 2**attempt, 8.0))
    finally:
        if owned:
            transport.close()
    raise ModelError("OpenAI request did not complete")


def turn(
    task: ToolTask, config: ModelConfig, client: httpx.Client | None
) -> ModelResponse:
    tools = TOOLS.validate_python(task.tools)
    if task.force_tool and task.force_tool not in {tool.name for tool in tools}:
        raise ModelError("Required tool is not defined for this task")
    definitions: list[JsonValue] = [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            # Tool argument validation remains in the feature's existing schema.
            "strict": False,
        }
        for tool in tools
    ]
    response = _request(
        {
            "model": config.model,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "instructions": task.system,
            "input": [*_input(task)],
            "tools": definitions,
            "parallel_tool_calls": task.parallel_tools and not task.force_tool,
            "tool_choice": {"type": "function", "name": task.force_tool}
            if task.force_tool
            else "auto",
            "max_output_tokens": config.max_tokens,
        },
        config,
        client,
    )
    calls: list[ToolUse] = []
    for item in response.output:
        if item.get("type") == "function_call":
            call = FunctionCall.model_validate(item)
            calls.append(
                ToolUse(
                    id=call.call_id,
                    name=call.name,
                    input=JSON_OBJECT.validate_json(call.arguments),
                )
            )
    validate_calls(task, calls)
    details = response.usage.get("input_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    usage = Usage.model_validate(
        {
            "input_tokens": response.usage.get("input_tokens", 0),
            "output_tokens": response.usage.get("output_tokens", 0),
            "cache_read_input_tokens": cached,
        }
    )
    # Claude reports uncached input separately; expose the same accounting here.
    usage.input_tokens = max(0, usage.input_tokens - usage.cache_read_input_tokens)
    return ModelResponse(
        content=[ProviderHistory(provider="openai", output=response.output), *calls],
        usage=usage,
        stop_reason="tool_use" if calls else "end_turn",
    )


def structured(
    task: StructuredTask[Output], config: ModelConfig, client: httpx.Client | None
) -> Output:
    response = _request(
        {
            "model": config.model,
            "store": False,
            "instructions": task.system,
            "input": [{"role": "user", "content": task.prompt}],
            "max_output_tokens": config.max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "structured_result",
                    "strict": True,
                    "schema": JSON_OBJECT.validate_python(
                        task.output_type.model_json_schema()
                    ),
                }
            },
        },
        config,
        client,
    )
    texts: list[str] = []
    for item in response.output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ModelError("OpenAI returned an invalid structured response")
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                raise ModelError("OpenAI did not return one complete structured result")
            value = part.get("text")
            if not isinstance(value, str):
                raise ModelError("OpenAI returned an invalid structured response")
            texts.append(value)
    if len(texts) != 1:
        raise ModelError("OpenAI did not return one complete structured result")
    return task.output_type.model_validate_json(texts[0])
