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

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..tracing import SpanRecorder


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result_size: int
    ok: bool
    counts_as_op: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result_size": self.result_size,
            "ok": self.ok,
            "counts_as_op": self.counts_as_op,
            "error": self.error,
        }


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

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        with self.spans.span(name):
            yield

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
        if counts_as_op:
            self.op_count += 1
        self.tool_calls.append(
            ToolCallRecord(
                name=name,
                arguments=dict(arguments),
                result_size=_result_size(result),
                ok=ok,
                counts_as_op=counts_as_op,
                error=error,
            )
        )

    def add_usage(self, usage: Any) -> None:
        if usage is None:
            return
        self.tokens["input"] += int(getattr(usage, "input_tokens", 0) or 0)
        self.tokens["output"] += int(getattr(usage, "output_tokens", 0) or 0)
        self.tokens["cache_read"] += int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )
        self.tokens["cache_creation"] += int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )

    def cost_usd(self, input_per_mtok: float, output_per_mtok: float) -> float:
        return round(
            self.tokens["input"] / 1_000_000 * input_per_mtok
            + self.tokens["output"] / 1_000_000 * output_per_mtok,
            6,
        )

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


def _result_size(result: Any) -> int:
    """Cheap, robust size signal for a tool result (count of items, else chars)."""
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("statements", "entities", "results"):
            v = result.get(key)
            if isinstance(v, list):
                return len(v)
        return len(result)
    try:
        return len(str(result))
    except Exception:  # noqa: BLE001
        return 0


def write_record(path: str | Path, record: dict) -> None:
    """Append one trace record as a single JSONL line. Best-effort: a logging
    failure must never mask the result."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass
