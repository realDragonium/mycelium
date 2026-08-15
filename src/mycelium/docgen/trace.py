"""The docgen trace: one complete, machine-readable JSON record per run.

Same discipline as its siblings — every tool call with its args and result
size, op count, model, latency, tokens, cost — but what is being scored here
is *whether the document was grounded*, so the record carries `grounding`
(what the run retrieved against what the document cited) and the resolution
it made, rather than a reconcile ledger.

The loop assembles a `TraceBuilder` as it runs and emits a dict; the framework
layer appends it as one JSONL line. Keeping file IO out of the loop keeps the
core testable with plain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import agentloop
from ..agentloop import ToolCallRecord, write_record  # noqa: F401 — re-exported
from ..tracing import SpanRecorder


@dataclass
class TraceBuilder:
    model: str
    op_cap: int
    wall_clock_s: float
    #: the request the run was asked to document.
    prompt: str = ""
    #: what the request named, before the run resolved anything.
    requested_set: str | None = None
    requested_type: str | None = None
    #: what the run wrote against, and why it chose that.
    guideline_set: str | None = None
    document_type: str | None = None
    resolution_reason: str | None = None
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
    #: knowledge gaps filed during the run, each "gap_id :: text".
    reported_gaps: list[str] = field(default_factory=list)
    #: the gaps the emitted document declared for itself.
    declared_gaps: list[str] = field(default_factory=list)
    #: emits the harness sent back, each with why (no ids, unretrieved ids,
    #: blank body). The anti-invention gate's own record.
    refused_emits: list[str] = field(default_factory=list)
    #: One entry per independent review. The reviewer gate's own record.
    reviews: list[dict] = field(default_factory=list)
    forced_finalize: str | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    #: Per-phase timing (recon / model turns / tool calls), exported as a
    #: speedscope flamegraph. Off the `build()` record — an out-of-band timing
    #: artifact, not part of the trace contract.
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
        grounding: dict,
        input_per_mtok: float,
        output_per_mtok: float,
    ) -> dict:
        tokens = dict(self.tokens)
        tokens["total"] = tokens["input"] + tokens["output"]
        per_span = self.spans.per_span_ms()
        phase_ms = {name: round(sum(spans), 1) for name, spans in per_span.items()}
        return {
            "prompt": self.prompt,
            "model": self.model,
            "outcome": outcome,
            "requested_set": self.requested_set,
            "requested_type": self.requested_type,
            "guideline_set": self.guideline_set,
            "document_type": self.document_type,
            "resolution_reason": self.resolution_reason,
            "op_count": self.op_count,
            "op_cap": self.op_cap,
            "wall_clock_s_limit": self.wall_clock_s,
            "latency_ms": round(latency_ms, 2),
            "model_turns": self.model_turns,
            "phase_ms": phase_ms,
            "tool_calls": [tc.as_dict() for tc in self.tool_calls],
            "grounding": grounding,
            "reported_gaps": self.reported_gaps,
            "declared_gaps": self.declared_gaps,
            "refused_emits": self.refused_emits,
            "reviews": self.reviews,
            "tokens": tokens,
            "cost_usd": self.cost_usd(input_per_mtok, output_per_mtok),
            "forced_finalize": self.forced_finalize,
            "degraded": self.degraded,
            "notes": self.notes,
        }
