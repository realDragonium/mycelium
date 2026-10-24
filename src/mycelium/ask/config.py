"""Tunables for the `ask` reasoning loop.

The model is the one saved for the `ask` action in AI settings, picked from
the admin's model catalog; there is no built-in default. The loop's latency is
dominated by per-call model inference across its sequential retrieval turns,
so a small, fast model keeps a multi-hop answer under ~40s. A model missing
from the list-price table gets no cost estimate. Task budgets come from saved
AI settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from .. import model_settings, product_settings, tracing
from ..ai import Provider, ReasoningEffort, pricing

#: The `quick` depth profile (see `for_depth`). A time-boxed caller — e.g.
#: Intercom, which drops an MCP call at ~30s — cannot afford the floor's forced
#: retrieve -> re-search -> re-search dance. `quick` drops the floor and tightens
#: the caps so the loop collapses to recon -> a targeted read or two -> answer,
#: returning a real (not degraded) answer inside the window. These are *ceilings*
#: applied via min(), so a lower saved limit still wins.
QUICK_OP_CAP = 8
QUICK_WALL_CLOCK_S = 25.0
QUICK_REQUEST_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class AskConfig:
    model: str = ""
    provider: Provider = "claude"
    reasoning_effort: ReasoningEffort | None = None
    limits: product_settings.AskSettings = field(
        default_factory=product_settings.AskSettings
    )
    #: The anti-premature-closure floor (loop.py: recon + a targeted retrieval +
    #: a concept-seeded adjacency re-search before an answer is accepted). ON by
    #: default — it's what buys thoroughness. The `quick` depth turns it OFF so a
    #: latency-boxed caller gets a fast, direct answer. See `for_depth`.
    enforce_floor: bool = True
    #: JSONL sink for the eval-harness trace. None → resolved by the caller to
    #: a default under the data dir (see server wiring).
    trace_log_path: str | None = None
    #: Directory for per-ask speedscope timing files (one per run). Defaults
    #: under the data dir so on Fargate it lands on the writable volume and the
    #: `/api/traces` endpoint can serve it. Empty string disables file writing.
    trace_dir: str | None = None

    @property
    def price(self) -> pricing.Price | None:
        return pricing.price(self.provider, self.model)

    @classmethod
    def from_env(cls) -> AskConfig:
        limits = product_settings.get(product_settings.AskSettings)
        selected = model_settings.get("ask")

        return cls(
            model=selected.model,
            provider=selected.provider,
            reasoning_effort=selected.reasoning_effort,
            limits=limits,
            trace_log_path=os.environ.get("MYCELIUM_ASK_TRACE_LOG"),
            trace_dir=(
                os.environ.get("MYCELIUM_ASK_TRACE_DIR")
                or str(tracing.default_trace_dir())
            ),
        )


def for_depth(config: AskConfig, depth: str) -> AskConfig:
    """Return `config` adjusted for the requested `depth`. Pure.

    `quick` drops the floor and lowers the op-cap / wall-clock / per-call timeout
    to *ceilings* (via min, so an already-lower saved limit still wins), so the
    loop is structurally shorter and finishes well inside a tight client window.
    Anything other than `quick` (incl. `standard`) returns `config` unchanged.
    """
    if depth != "quick":
        return config
    return replace(
        config,
        enforce_floor=False,
        limits=config.limits.model_copy(
            update={
                "op_cap": min(config.limits.op_cap, QUICK_OP_CAP),
                "wall_clock_s": min(config.limits.wall_clock_s, QUICK_WALL_CLOCK_S),
                "request_timeout_s": min(
                    config.limits.request_timeout_s, QUICK_REQUEST_TIMEOUT_S
                ),
            }
        ),
    )
