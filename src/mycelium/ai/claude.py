"""Claude task transport, including signed history and prompt cache boundaries."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Protocol, TypedDict, runtime_checkable

import httpx
from anthropic import Anthropic, BadRequestError
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
    IncompleteTurn,
    ModelConfig,
    ModelError,
    ModelResponse,
    Output,
    ProviderHistory,
    StructuredTask,
    ToolDefinition,
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


_LOG = logging.getLogger(__name__)

#: Models that reject a forced `tool_choice` ("tool" or "any") with a 400 and
#: tie thinking blocks to an unedited history. A required tool is asked for in
#: the prompt instead, and `validate_calls` still insists on that one call.
_UNFORCEABLE = frozenset(
    {"claude-fable-5-1", "claude-mythos-5-1", "claude-opus-5-5", "claude-sonnet-5-5"}
)
#: Models outside that list that turned out to refuse a forced tool choice,
#: learnt from the refusal and kept for the life of the process.
_refused_forcing: set[str] = set()


def _forced(task: ToolTask, config: ModelConfig) -> bool:
    return (
        bool(task.force_tool)
        and config.model not in _UNFORCEABLE
        and config.model not in _refused_forcing
    )


def _refuses_forcing(error: BadRequestError) -> bool:
    message = str(error)
    return "tool_choice" in message and "not supported for this model" in message


def _messages(task: ToolTask, config: ModelConfig) -> list[MessageParam]:
    forced = _forced(task, config)
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
        if forced:
            blocks = [
                block
                for block in blocks
                if block.get("type") not in ("thinking", "redacted_thinking")
            ]
        if blocks:
            messages.append({"role": message.role, "content": [*blocks]})
    if task.force_tool and not forced and messages:
        last = dict(messages[-1])
        content = last.get("content")
        request: dict[str, JsonValue] = {
            "type": "text",
            "text": f"Respond now by calling the `{task.force_tool}` tool exactly once.",
        }
        last["content"] = (
            [{"type": "text", "text": content}, request]
            if isinstance(content, str)
            else [*content, request]
            if isinstance(content, list)
            else [request]
        )
        messages[-1] = last
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
    for param in validated:
        if not isinstance(param["content"], str):
            param["content"] = list(param["content"])
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
    try:
        response = _send(task, config, client, system, tools)
    except BadRequestError as error:
        if not (_forced(task, config) and _refuses_forcing(error)):
            raise
        _refused_forcing.add(config.model)
        _LOG.warning(
            "Model %s refuses a forced tool_choice; add it to _UNFORCEABLE.",
            config.model,
        )
        response = _send(task, config, client, system, tools)
    if response.stop_reason not in ("end_turn", "tool_use"):
        raise IncompleteTurn(
            "Claude response was incomplete or unsuccessful "
            f"(stop_reason={response.stop_reason})",
            response.usage,
        )
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


def _send(
    task: ToolTask,
    config: ModelConfig,
    client: ClaudeClient,
    system: str | list[TextBlockParam],
    tools: list[ToolDefinition],
) -> _Response:
    forced = _forced(task, config)
    choice: ToolChoiceParam = (
        {"type": "tool", "name": task.force_tool, "disable_parallel_tool_use": True}
        if forced and task.force_tool
        else {
            "type": "auto",
            "disable_parallel_tool_use": bool(task.force_tool)
            or not task.parallel_tools,
        }
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
    if config.thinking and not forced:
        request["thinking"] = {"type": "adaptive"}
    configured = client.with_options(
        timeout=config.request_timeout_s, max_retries=config.max_retries
    )
    if isinstance(configured, Anthropic):
        # Streamed so the request timeout bounds a silent connection rather
        # than the whole turn. Writing a long document takes longer than any
        # sensible total timeout, and each timed-out attempt is generated,
        # billed and retried from scratch.
        return _stream_turn(task, request, configured)
    if task.on_tool_delta is not None:
        raise ModelError("Streaming Claude turns require an Anthropic transport")
    return _Response.model_validate(configured.messages.create(**request))


def _stream_turn(task: ToolTask, request: _Request, client: Anthropic) -> _Response:
    calls: dict[int, tuple[str, str]] = {}
    stopped = False
    with client.messages.stream(**request) as stream:
        for event in stream:
            if task.check_cancel:
                task.check_cancel()
            if event.type == "message_stop":
                stopped = True
            if (
                event.type == "content_block_start"
                and event.content_block.type == "tool_use"
            ):
                block = event.content_block
                calls[event.index] = (block.id, block.name)
            elif (
                event.type == "content_block_delta"
                and event.delta.type == "input_json_delta"
            ):
                identity = calls.get(event.index)
                if identity and task.on_tool_delta:
                    task.on_tool_delta(*identity, event.delta.partial_json)
        if not stopped:
            raise ModelError("Claude stream ended without a completed response")
        return _Response.model_validate(stream.get_final_message())


def turn(
    task: ToolTask, config: ModelConfig, client: ClaudeClient | httpx.Client | None
) -> ModelResponse:
    if isinstance(client, ClaudeClient):
        return _turn(task, config, client)
    with transport(config, client) as owned:
        return _turn(task, config, owned)


def structured(
    task: StructuredTask[Output], config: ModelConfig, client: httpx.Client | None
) -> tuple[Output, Usage]:
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
    return response.parsed_output, Usage.model_validate(response.usage)
