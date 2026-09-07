"""Claude task transport, including signed history and prompt cache boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Protocol, TypedDict, runtime_checkable

import httpx
from anthropic import Anthropic
from anthropic.types import (
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    ThinkingConfigParam,
    ToolChoiceParam,
    ToolUnionParam,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .types import (
    CLAUDE_EFFORT,
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


class ClaudeMessages(Protocol):
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str | Iterable[TextBlockParam],
        messages: Iterable[MessageParam],
        tools: Iterable[ToolUnionParam],
        tool_choice: ToolChoiceParam,
        thinking: ThinkingConfigParam = ...,
        output_config: OutputConfigParam = ...,
    ) -> object: ...


@runtime_checkable
class ClaudeClient(Protocol):
    @property
    def messages(self) -> ClaudeMessages: ...

    def with_options(self, *, timeout: float, max_retries: int) -> ClaudeClient: ...


class _RequiredRequest(TypedDict):
    model: str
    max_tokens: int
    system: str | Iterable[TextBlockParam]
    messages: Iterable[MessageParam]
    tools: Iterable[ToolUnionParam]
    tool_choice: ToolChoiceParam


class _Request(_RequiredRequest, total=False):
    thinking: ThinkingConfigParam
    output_config: OutputConfigParam


class _StructuredRequired(TypedDict):
    model: str
    max_tokens: int
    system: str
    messages: Iterable[MessageParam]


class _StructuredRequest(_StructuredRequired, total=False):
    thinking: ThinkingConfigParam
    output_config: OutputConfigParam


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    content: list[object]
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str


class _BlockKind(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    type: str


class _Text(_BlockKind):
    text: str


class _Thinking(_BlockKind):
    thinking: str
    signature: str = ""


class _RedactedThinking(_BlockKind):
    data: str


_SDK_MESSAGES = TypeAdapter(list[MessageParam])
_SDK_TOOLS = TypeAdapter(list[ToolUnionParam])


def _block(block: object) -> dict[str, JsonValue]:
    if isinstance(block, BaseModel) or isinstance(block, dict):
        return json_block(block)
    # Old loop fixtures expose SDK-shaped objects. Validate their attributes at
    # this single injection boundary; production SDK blocks serialize directly.
    kind = _BlockKind.model_validate(block).type
    if kind == "tool_use":
        return json_block(ToolUse.model_validate(block))
    if kind == "text":
        return json_block(_Text.model_validate(block))
    if kind == "thinking":
        return json_block(_Thinking.model_validate(block))
    if kind == "redacted_thinking":
        return json_block(_RedactedThinking.model_validate(block))
    raise ModelError("Unsupported Claude conversation block")


def _messages(task: ToolTask, config: ModelConfig) -> list[MessageParam]:
    messages: list[dict[str, JsonValue]] = []
    for message in MESSAGES.validate_python(task.messages):
        if isinstance(message.content, str):
            messages.append({"role": message.role, "content": message.content})
            continue
        blocks: list[dict[str, JsonValue]] = []
        continuation = [
            item for block in message.content if (item := history(block)) is not None
        ]
        if any(item.provider != "claude" for item in continuation):
            raise ModelError("Cannot change providers within a model conversation")
        for block in message.content:
            original = history(block)
            if original is not None:
                blocks.extend(original.output)
            else:
                data = _block(block)
                if data.get("type") == "tool_use" and continuation:
                    continue
                blocks.append(data)
        if task.force_tool:
            blocks = [
                block
                for block in blocks
                if block.get("type") not in ("thinking", "redacted_thinking")
            ]
        if blocks:
            messages.append({"role": message.role, "content": [*blocks]})
    if config.cache and messages:
        last = dict(messages[-1])
        content = last.get("content")
        if isinstance(content, str) and content:
            last["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content and isinstance(content[-1], dict):
            last["content"] = [
                *content[:-1],
                {**content[-1], "cache_control": {"type": "ephemeral"}},
            ]
        messages[-1] = last
    validated = _SDK_MESSAGES.validate_python(messages)
    for message in validated:
        content = message["content"]
        if not isinstance(content, str):
            message["content"] = list(content)
    return validated


@contextmanager
def transport(
    config: ModelConfig, http_client: httpx.Client | None = None
) -> Iterator[Anthropic]:
    client = Anthropic(
        http_client=http_client,
        timeout=config.request_timeout_s,
        max_retries=config.max_retries,
    )
    try:
        yield client
    finally:
        if http_client is None:
            client.close()


def _turn(task: ToolTask, config: ModelConfig, client: ClaudeClient) -> ModelResponse:
    tools = TOOLS.validate_python(task.tools)
    if task.force_tool and task.force_tool not in {tool.name for tool in tools}:
        raise ModelError("Required tool is not defined for this task")
    system: str | list[TextBlockParam] = task.system
    if config.cache:
        system = [
            {
                "type": "text",
                "text": task.system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    choice: ToolChoiceParam = (
        {"type": "tool", "name": task.force_tool, "disable_parallel_tool_use": True}
        if task.force_tool
        else {"type": "auto", "disable_parallel_tool_use": not task.parallel_tools}
    )
    request: _Request = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": _messages(task, config),
        "tools": _SDK_TOOLS.validate_python(
            [tool.model_dump(exclude_none=True) for tool in tools]
        ),
        "tool_choice": choice,
    }
    if config.reasoning_effort is not None:
        request["output_config"] = {
            "effort": CLAUDE_EFFORT.validate_python(config.reasoning_effort)
        }
    if config.thinking and not task.force_tool:
        request["thinking"] = {"type": "adaptive"}
    response = _Response.model_validate(
        client.with_options(
            timeout=config.request_timeout_s, max_retries=config.max_retries
        ).messages.create(**request)
    )
    if response.stop_reason not in ("end_turn", "tool_use"):
        raise ModelError("Claude response was incomplete or unsuccessful")
    output = [_block(block) for block in response.content]
    calls = [
        ToolUse.model_validate(
            {
                key: value
                for key, value in block.items()
                if key in ("type", "id", "name", "input")
            }
        )
        for block in output
        if block.get("type") == "tool_use"
    ]
    validate_calls(task, calls)
    return ModelResponse(
        content=[ProviderHistory(provider="claude", output=output), *calls],
        usage=response.usage,
        stop_reason=response.stop_reason,
    )


def turn(
    task: ToolTask, config: ModelConfig, client: ClaudeClient | httpx.Client | None
) -> ModelResponse:
    if isinstance(client, ClaudeClient):
        return _turn(task, config, client)
    with transport(config, client) as owned:
        return _turn(task, config, owned)


def structured(
    task: StructuredTask[Output], config: ModelConfig, client: httpx.Client | None
) -> Output:
    request: _StructuredRequest = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": task.system,
        "messages": [{"role": "user", "content": task.prompt}],
    }
    if config.reasoning_effort is not None:
        request["output_config"] = {
            "effort": CLAUDE_EFFORT.validate_python(config.reasoning_effort)
        }
    if config.thinking:
        request["thinking"] = {"type": "adaptive"}
    with transport(config, client) as sdk:
        response = sdk.messages.parse(**request, output_format=task.output_type)
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise ModelError("Claude did not return one complete structured result")
    return response.parsed_output
