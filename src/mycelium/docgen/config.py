"""Tunables for the documentation-generation loop.

The model is the one saved for the `docgen` action in AI settings for the
chosen provider, picked from the admin's model catalog; there is no built-in
default. Task budgets come from saved AI settings. A generation
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypedDict

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort
from ..guidelines import SET_NAME

#: The generation doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the docgen doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit in Settings → Prompts lands on the next documentation run.
DOCTRINE_NAME: Final = "docgen"


def resolve_provider(value: str | None = None) -> Provider:
    selected = value if value is not None else model_settings.get("docgen").provider
    if selected == "claude":
        return "claude"
    if selected == "openai":
        return "openai"
    raise ValueError("documentation provider must be claude or openai")


class ModelChoice(TypedDict):
    provider: Provider | Literal["agent"]
    label: str
    model: str | None
    reasoning_effort: ReasoningEffort | None
    available: bool
    reason: str | None


def model_choices() -> list[ModelChoice]:
    choices: list[ModelChoice] = []
    for provider in ("claude", "openai"):
        config = DocgenConfig.from_env(provider=resolve_provider(provider))
        reason = None
        if not config.model:
            reason = model_settings.missing_model("docgen", config.provider)
        else:
            reason = model_settings.provider_availability(config.provider).reason
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
    if model_settings.get("docgen").external_agent:
        choices.append(
            {
                "provider": "agent",
                "label": "External agent",
                "model": None,
                "reasoning_effort": None,
                "available": True,
                "reason": None,
            }
        )
    return choices


@dataclass(frozen=True)
class DocgenConfig:
    model: str = ""
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    #: The set this instance prefers when the request named none. It is a
    #: preference the resolution step is told about, not an override: the
    #: request wins, and a prompt that plainly asks for another configured
    #: set wins too. Defaults to the one set that ships, so an instance that
    #: has only ever been booted (never configured) still has a preference.
    guideline_set: str = SET_NAME
    limits: product_settings.DocgenSettings = field(
        default_factory=product_settings.DocgenSettings
    )
    #: Path to the docgen doctrine seeded into the store and injected into
    #: the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: JSONL sink for the trace. None disables it.
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/ingest); empty string disables writing.
    trace_dir: str | None = None

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
            limits=limits,
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
