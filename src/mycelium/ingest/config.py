"""Tunables for the `ingest` write-harness loop.

The model is the one saved for the `ingest` action in AI settings, picked from
the admin's model catalog; there is no built-in default. One model, one
context drives extract -> reconcile -> classify -> link -> emit. Task budgets
come from saved AI settings.

`ingest` runs hotter than `ask`: it reconciles *every* extracted candidate
against the substrate, so the op cap and wall clock are larger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort

#: The reasoning doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the ingest doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit in Settings → Prompts lands on the next ingest.
DOCTRINE_NAME: Final = "ingest"


@dataclass(frozen=True)
class IngestConfig:
    model: str = ""
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    limits: product_settings.IngestSettings = field(
        default_factory=product_settings.IngestSettings
    )
    #: Path to the reasoning doctrine injected into the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: Most tokens one run may use, cache reads included; None (or 0) leaves
    #: the op cap and wall clock as the only bounds.
    max_run_tokens: int | None = None
    #: JSONL sink for the trace. None → resolved by the caller to a default
    #: under the data dir (see server wiring).
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/find); empty string disables file writing.
    trace_dir: str | None = None

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
