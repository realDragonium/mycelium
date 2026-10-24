"""Provider-neutral tool turns and typed structured output for language models."""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from anthropic import AnthropicError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from .. import request_timing
from . import claude, openai, usage
from .claude import ClaudeClient
from .types import (
    IncompleteTurn,
    ModelConfig,
    ModelError,
    ModelResponse,
    Output,
    Provider,
    ProviderHistory,
    ReasoningEffort,
    StructuredTask,
    ToolTask,
    ToolUse,
    Usage,
)

__all__ = [
    "ClaudeClient",
    "IncompleteTurn",
    "ModelConfig",
    "ModelError",
    "ModelResponse",
    "Provider",
    "ProviderHistory",
    "ReasoningEffort",
    "StructuredTask",
    "ToolTask",
    "ToolUse",
    "Usage",
    "structured",
    "structured_with_usage",
    "turn",
    "usage",
]


_LOG = logging.getLogger(__name__)


def _provider_failure(
    provider: Provider,
    operation: Literal["turn", "structured"],
    exc: ValidationError | AnthropicError,
) -> ModelError:
    status = exc.status_code if isinstance(exc, APIStatusError) else None
    category = (
        "validation"
        if isinstance(exc, ValidationError)
        else "timeout"
        if isinstance(exc, APITimeoutError)
        else "http"
        if isinstance(exc, APIStatusError)
        else "client"
    )
    # Validation paths and exception messages can contain supplied evidence.
    _LOG.warning(
        "AI provider failure provider=%s operation=%s category=%s status=%s errors=%s",
        provider,
        operation,
        category,
        status,
        exc.error_count() if isinstance(exc, ValidationError) else None,
    )
    if isinstance(exc, ValidationError):
        return ModelError(
            "Model returned malformed structured output"
            if operation == "structured"
            else "Model returned malformed output or conversation data"
        )
    if isinstance(exc, APITimeoutError):
        return ModelError("Claude request timed out")
    if isinstance(exc, APIStatusError):
        guidance = (
            " Check the model ID, reasoning effort and thinking settings in AI settings."
            if exc.status_code == 400
            else ""
        )
        return ModelError(f"Claude request failed (HTTP {exc.status_code}).{guidance}")
    return ModelError(
        "Claude request failed; check server credentials and model configuration"
    )


def turn(
    task: ToolTask,
    config: ModelConfig,
    *,
    client: ClaudeClient | httpx.Client | None = None,
) -> ModelResponse:
    with usage.metered(config) as report:
        try:
            if config.provider == "claude":
                with request_timing.phase("model"):
                    response = claude.turn(task, config, client)
            elif client is not None and not isinstance(client, httpx.Client):
                raise ModelError(
                    "OpenAI requires an HTTP client for transport injection"
                )
            else:
                with request_timing.phase("model"):
                    response = openai.turn(task, config, client)
        except (ValidationError, AnthropicError) as exc:
            raise _provider_failure(config.provider, "turn", exc) from None
        report(response.usage)
        return response


def structured(
    task: StructuredTask[Output],
    config: ModelConfig,
    *,
    client: httpx.Client | None = None,
) -> Output:
    return structured_with_usage(task, config, client=client)[0]


def structured_with_usage(
    task: StructuredTask[Output],
    config: ModelConfig,
    *,
    client: httpx.Client | None = None,
) -> tuple[Output, Usage]:
    """`structured`, plus the tokens the request used."""
    with usage.metered(config) as report:
        try:
            with request_timing.phase("model"):
                result = (
                    claude.structured(task, config, client)
                    if config.provider == "claude"
                    else openai.structured(task, config, client)
                )
        except (ValidationError, AnthropicError) as exc:
            raise _provider_failure(config.provider, "structured", exc) from None
        report(result[1])
        return result
