"""Tunables for the `research` write-harness loop.

Config follows the repo convention (ingest/config.py, ask/config.py):
module-level defaults read from `MYCELIUM_RESEARCH_*` env vars with inline
fallbacks. No central settings module.

The model default falls back to ingest's (`MYCELIUM_RESEARCH_MODEL` first,
then ingest's `DEFAULT_MODEL`). Research runs much hotter than ingest: the
loop explores a whole codebase before it ever reconciles, so the op cap and
wall clock are an order of magnitude larger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import tracing
from ..ingest.config import DEFAULT_MODEL

#: The research doctrine the inner model reads, shipped beside this package.
_DEFAULT_DOCTRINE_PATH = str(Path(__file__).resolve().parent / "doctrine.md")


@dataclass(frozen=True)
class ResearchConfig:
    model: str = DEFAULT_MODEL
    #: Hard ceiling on tool operations per run. Vocab fetch, every workspace
    #: read, and every reconcile read all count toward it.
    op_cap: int = 150
    #: Whole-run wall-clock budget, seconds. On exhaustion we degrade to a
    #: forced emit (or NothingFound) rather than throwing.
    wall_clock_s: float = 1200.0
    #: max_tokens per model turn. Comfortably above a structured emit.
    max_tokens: int = 8000
    #: Anthropic SDK auto-retries 429/5xx/connection with exponential backoff.
    max_retries: int = 4
    #: Per-Anthropic-call timeout, seconds. Kept well under the wall clock so
    #: a single hung call can't blow the whole budget.
    request_timeout_s: float = 120.0
    #: Adaptive thinking in the loop (disabled only on the forced emit call,
    #: where a forced tool_choice is incompatible with it).
    thinking: bool = True
    #: Cap on the topic text. Longer input is head-truncated and a gap
    #: recorded — never silently blown past.
    max_topic_chars: int = 2000
    #: Path to the research doctrine injected into the system prompt.
    doctrine_path: str = _DEFAULT_DOCTRINE_PATH
    #: Pricing, $ / 1M tokens — used only to stamp an estimated cost on the
    #: trace. Override when running a non-default model.
    input_per_mtok: float = 3.0
    output_per_mtok: float = 15.0
    #: JSONL sink for the trace. None → resolved by the caller to a default
    #: under the data dir (see research_runs wiring).
    trace_log_path: str | None = None
    #: Directory for per-run speedscope timing files. Defaults under the data
    #: dir (shared with ask/ingest); empty string disables file writing.
    trace_dir: str | None = None

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        def _f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        def _i(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        return cls(
            model=(
                os.environ.get("MYCELIUM_RESEARCH_MODEL")
                or os.environ.get("MYCELIUM_INGEST_MODEL")
                or DEFAULT_MODEL
            ),
            op_cap=_i("MYCELIUM_RESEARCH_OP_CAP", 150),
            wall_clock_s=_f("MYCELIUM_RESEARCH_WALL_CLOCK_S", 1200.0),
            max_tokens=_i("MYCELIUM_RESEARCH_MAX_TOKENS", 8000),
            max_retries=_i("MYCELIUM_RESEARCH_MAX_RETRIES", 4),
            request_timeout_s=_f("MYCELIUM_RESEARCH_REQUEST_TIMEOUT_S", 120.0),
            thinking=(
                os.environ.get("MYCELIUM_RESEARCH_THINKING", "on").lower() != "off"
            ),
            max_topic_chars=_i("MYCELIUM_RESEARCH_MAX_TOPIC_CHARS", 2000),
            doctrine_path=(
                os.environ.get("MYCELIUM_RESEARCH_DOCTRINE_PATH")
                or _DEFAULT_DOCTRINE_PATH
            ),
            input_per_mtok=_f("MYCELIUM_RESEARCH_INPUT_PER_MTOK", 3.0),
            output_per_mtok=_f("MYCELIUM_RESEARCH_OUTPUT_PER_MTOK", 15.0),
            trace_log_path=os.environ.get("MYCELIUM_RESEARCH_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_RESEARCH_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
