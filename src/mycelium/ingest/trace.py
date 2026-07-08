"""The ingest trace: one complete, machine-readable JSON record per run.

Adapted from `ask/trace.py` (kept untouched). The same discipline applies —
record every tool call, op count, model/latency/token/cost — but the ledger
here is the *per-candidate reconcile ledger* plus the proposed ops, flagged
contradictions, and skipped duplicates, because the thing being scored is
"did each extracted fact get reconciled and classified before any op was
queued", not "was a question answered".

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
    model: str
    op_cap: int
    wall_clock_s: float
    #: length of the input text actually processed (after any truncation).
    input_chars: int = 0
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
    #: the per-candidate reconcile ledger (list of dicts from CandidateLedger).
    candidate_ledger: list[dict] = field(default_factory=list)
    #: the ops queued into the draft (list of dicts from ProposedOp).
    proposed_ops: list[dict] = field(default_factory=list)
    #: contradictions + hard-validation failures, with reasons.
    flagged: list[str] = field(default_factory=list)
    #: candidates skipped as duplicates ("candidate :: existing_id").
    skipped_duplicates: list[str] = field(default_factory=list)
    #: candidates left unprocessed when a budget cap fired mid-reconcile.
    gaps: list[str] = field(default_factory=list)
    forced_finalize: str | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    #: Per-phase timing (vocab / model turns / tool calls), exported as a
    #: speedscope flamegraph. Off the `build()` record — it's an out-of-band
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
        return {
            "model": self.model,
            "outcome": outcome,
            "input_chars": self.input_chars,
            "op_count": self.op_count,
            "op_cap": self.op_cap,
            "wall_clock_s_limit": self.wall_clock_s,
            "latency_ms": round(latency_ms, 2),
            "model_turns": self.model_turns,
            "tool_calls": [tc.as_dict() for tc in self.tool_calls],
            "candidate_ledger": self.candidate_ledger,
            "proposed_ops": self.proposed_ops,
            "flagged": self.flagged,
            "skipped_duplicates": self.skipped_duplicates,
            "gaps": self.gaps,
            "floor": floor,
            "tokens": tokens,
            "cost_usd": self.cost_usd(input_per_mtok, output_per_mtok),
            "forced_finalize": self.forced_finalize,
            "degraded": self.degraded,
            "notes": self.notes,
        }
