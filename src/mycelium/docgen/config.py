"""Tunables for the documentation-generation loop.

Model choices use saved per-action settings, with legacy environment values imported
once on upgrade. Task budgets come from saved AI settings.

Claude remains the default, with the same built-in model as ingest. GPT uses an
explicitly configured model ID. A generation
run surveys the substrate before it writes a word, so the op cap and wall
clock are sized well beyond a single `ask` question.

A run reads TWO kinds of steering text, and only one of them is a file here.
The GUIDELINE SET says how to write a document and lives entirely in the
prompt store as rows an operator can edit or add without a redeploy
(docs/GUIDELINE_SETS.md) — `guideline_set` below is only the instance's
preferred set, never a path. The DOCTRINE says how to run the loop that
writes one, and follows its siblings exactly: a packaged file seeds the
`(doctrine, docgen)` row at startup, and the loop reads the row per run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort, pricing
from ..guidelines import SET_NAME
from ..ingest.config import DEFAULT_MODEL
from ..model_credentials import (
    claude_configuration_error as _claude_configuration_error,
)

#: The generation doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the docgen doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit through `save_prompt_text` lands on the next documentation run.
DOCTRINE_NAME: Final = "docgen"


def resolve_provider(value: str | None = None) -> Provider:
    selected = value if value is not None else model_settings.get("docgen").provider
    if selected == "claude":
        return "claude"
    if selected == "openai":
        return "openai"
    raise ValueError("documentation provider must be claude or openai")


class ModelChoice(TypedDict):
    provider: Provider
    label: str
    model: str | None
    reasoning_effort: ReasoningEffort | None
    available: bool
    reason: str | None


def model_choices() -> list[ModelChoice]:
    choices: list[ModelChoice] = []
    for provider in ("claude", "openai"):
        config = DocgenConfig.from_env(provider=resolve_provider(provider))
        key = "ANTHROPIC_API_KEY" if provider == "claude" else "OPENAI_API_KEY"
        reason = None
        if not config.model:
            reason = (
                "Choose an OpenAI documentation model in AI settings."
                if provider == "openai"
                else "Choose a Claude documentation model in AI settings."
            )
        elif provider == "claude":
            reason = _claude_configuration_error()
        elif not os.environ.get(key, "").strip():
            reason = f"Set {key} on the server."
        choices.append(
            {
                "provider": config.provider,
                "label": "Claude" if provider == "claude" else "GPT",
                "model": config.model or None,
                "reasoning_effort": config.reasoning_effort,
                "available": reason is None,
                "reason": reason,
            }
        )
    return choices


@dataclass(frozen=True)
class DocgenConfig:
    model: str = DEFAULT_MODEL
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    #: The set this instance prefers when the request named none. It is a
    #: preference the resolution step is told about, not an override: the
    #: request wins, and a prompt that plainly asks for another configured
    #: set wins too. Defaults to the one set that ships, so an instance that
    #: has only ever been booted (never configured) still has a preference.
    guideline_set: str = SET_NAME
    #: Hard ceiling on tool operations per run. Every substrate read the run
    #: makes while gathering material counts toward it.
    op_cap: int = 150
    #: Whole-run wall-clock budget, seconds. A run holds a shared model-loop
    #: slot for its whole life, so this is also how long one request can keep
    #: that slot from `ask` and `ingest`.
    wall_clock_s: float = 900.0
    #: max_tokens per model turn. A document body is the largest single thing
    #: any loop in this tree emits, and adaptive thinking shares the budget.
    max_tokens: int = 32000
    #: Provider retries cover 429/5xx/connection with exponential backoff.
    max_retries: int = 4
    #: Per-model-call timeout, seconds. Kept well under the wall clock so
    #: a single hung call can't blow the whole budget.
    request_timeout_s: float = 120.0
    #: Adaptive thinking in the loop.
    thinking: bool = True
    #: Cap on the requested prompt. Enforced at the door by
    #: `request_documentation`, which refuses rather than truncates: a
    #: documentation request is something a person typed, and silently
    #: dropping its tail would generate the wrong document instead of an
    #: error the caller can act on.
    max_prompt_chars: int = 2000
    #: Width of the opening `survey_statements` map of the request. Wider
    #: than ask's recon: a document covers a topic, not a question.
    recon_k: int = 30
    #: Path to the docgen doctrine seeded into the store and injected into
    #: the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: JSONL sink for the trace. None disables it.
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/ingest); empty string disables writing.
    trace_dir: str | None = None

    @property
    def price(self) -> pricing.Price | None:
        return pricing.price(self.provider, self.model)

    @classmethod
    def from_env(cls, *, provider: Provider | None = None) -> DocgenConfig:
        limits = product_settings.get(product_settings.DocgenSettings)
        selected = model_settings.get("docgen")
        selected_provider = (
            selected.provider if provider is None else resolve_provider(provider)
        )
        selected_model = (
            selected.claude_model
            if selected_provider == "claude"
            else selected.openai_model
        )

        return cls(
            provider=selected_provider,
            reasoning_effort=selected.effort_for(selected_provider),
            model=selected_model,
            guideline_set=product_settings.get(
                product_settings.DocumentationSettings
            ).guideline_set,
            op_cap=limits.op_cap,
            wall_clock_s=limits.wall_clock_s,
            max_tokens=limits.max_tokens,
            max_retries=limits.max_retries,
            request_timeout_s=limits.request_timeout_s,
            thinking=limits.thinking,
            max_prompt_chars=limits.max_prompt_chars,
            recon_k=limits.recon_k,
            doctrine_path=(
                os.environ.get("MYCELIUM_DOCGEN_DOCTRINE_PATH")
                or _DEFAULT_DOCTRINE_PATH
            ),
            trace_log_path=os.environ.get("MYCELIUM_DOCGEN_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_DOCGEN_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
