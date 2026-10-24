"""Tunables for the `ingest` write-harness loop.

Model choices use saved per-action settings, with legacy environment values imported
once on upgrade. Task budgets come from saved AI settings.

The model default is **Sonnet** (`claude-sonnet-4-6`) — one model, one context
drives extract -> reconcile -> classify -> link -> emit. The id is config,
never hardcoded in logic; choose it in AI settings.

`ingest` runs hotter than `ask`: it reconciles *every* extracted candidate
against the substrate, so the op cap and wall clock are larger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort, pricing

#: Current Sonnet model id (confirmed against Anthropic's model catalog).
DEFAULT_MODEL = "claude-sonnet-4-6"

#: The reasoning doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the ingest doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit in Settings → Prompts lands on the next ingest.
DOCTRINE_NAME: Final = "ingest"


@dataclass(frozen=True)
class IngestConfig:
    model: str = DEFAULT_MODEL
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    limits: product_settings.IngestSettings = field(
        default_factory=product_settings.IngestSettings
    )
    #: Path to the reasoning doctrine injected into the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: Spending cap per run, in USD. Needs a list price; without one the
    #: op cap and wall clock are the only bounds.
    max_cost_usd: float | None = None
    #: JSONL sink for the trace. None → resolved by the caller to a default
    #: under the data dir (see server wiring).
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/find); empty string disables file writing.
    trace_dir: str | None = None

    @property
    def price(self) -> pricing.Price | None:
        return pricing.price(self.provider, self.model)

    @classmethod
    def from_env(cls) -> IngestConfig:
        limits = product_settings.get(product_settings.IngestSettings)
        selected = model_settings.get("ingest")

        return cls(
            model=selected.model,
            provider=selected.provider,
            reasoning_effort=selected.reasoning_effort,
            limits=limits,
            doctrine_path=(
                os.environ.get("MYCELIUM_INGEST_DOCTRINE_PATH")
                or _DEFAULT_DOCTRINE_PATH
            ),
            trace_log_path=os.environ.get("MYCELIUM_INGEST_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_INGEST_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
