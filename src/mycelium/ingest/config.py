"""Tunables for the `ingest` write-harness loop.

Config follows the repo convention (ask/config.py, embed.py, http.py):
module-level defaults read from `MYCELIUM_INGEST_*` env vars with inline
fallbacks. No central settings module.

The model default is **Sonnet** (`claude-sonnet-4-6`) — one model, one context
drives extract -> reconcile -> classify -> link -> emit. The id is config,
never hardcoded in logic; override with `MYCELIUM_INGEST_MODEL`.

`ingest` runs hotter than `ask`: it reconciles *every* extracted candidate
against the substrate, so the op cap and wall clock are larger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import tracing

#: Current Sonnet model id (confirmed against Anthropic's model catalog).
DEFAULT_MODEL = "claude-sonnet-4-6"

#: The reasoning doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")


@dataclass(frozen=True)
class IngestConfig:
    model: str = DEFAULT_MODEL
    #: Hard ceiling on substrate operations per call. Vocab fetch + every
    #: reconcile read counts toward it. Higher than ask's: ingest reconciles
    #: per-candidate, so it spends far more reads.
    op_cap: int = 50
    #: Whole-call wall-clock budget, seconds. On exhaustion we degrade to a
    #: forced emit (or NothingToIngest) rather than throwing.
    wall_clock_s: float = 120.0
    #: max_tokens per model turn. Comfortably above a structured emit.
    max_tokens: int = 8000
    #: Anthropic SDK auto-retries 429/5xx/connection with exponential backoff;
    #: this raises its default 2 for the slow-substrate environment.
    max_retries: int = 4
    #: Per-Anthropic-call timeout, seconds. Kept under the wall clock so a
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
    #: Sonnet pricing, $ / 1M tokens — used only to stamp an estimated cost on
    #: the trace. Override via MYCELIUM_INGEST_INPUT_PER_MTOK / _OUTPUT_PER_MTOK
    #: when running a non-default model.
    input_per_mtok: float = 3.0
    output_per_mtok: float = 15.0
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

        def _i(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        return cls(
            model=os.environ.get("MYCELIUM_INGEST_MODEL") or DEFAULT_MODEL,
            op_cap=_i("MYCELIUM_INGEST_OP_CAP", 50),
            wall_clock_s=_f("MYCELIUM_INGEST_WALL_CLOCK_S", 120.0),
            max_tokens=_i("MYCELIUM_INGEST_MAX_TOKENS", 8000),
            max_retries=_i("MYCELIUM_INGEST_MAX_RETRIES", 4),
            request_timeout_s=_f("MYCELIUM_INGEST_REQUEST_TIMEOUT_S", 90.0),
            thinking=(os.environ.get("MYCELIUM_INGEST_THINKING", "on").lower() != "off"),
            max_input_chars=_i("MYCELIUM_INGEST_MAX_INPUT_CHARS", 20000),
            doctrine_path=(
                os.environ.get("MYCELIUM_INGEST_DOCTRINE_PATH") or _DEFAULT_DOCTRINE_PATH
            ),
            input_per_mtok=_f("MYCELIUM_INGEST_INPUT_PER_MTOK", 3.0),
            output_per_mtok=_f("MYCELIUM_INGEST_OUTPUT_PER_MTOK", 15.0),
            trace_log_path=os.environ.get("MYCELIUM_INGEST_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_INGEST_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
