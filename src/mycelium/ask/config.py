"""Tunables for the `ask` reasoning loop.

Config follows the repo convention (embed.py / http.py): module-level defaults
read from `MYCELIUM_ASK_*` env vars with inline fallbacks. No central settings
module.

The model default is **Haiku** (`claude-haiku-4-5`). The spec originally
mandated one model (Sonnet), but the ask loop's latency is dominated by
per-call model inference across its sequential retrieval turns, and Haiku's
much lower per-call latency is the only lever that brings a multi-hop answer
under ~40s. The id is config, never hardcoded in logic; set
`MYCELIUM_ASK_MODEL=claude-sonnet-4-6` to go back to Sonnet (and the matching
`MYCELIUM_ASK_INPUT_PER_MTOK` / `_OUTPUT_PER_MTOK` for an accurate cost stamp).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .. import tracing

#: Current Haiku model id (confirmed against Anthropic's model catalog:
#: claude-haiku-4-5, 200K context, $1/$5 per MTok).
DEFAULT_MODEL = "claude-haiku-4-5"


@dataclass(frozen=True)
class AskConfig:
    model: str = DEFAULT_MODEL
    #: Hard ceiling on substrate operations per call. Recon counts toward it.
    op_cap: int = 25
    #: Whole-call wall-clock budget, seconds. On exhaustion we degrade to a
    #: low-confidence partial answer rather than throwing. Kept under the
    #: connection window in front of us: the /mcp transport has no keepalive, so
    #: an Ask that runs past the Cloudflare/ALB idle timeout is dropped mid-flight
    #: and the client sees a generic error. 45s returns a fast partial instead.
    #: Raise with MYCELIUM_ASK_WALL_CLOCK_S once /mcp gets its own keepalive.
    wall_clock_s: float = 45.0
    #: `k` for the step-0 recon survey_statements call.
    recon_k: int = 8
    #: max_tokens per model turn. Comfortably above a structured answer.
    max_tokens: int = 8000
    #: Anthropic SDK auto-retries 429/5xx/connection with exponential backoff;
    #: this raises its default 2 for the slow-substrate environment.
    max_retries: int = 4
    #: Per-Anthropic-call timeout, seconds. Kept under the wall clock so a
    #: single hung call can't blow the whole budget.
    request_timeout_s: float = 40.0
    #: Adaptive thinking in the retrieval loop. Default OFF: with thinking on,
    #: each retrieval turn spent ~2x as long thinking and the run still blew the
    #: wall-clock budget; off, the same question finishes cleanly and faster.
    #: (Also a no-op-to-error guard on Haiku, which doesn't take adaptive
    #: thinking.) Re-enable with MYCELIUM_ASK_THINKING=on on a model that
    #: supports it.
    thinking: bool = False
    #: Prompt caching. The loop re-sends a growing conversation every turn; with
    #: caching on, the static prefix (tools + system) and the conversation so far
    #: are read from cache on turns 2..N instead of re-ingested — a large latency
    #: and cost win on a multi-turn run. Disabled by an off-switch for A/B.
    cache: bool = True
    #: Haiku pricing, $ / 1M tokens — used only to stamp an estimated cost on
    #: the trace. Override via MYCELIUM_ASK_INPUT_PER_MTOK / _OUTPUT_PER_MTOK
    #: when running a non-default model (Sonnet is 3.0 / 15.0).
    input_per_mtok: float = 1.0
    output_per_mtok: float = 5.0
    #: JSONL sink for the eval-harness trace. None → resolved by the caller to
    #: a default under the data dir (see server wiring).
    trace_log_path: str | None = None
    #: Directory for per-ask speedscope timing files (one per run). Defaults
    #: under the data dir so on Fargate it lands on the writable volume and the
    #: `/api/traces` endpoint can serve it. Empty string disables file writing.
    trace_dir: str | None = None

    @classmethod
    def from_env(cls) -> "AskConfig":
        def _f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        def _i(name: str, default: int) -> int:
            v = os.environ.get(name)
            return int(v) if v else default

        return cls(
            model=os.environ.get("MYCELIUM_ASK_MODEL") or DEFAULT_MODEL,
            op_cap=_i("MYCELIUM_ASK_OP_CAP", 25),
            wall_clock_s=_f("MYCELIUM_ASK_WALL_CLOCK_S", 90.0),
            recon_k=_i("MYCELIUM_ASK_RECON_K", 8),
            max_tokens=_i("MYCELIUM_ASK_MAX_TOKENS", 8000),
            max_retries=_i("MYCELIUM_ASK_MAX_RETRIES", 4),
            request_timeout_s=_f("MYCELIUM_ASK_REQUEST_TIMEOUT_S", 75.0),
            thinking=(os.environ.get("MYCELIUM_ASK_THINKING", "off").lower() == "on"),
            cache=(os.environ.get("MYCELIUM_ASK_CACHE", "on").lower() != "off"),
            input_per_mtok=_f("MYCELIUM_ASK_INPUT_PER_MTOK", 1.0),
            output_per_mtok=_f("MYCELIUM_ASK_OUTPUT_PER_MTOK", 5.0),
            trace_log_path=os.environ.get("MYCELIUM_ASK_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_ASK_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )
