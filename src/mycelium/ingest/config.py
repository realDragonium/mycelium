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
from dataclasses import dataclass
from pathlib import Path

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort

#: Current Sonnet model id (confirmed against Anthropic's model catalog).
DEFAULT_MODEL = "claude-sonnet-4-6"

#: The reasoning doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")

#: Prompt-store name the ingest doctrine is kept under (type `doctrine`).
#: Startup seeds that row from `doctrine_path`; the loop reads it per run,
#: so an edit through `save_prompt_text` lands on the next ingest.
DOCTRINE_NAME = "ingest"


@dataclass(frozen=True)
class IngestConfig:
    model: str = DEFAULT_MODEL
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    #: Hard ceiling on substrate operations per call. Vocab fetch + every
    #: reconcile read counts toward it. Higher than ask's: ingest reconciles
    #: per-candidate, so it spends far more reads.
    op_cap: int = 50
    #: Whole-call wall-clock budget, seconds. On exhaustion we degrade to a
    #: forced emit (or NothingToIngest) rather than throwing.
    wall_clock_s: float = 120.0
    #: max_tokens per model turn. Comfortably above a structured emit.
    max_tokens: int = 8000
    #: Provider retries cover 429/5xx/connection with exponential backoff;
    #: this raises its default 2 for the slow-substrate environment.
    max_retries: int = 4
    #: Per-model-call timeout, seconds. Kept under the wall clock so a
    #: single hung call can't blow the whole budget.
    request_timeout_s: float = 90.0
    #: Adaptive thinking in the loop (disabled only on the forced emit call,
    #: where a forced tool_choice is incompatible with it).
    thinking: bool = True
    #: Cap on input text. Longer input is head-truncated and a gap recorded —
    #: never silently blown past.
    max_input_chars: int = 20000
    #: Path to the reasoning doctrine injected into the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: Cost rates are populated only for the known default Claude model.
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    #: JSONL sink for the trace. None → resolved by the caller to a default
    #: under the data dir (see server wiring).
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/find); empty string disables file writing.
    trace_dir: str | None = None

    @classmethod
    def from_env(cls) -> "IngestConfig":
        def _f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        limits = product_settings.get(product_settings.IngestSettings)
        selected = model_settings.get("ingest")

        return cls(
            model=selected.model,
            provider=selected.provider,
            reasoning_effort=selected.reasoning_effort,
            op_cap=limits.op_cap,
            wall_clock_s=limits.wall_clock_s,
            max_tokens=limits.max_tokens,
            max_retries=limits.max_retries,
            request_timeout_s=limits.request_timeout_s,
            thinking=limits.thinking,
            max_input_chars=limits.max_input_chars,
            doctrine_path=(
                os.environ.get("MYCELIUM_INGEST_DOCTRINE_PATH")
                or _DEFAULT_DOCTRINE_PATH
            ),
            input_per_mtok=(
                _f("MYCELIUM_INGEST_INPUT_PER_MTOK", 3.0)
                if selected.provider == "claude" and selected.model == DEFAULT_MODEL
                else None
            ),
            output_per_mtok=(
                _f("MYCELIUM_INGEST_OUTPUT_PER_MTOK", 15.0)
                if selected.provider == "claude" and selected.model == DEFAULT_MODEL
                else None
            ),
            trace_log_path=os.environ.get("MYCELIUM_INGEST_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_INGEST_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
