"""The eval-harness trace: one complete, machine-readable JSON record per run.

This is the input to scoring Mycelium vs. the markdown baseline, so it must be
complete — question, full outcome, every tool call + args + result size, op
count, model, latency, token/cost, and the sub-question ledger.

The loop assembles a `TraceBuilder` as it runs and emits a dict; the framework
layer (server wiring) appends it as one JSONL line. Keeping file IO out of the
loop keeps the core testable with plain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import agentloop
from ..agentloop import ToolCallRecord, write_record  # noqa: F401 — re-exported
from ..tracing import SpanRecorder


@dataclass
class TraceBuilder:
    question: str
    model: str
    op_cap: int
    wall_clock_s: float
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    op_count: int = 0
    model_turns: int = 0
    tokens: dict[str, int] = field(
        default_factory=lambda: {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
        }
    )
    sub_question_ledger: list[dict] = field(default_factory=list)
    adjacency_note: str | None = None
    forced_finalize: str | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    #: Per-phase timing (recon / model turns / tool calls), exported as a
    #: speedscope flamegraph file. Kept off `build()` — it's an out-of-band
    #: timing artifact, not part of the eval-harness trace contract.
    spans: SpanRecorder = field(default_factory=SpanRecorder)

    def span(self, name: str) -> Any:
        return agentloop.span(self.spans, name)

    def record_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        *,
        ok: bool,
        counts_as_op: bool,
        error: str | None = None,
    ) -> None:
        agentloop.record_tool_call(
            self, name, arguments, result, ok=ok, counts_as_op=counts_as_op, error=error
        )

    def add_usage(self, usage: Any) -> None:
        agentloop.add_usage(self, usage)

    def cost_usd(self, input_per_mtok: float, output_per_mtok: float) -> float:
        return agentloop.cost_usd(self.tokens, input_per_mtok, output_per_mtok)

    def build(
        self,
        *,
        outcome: str,
        latency_ms: float,
        floor: dict,
        input_per_mtok: float,
        output_per_mtok: float,
    ) -> dict:
        tokens = dict(self.tokens)
        tokens["total"] = tokens["input"] + tokens["output"]
        per_span = self.spans.per_span_ms()
        # Where the wall-clock went, persisted (not just in the flamegraph): the
        # collapsed per-phase totals, plus each model turn's own latency so an
        # outlier call is visible. Inference latency dominates this loop, so this
        # is the signal that matters most.
        phase_ms = {name: round(sum(spans), 1) for name, spans in per_span.items()}
        model_turn_ms = [round(d, 1) for d in per_span.get("model_turn", [])]
        return {
            "question": self.question,
            "model": self.model,
            "outcome": outcome,
            "op_count": self.op_count,
            "op_cap": self.op_cap,
            "wall_clock_s_limit": self.wall_clock_s,
            "latency_ms": round(latency_ms, 2),
            "model_turns": self.model_turns,
            "phase_ms": phase_ms,
            "model_turn_ms": model_turn_ms,
            "tool_calls": [tc.as_dict() for tc in self.tool_calls],
            "sub_question_ledger": self.sub_question_ledger,
            "adjacency_note": self.adjacency_note,
            "floor": floor,
            "tokens": tokens,
            "cost_usd": self.cost_usd(input_per_mtok, output_per_mtok),
            "forced_finalize": self.forced_finalize,
            "degraded": self.degraded,
            "notes": self.notes,
        }
