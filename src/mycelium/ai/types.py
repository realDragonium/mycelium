"""Task and response contracts shared by Mycelium's language-model workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
)

Provider = Literal["claude", "openai"]
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
CLAUDE_EFFORT = TypeAdapter(ClaudeEffort)
REASONING_EFFORT = TypeAdapter(ReasoningEffort)
Output = TypeVar("Output", bound=BaseModel)


@dataclass(frozen=True)
class ModelConfig:
    provider: Provider
    model: str
    max_tokens: int
    request_timeout_s: float
    max_retries: int = 0
    thinking: bool = False
    cache: bool = False
    reasoning_effort: ReasoningEffort | None = None

    def __post_init__(self) -> None:
        if self.reasoning_effort is not None:
            adapter = CLAUDE_EFFORT if self.provider == "claude" else REASONING_EFFORT
            adapter.validate_python(self.reasoning_effort)
        if self.provider not in ("claude", "openai"):
            raise ValueError("Model provider must be claude or openai")
        if not self.model.strip():
            raise ValueError("A model ID is required")
        if self.max_tokens < 1 or self.request_timeout_s <= 0 or self.max_retries < 0:
            raise ValueError("Invalid model request limits")


@dataclass(frozen=True)
class ToolTask:
    system: str
    messages: Sequence[Mapping[str, object]]
    tools: Sequence[Mapping[str, object]]
    force_tool: str | None = None
    parallel_tools: bool = False


@dataclass(frozen=True)
class StructuredTask(Generic[Output]):
    system: str
    prompt: str
    output_type: type[Output]


class ToolUse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, JsonValue]


class ProviderHistory(BaseModel):
    type: Literal["provider_history"] = "provider_history"
    provider: Provider
    output: list[dict[str, JsonValue]]


class Usage(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)

    @field_validator(
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        mode="before",
    )
    @classmethod
    def absent_usage_is_zero(cls, value: object) -> object:
        return 0 if value is None else value


class ModelResponse(BaseModel):
    content: list[ProviderHistory | ToolUse]
    usage: Usage
    stop_reason: str


class ModelError(ValueError):
    """Safe provider failure text that can be persisted in a run or trace."""


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str | list[object]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    input_schema: dict[str, JsonValue]
    strict: bool | None = None


JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
MESSAGES = TypeAdapter(list[Message])
TOOLS = TypeAdapter(list[ToolDefinition])


def history(block: object) -> ProviderHistory | None:
    if isinstance(block, ProviderHistory):
        return block
    if isinstance(block, Mapping) and block.get("type") == "provider_history":
        return ProviderHistory.model_validate(block)
    return None


def json_block(block: object) -> dict[str, JsonValue]:
    if isinstance(block, BaseModel):
        return JSON_OBJECT.validate_python(
            block.model_dump(mode="json", exclude_none=True)
        )
    return JSON_OBJECT.validate_python(block)


def validate_calls(task: ToolTask, calls: list[ToolUse]) -> None:
    if not task.parallel_tools and len(calls) > 1:
        raise ModelError("Model returned parallel tool calls for a serial task")
    if task.force_tool and (len(calls) != 1 or calls[0].name != task.force_tool):
        raise ModelError("Model did not return the required tool call")
    if len({call.id for call in calls}) != len(calls):
        raise ModelError("Model returned duplicate tool call identifiers")
