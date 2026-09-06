"""Provider-neutral tool turns and typed structured output for language models."""

from __future__ import annotations

import httpx
from anthropic import AnthropicError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from . import claude, openai
from .claude import ClaudeClient
from .types import (
    ModelConfig,
    ModelError,
    ModelResponse,
    Output,
    Provider,
    ProviderHistory,
    StructuredTask,
    ToolTask,
    ToolUse,
    Usage,
)

__all__ = [
    "ClaudeClient",
    "ModelConfig",
    "ModelError",
    "ModelResponse",
    "Provider",
    "ProviderHistory",
    "StructuredTask",
    "ToolTask",
    "ToolUse",
    "Usage",
    "structured",
    "turn",
]


def turn(
    task: ToolTask,
    config: ModelConfig,
    *,
    client: ClaudeClient | httpx.Client | None = None,
) -> ModelResponse:
    try:
        if config.provider == "claude":
            return claude.turn(task, config, client)
        if client is not None and not isinstance(client, httpx.Client):
            raise ModelError("OpenAI requires an HTTP client for transport injection")
        return openai.turn(task, config, client)
    except ValidationError:
        raise ModelError(
            "Model returned malformed output or conversation data"
        ) from None
    except APITimeoutError:
        raise ModelError("Claude request timed out") from None
    except APIStatusError as exc:
        raise ModelError(f"Claude request failed (HTTP {exc.status_code})") from None
    except AnthropicError:
        raise ModelError(
            "Claude request failed; check server credentials and model configuration"
        ) from None


def structured(
    task: StructuredTask[Output],
    config: ModelConfig,
    *,
    client: httpx.Client | None = None,
) -> Output:
    try:
        if config.provider == "claude":
            return claude.structured(task, config, client)
        return openai.structured(task, config, client)
    except ValidationError:
        raise ModelError("Model returned malformed structured output") from None
    except APITimeoutError:
        raise ModelError("Claude request timed out") from None
    except APIStatusError as exc:
        raise ModelError(f"Claude request failed (HTTP {exc.status_code})") from None
    except AnthropicError:
        raise ModelError(
            "Claude request failed; check server credentials and model configuration"
        ) from None
