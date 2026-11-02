"""The `ingest` write-harness loop.

One Sonnet context drives extract -> reconcile -> classify -> link -> emit over
the substrate READ primitives; this module is the deterministic harness around
it — vocab fetch, the tool-use loop, the anti-premature-closure floor, the
op-cap / wall-clock ceilings, draft assembly + validation, and graceful
degradation. The model reasons; this code fetches, counts, bounds, validates,
and records.

Core-at-the-center: `_execute` depends only on a client-like object (anything
with `.messages.create(...)`), a `SubstrateReader` (reused from `ask`), and a
`DraftEmitter`. All three are injectable, so the loop is exercisable with plain
fakes — no server, no DB, no network. The framework seam (`run_ingest`) wires
the shared model transport + in-process substrate + in-process draft emitter and
writes the trace.

THE NO-LIVE-WRITE GUARANTEE: the model is handed READ tools plus one terminal
`emit_draft` tool and never sees a write tool. The only write path in the whole
package is `drafts_store.create_draft`/`add_op`, reached exclusively through the
injected `DraftEmitter` in `_assemble_draft`. This module imports no substrate
write tool and never touches `server._db()`.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import ai, ai_prompts, link_rules, tracing, when_expression
from ..agentloop import (
    append_tool_error as _append_tool_error,
)
from ..agentloop import check_budget
from ..agentloop import (
    first_tool_use as _first_tool_use,
)
from ..agentloop import (
    serialize as _serialize,
)
from ..agentloop import (
    substrate_has as _substrate_has,
)

# Reuse ask's read seam wholesale — do NOT duplicate it.
from ..ask.substrate import InProcessSubstrate, SubstrateError, SubstrateReader
from . import directions, prompts
from .config import DOCTRINE_NAME, IngestConfig
from .draft import DraftEmitter, InProcessDraftEmitter
from .schema import (
    CandidateLedger,
    DraftCreated,
    IngestResult,
    NothingToIngest,
    OpKind,
    ProposedOp,
)
from .tools import EMIT_TOOL, build_tools, parse_emit_input
from .trace import TraceBuilder

#: Reconcile reads — at least one must have happened before emit is accepted.
#: Each takes the candidate's text; `find_duplicates` audits the whole corpus
#: instead, so calling it checks nothing about the candidates.
_RECONCILE_TOOLS = frozenset({"discover_facts", "search_statements"})
#: Adjacency searches — at least one must have happened before emit is accepted.
_ADJACENCY_TOOLS = frozenset({"search_statements", "grep_statements"})

#: The deterministic vocab fetch (each counts toward the op cap).
_VOCAB_CALLS = (
    ("statement_kinds", "list_statement_kinds"),
    ("link_types", "list_link_types"),
    ("entity_link_types", "list_entity_link_types"),
)

#: The valid OpKind set, for fast membership checks.
_OP_KINDS: frozenset[str] = frozenset(OpKind.__args__)  # type: ignore[attr-defined]

#: Per-op required keys for the kinds with mandatory args. Missing one is a hard
#: validation failure (the op is flagged, not queued) — never a throw.
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "upsert_statement": ("kind", "text"),
    "upsert_statements": ("statements",),
    "upsert_entity": ("name", "description"),
    "add_links": ("links",),
    "add_entity_links": ("links",),
    "patch_statement": ("id",),
    "replace_text": ("id", "text"),
    "merge_statements": ("from_id", "into_id"),
}

#: Safety stops so a stubborn model can't spin forever without consuming ops.
_MAX_FLOOR_BLOCKS = 3
_MAX_MALFORMED_RETRIES = 1
#: Hard ceiling on model turns, well above any real run (op cap bounds reads).
_TURN_HEADROOM = 16
#: Share of the wall clock held back for the final emit. Reading turns stop
#: where the rest ends; an emit still running at the wall clock keeps the ops
#: it had finished.
_FINAL_TURN_SHARE = 1 / 3


def run_ingest(
    text: str,
    *,
    client: Any | None = None,
    substrate: SubstrateReader | None = None,
    emitter: DraftEmitter | None = None,
    config: IngestConfig | None = None,
) -> IngestResult:
    """Turn `text` into a reviewable DRAFT. Returns `DraftCreated` or
    `NothingToIngest` — never raises for extraction/closure reasons, and never
    writes live.

    `client` / `substrate` / `emitter` / `config` are injectable for tests; in
    production they default to the shared model transport, the in-process
    substrate, the in-process draft emitter, and effective saved configuration.
    """
    config = config or IngestConfig.from_env()
    task, instructions = ingest_task(text, config)
    return run(
        task,
        instructions,
        client=client,
        substrate=substrate,
        emitter=emitter,
        config=config,
        label="ingest",
    )


def ingest_task(text: str, config: IngestConfig) -> tuple[Task, ai_prompts.Snapshot]:
    """The loop's task for ingesting `text`, and the instructions it runs under."""
    instructions = ai_prompts.resolve(DOCTRINE_NAME, default_path=config.doctrine_path)
    guarded, input_note = _guard_input(text, config)
    task = Task(
        text=guarded,
        system_prompt=prompts.build_system_prompt(instructions.text),
        first_message=lambda vocab: prompts.initial_user_message(guarded, vocab),
        title=_draft_title(guarded),
        notes=tuple(n for n in (instructions.note, input_note) if n),
    )
    return task, instructions


def run(
    task: Task,
    instructions: ai_prompts.Snapshot,
    *,
    client: Any | None,
    substrate: SubstrateReader | None,
    emitter: DraftEmitter | None,
    config: IngestConfig,
    label: str,
    run_id: str | None = None,
) -> IngestResult:
    """Run the loop for `task`, recording which `instructions` it ran under."""
    if substrate is None:
        substrate = InProcessSubstrate()
    if emitter is None:
        emitter = InProcessDraftEmitter()

    with (
        tracing.profile_to_html(label, f"{len(task.text)} chars"),
        ai.usage.attributed(label, run_id=run_id),
    ):
        result = _execute(task, client, substrate, emitter, config)

    if run_id is not None:
        result.trace["run_id"] = run_id
    result.trace["prompts"] = [instructions.reference().model_dump(mode="json")]

    if config.trace_log_path:
        from .trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


@dataclass(frozen=True)
class Task:
    """What one run of the loop is asked to do: ingest free text, or connect
    existing statements (see `connect.py`)."""

    #: The text the run works from; alias evidence without a statement quotes it.
    text: str
    system_prompt: str
    #: The opening message, given the live vocabulary.
    first_message: Callable[[dict[str, Any]], str]
    title: str
    notes: tuple[str, ...] = ()
    #: Narrows one op to what this task may propose: the op, possibly with
    #: fewer edges, or None to drop it, plus a line per thing dropped. It is
    #: given the existing statements the draft's edges touch and the ledger.
    screen: (
        Callable[
            [dict, Mapping[str, directions.Statement], Sequence[dict]],
            tuple[dict | None, list[str]],
        ]
        | None
    ) = None
    #: Which statement edges to drop by their kinds, given (link type, source
    #: kind, target kind). Ingest drops only edges applying would reject.
    edge_check: directions.EdgeCheck = link_rules.flip_error
    #: Statements alias evidence may quote instead of `text`, by id.
    quotable: Mapping[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


@dataclass
class _RunContext:
    """Per-run harness state, so the finalizers/handlers below don't each need
    ten-plus positional parameters."""

    task: Task
    client: Any
    substrate: SubstrateReader
    config: IngestConfig
    tools: list[dict]
    messages: list[dict[str, Any]]
    emitter: DraftEmitter
    trace: TraceBuilder
    start: float
    reads_after_vocab: list[str]
    #: Monotonic times reading turns, and the whole run, must end by.
    reading_until: float
    deadline: float
    nudged: bool = False
    floor_blocks: int = 0
    malformed_retries: int = 0
    #: Held back from the token cap so the turns that end the run fit
    #: under it: see `_reserve`.
    largest_turn_tokens: int = 0
    largest_output_tokens: int = 0
    history_tokens: int = 0
    #: An outside agent's emit_draft input, standing in for the model's turns
    #: (see `external`): a forced finalize keeps it instead of forcing a turn.
    submitted: dict[str, Any] | None = None


def _open(
    task: Task,
    client: Any,
    substrate: SubstrateReader,
    emitter: DraftEmitter,
    config: IngestConfig,
) -> _RunContext:
    """Start a run: fetch the vocabulary and build the opening message."""
    start = time.monotonic()

    trace = TraceBuilder(
        model=config.model,
        provider=config.provider,
        op_cap=config.limits.op_cap,
        wall_clock_s=config.limits.wall_clock_s,
        input_chars=len(task.text),
    )
    trace.notes.extend(task.notes)

    tools = build_tools(substrate.tool_specs())

    # ---- Vocab fetch (deterministic; each counts toward the op cap) ----
    vocab = _fetch_vocab(substrate, trace)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": task.first_message(vocab)}
    ]

    reads_after_vocab: list[str] = []  # successful read names, for the floor

    return _RunContext(
        task=task,
        client=client,
        substrate=substrate,
        config=config,
        tools=tools,
        messages=messages,
        emitter=emitter,
        trace=trace,
        start=start,
        reads_after_vocab=reads_after_vocab,
        reading_until=start + config.limits.wall_clock_s * (1 - _FINAL_TURN_SHARE),
        deadline=start + config.limits.wall_clock_s,
        nudged=False,
        floor_blocks=0,
        malformed_retries=0,
    )


def _execute(
    task: Task,
    client: Any,
    substrate: SubstrateReader,
    emitter: DraftEmitter,
    config: IngestConfig,
) -> IngestResult:
    ctx = _open(task, client, substrate, emitter, config)
    trace, messages, tools = ctx.trace, ctx.messages, ctx.tools
    start, reads_after_vocab = ctx.start, ctx.reads_after_vocab
    max_turns = config.limits.op_cap + _TURN_HEADROOM

    while True:
        # ---- Budget gates first — forced finalize bypasses the floor ----
        reason = (
            check_budget(trace, config.limits, start, max_turns)
            or ("wall_clock" if time.monotonic() >= ctx.reading_until else None)
            or _tokens_reached(trace, config, _reserve(ctx))
        )
        if reason:
            return _forced_finalize(reason, ctx)
        tokens_before = dict(trace.tokens)

        try:
            with trace.span("model_turn"):
                resp = _model_turn(
                    client,
                    config,
                    task.system_prompt,
                    messages,
                    tools,
                    force=False,
                    until=ctx.reading_until,
                )
        except Exception as exc:  # noqa: BLE001 — terminal API error after SDK backoff
            stopped = time.monotonic() >= ctx.reading_until
            if isinstance(exc, ai.IncompleteTurn):
                trace.add_usage(exc.usage)
                kept = _cut_emit(exc, "wall_clock" if stopped else "max_tokens", ctx)
                if kept is not None:
                    return kept
            trace.notes.append(f"model error: {exc}")
            return _forced_finalize("wall_clock" if stopped else "api_error", ctx)
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        _note_turn(ctx, tokens_before)
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [block for block in resp.content if isinstance(block, ai.ToolUse)]
        if not tool_uses:
            # Text only / end_turn with no terminal tool.
            if not ctx.nudged:
                ctx.nudged = True
                messages.append({"role": "user", "content": prompts.NO_TERMINAL_NUDGE})
                continue
            return _forced_finalize("no_terminal", ctx)

        # The model is calling a tool again — reset the no-terminal nudge so a
        # single stray text turn earlier doesn't doom a later one. The nudge
        # budget is per consecutive-text-streak, not per session.
        ctx.nudged = False

        # ---- Substrate READ primitives: every read of this turn ----
        # Only a SUCCESSFUL read counts toward the floor — a SubstrateError
        # gathered no data. It still counts toward the op cap (recorded).
        for tool_use in tool_uses:
            if tool_use.name != EMIT_TOOL and _dispatch_read(
                tool_use.name,
                dict(tool_use.input),
                tool_use.id,
                substrate,
                trace,
                messages,
            ):
                reads_after_vocab.append(tool_use.name)

        # ---- Terminal: emit_draft (gated by the floor + ledger well-formedness) ----
        emits = [t for t in tool_uses if t.name == EMIT_TOOL]
        if not emits:
            continue
        if len(tool_uses) != 1:
            # An emit beside reads was decided without their results.
            for emit in emits:
                _append_tool_error(
                    messages,
                    emit.id,
                    "Call emit_draft alone, in a turn after you have read the "
                    "results of your reads.",
                )
            continue
        result = _handle_emit(emits[0], ctx)
        if result is not None:
            return result


def _used(trace: TraceBuilder) -> int:
    return sum(trace.tokens.values())


def _note_turn(ctx: _RunContext, tokens_before: Mapping[str, int]) -> None:
    turn = {k: v - tokens_before[k] for k, v in ctx.trace.tokens.items()}
    ctx.largest_turn_tokens = max(ctx.largest_turn_tokens, sum(turn.values()))
    ctx.largest_output_tokens = max(ctx.largest_output_tokens, turn["output"])
    ctx.history_tokens = sum(turn.values())


def _reserve(ctx: _RunContext) -> int:
    """What the run may still use after this check: one more reading turn
    like the largest so far, then the forced emit, which reads the whole
    history again."""
    return ctx.largest_turn_tokens + ctx.history_tokens + ctx.largest_output_tokens


def _tokens_reached(
    trace: TraceBuilder, config: IngestConfig, reserve: int
) -> str | None:
    """The token cap, checked before each turn."""
    if not config.max_run_tokens:
        return None
    return "token_cap" if _used(trace) + reserve >= config.max_run_tokens else None


def _handle_emit(tool_use: Any, ctx: _RunContext) -> IngestResult | None:
    """Terminal: emit_draft (gated by the floor + ledger well-formedness).
    Returns a result to finish, or None to keep looping after a re-prompt."""
    trace: TraceBuilder = ctx.trace
    messages: list[dict[str, Any]] = ctx.messages
    tool_input = dict(tool_use.input or {})
    try:
        ops, ledger, flagged, skipped = parse_emit_input(tool_input)
    except ValueError as exc:
        if ctx.malformed_retries < _MAX_MALFORMED_RETRIES:
            ctx.malformed_retries += 1
            _append_tool_error(
                messages, tool_use.id, prompts.malformed_retry_message(str(exc))
            )
            return None
        trace.notes.append(f"emit_draft malformed twice: {exc}")
        return _degrade_no_draft("degraded: emit_draft malformed twice", ctx)

    floor = _floor_state(ctx.reads_after_vocab)
    unmet = _ledger_unmet(ledger)
    coverage = _coverage_unmet(ops, ledger)
    if coverage:
        unmet = [*unmet, coverage]
    if not floor["satisfied"] or unmet:
        if ctx.floor_blocks < _MAX_FLOOR_BLOCKS:
            ctx.floor_blocks += 1
            _append_tool_error(
                messages,
                tool_use.id,
                prompts.floor_block_message(_floor_detail(floor, unmet)),
            )
            return None
        # Stuck below the floor: respond to the pending tool_use, then degrade
        # via a forced finalize rather than accepting a floorless emit.
        _append_tool_error(
            messages,
            tool_use.id,
            "Floor still unmet after repeated attempts; finalizing with "
            "what has been reconciled.",
        )
        return _forced_finalize("floor_stuck", ctx)
    return _assemble_draft(ops, ledger, flagged, skipped, ctx, degraded=False)


def _existing_statements(
    ids: list[str], ctx: _RunContext
) -> dict[str, directions.Statement]:
    """Kind and text of the existing statements a draft links to; whatever
    cannot be read is left out, so fewer edges get checked."""
    if not ids or not _substrate_has(ctx.substrate, "get_statements"):
        return {}
    arguments = {"ids": ids}
    try:
        result = ctx.substrate.call("get_statements", arguments)
    except SubstrateError as exc:
        ctx.trace.record_tool_call(
            "get_statements",
            arguments,
            None,
            ok=False,
            counts_as_op=False,
            error=str(exc),
        )
        return {}
    ctx.trace.record_tool_call(
        "get_statements", arguments, result, ok=True, counts_as_op=False
    )
    rows = result.get("statements") if isinstance(result, dict) else None
    return {
        row["id"]: directions.Statement(kind=row["kind"], text=row["text"])
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and all(isinstance(row.get(k), str) for k in ("id", "kind", "text"))
    }


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _guard_input(text: str, config: IngestConfig) -> tuple[str, str | None]:
    text = text or ""
    if len(text) <= config.limits.max_input_chars:
        return text, None
    head = text[: config.limits.max_input_chars]
    note = (
        f"input truncated: {len(text)} chars exceeded max_input_chars="
        f"{config.limits.max_input_chars}; only the head was processed (tail is a gap)"
    )
    return head, note


def _fetch_vocab(substrate: SubstrateReader, trace: TraceBuilder) -> dict[str, Any]:
    """Fetch the live vocabulary deterministically; each call counts as an op.
    Failures are recorded but never fatal — the model can still reconcile."""
    vocab: dict[str, Any] = {}
    for key, name in _VOCAB_CALLS:
        if not _substrate_has(substrate, name):
            vocab[key] = []
            trace.record_tool_call(
                name, {}, None, ok=False, counts_as_op=True, error="unknown tool"
            )
            trace.notes.append(f"vocab fetch skipped: {name} not available")
            continue
        try:
            with trace.span(f"vocab:{name}"):
                result = substrate.call(name, {})
            trace.record_tool_call(name, {}, result, ok=True, counts_as_op=True)
            vocab[key] = result
        except SubstrateError as exc:
            vocab[key] = []
            trace.record_tool_call(
                name, {}, None, ok=False, counts_as_op=True, error=str(exc)
            )
            trace.notes.append(f"vocab fetch failed: {name}: {exc}")
    return vocab


def _dispatch_read(
    name: str,
    arguments: dict[str, Any],
    tool_use_id: str,
    substrate: SubstrateReader,
    trace: TraceBuilder,
    messages: list[dict[str, Any]],
) -> bool:
    """Execute one read; return True only if it succeeded (so the caller knows
    whether it counts toward the floor)."""
    if not _substrate_has(substrate, name):
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error="unknown tool"
        )
        _append_tool_error(messages, tool_use_id, f"unknown tool: {name}")
        return False
    try:
        with trace.span(f"tool:{name}"):
            result = substrate.call(name, arguments)
        trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
        _append_tool_result(messages, tool_use_id, result, is_error=False)
        return True
    except SubstrateError as exc:
        # Absence/failure is reported, never fabricated into an empty success.
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error=str(exc)
        )
        _append_tool_result(messages, tool_use_id, {"error": str(exc)}, is_error=True)
        return False


def _forced_finalize(reason: str, ctx: _RunContext) -> IngestResult:
    """Last resort: force one emit_draft turn (floor bypassed) in the time
    left, else give up gracefully with NothingToIngest. Never throws, never partial
    live-write."""
    trace: TraceBuilder = ctx.trace
    trace.forced_finalize = reason
    trace.degraded = True
    if ctx.submitted is not None:
        ops, ledger, flagged, skipped = parse_emit_input(ctx.submitted)
        return _assemble_draft(ops, ledger, flagged, skipped, ctx, degraded=True)
    ctx.messages.append(
        {"role": "user", "content": prompts.forced_finalize_message(reason)}
    )
    try:
        with trace.span("model_turn:forced"):
            resp = _model_turn(
                ctx.client,
                ctx.config,
                ctx.task.system_prompt,
                ctx.messages,
                ctx.tools,
                force=True,
                until=ctx.deadline,
            )
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        tool_use = _first_tool_use(resp)
        if tool_use is not None and tool_use.name == EMIT_TOOL:
            try:
                ops, ledger, flagged, skipped = parse_emit_input(
                    dict(tool_use.input or {})
                )
            except ValueError as exc:
                trace.notes.append(f"forced finalize: emit_draft malformed: {exc}")
            else:
                return _assemble_draft(
                    ops, ledger, flagged, skipped, ctx, degraded=True
                )
        else:
            trace.notes.append("forced finalize: model did not emit emit_draft")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ai.IncompleteTurn):
            trace.add_usage(exc.usage)
            stopped = time.monotonic() >= ctx.deadline
            kept = _cut_emit(exc, "wall_clock" if stopped else "max_tokens", ctx)
            if kept is not None:
                return kept
        trace.notes.append(f"forced finalize failed: {exc}")
    return _degrade_no_draft(f"degraded: could not assemble a draft ({reason})", ctx)


def _cut_emit(
    exc: ai.IncompleteTurn, cause: str, ctx: _RunContext
) -> IngestResult | None:
    """A draft from the ops an emit_draft had finished when its output was cut
    off, or None when the cut turn was not an emit or kept nothing usable."""
    call = exc.truncated
    if call is None or call.name != EMIT_TOOL:
        return None
    try:
        ops, ledger, flagged, skipped = parse_emit_input(dict(call.input))
    except ValueError as error:
        ctx.trace.notes.append(f"emit_draft cut off ({cause}), unusable: {error}")
        return None
    ctx.trace.notes.append(
        f"emit_draft cut off ({cause}); kept the {len(ops)} ops it had finished"
    )
    ctx.trace.forced_finalize = ctx.trace.forced_finalize or cause
    return _assemble_draft(ops, ledger, flagged, skipped, ctx, degraded=True)


# --------------------------------------------------------------------------- #
# Draft assembly (the only write path — via the injected emitter)
# --------------------------------------------------------------------------- #


def _assemble_draft(
    ops: list[dict],
    ledger: list[dict],
    flagged: list[str],
    skipped: list[str],
    ctx: _RunContext,
    *,
    degraded: bool,
) -> IngestResult:
    """Validate the model's ops, queue the valid ones into a draft via the
    emitter, and return the structured outcome. Never throws; hard-validation
    failures are moved to `flagged`, not queued, and never become a live write."""
    trace: TraceBuilder = ctx.trace
    emitter: DraftEmitter = ctx.emitter
    if degraded:
        trace.degraded = True

    # The model's own flags (contradictions, scoped-out mechanisms) are a
    # review-worthy signal on their own; validation may append more (rejected
    # ops). Track the model's count so an all-ops-rejected run with no real
    # contradiction degrades instead of emitting a contentless draft.
    model_flags = list(flagged)
    flagged = list(flagged)
    ledger = _mark_unprocessed_gaps(ledger, trace)
    trace.candidate_ledger = [_normalize_ledger_row(r) for r in ledger]
    trace.skipped_duplicates = list(skipped)

    # Nothing to do: no ops, no model flags, and the ledger is empty/all-duplicate.
    if not ops and not model_flags and _ledger_empty_or_all_duplicate(ledger):
        reason = (
            "all candidates were duplicates"
            if any(r.get("classification") == "duplicate" for r in ledger)
            else "nothing extractable"
        )
        trace.flagged = flagged
        return _nothing(reason, ctx)

    existing = _existing_statements(directions.existing_ids(ops), ctx)
    ops, flipped = directions.without_flipped(ops, existing, ctx.task.edge_check)
    flagged.extend(f"edge dropped: {f}" for f in flipped)

    valid_kinds = _safe_valid_kinds(emitter)
    indexed: list[tuple[int, ProposedOp]] = []
    for idx, op in enumerate(ops):
        kept = _screen_and_validate(op, idx, valid_kinds, flagged, ctx, existing)
        if kept is not None:
            indexed.append((idx, kept))
    validated = [p for _, p in indexed]

    trace.proposed_ops = [p.model_dump() for p in validated]
    trace.flagged = flagged

    if not validated:
        if not ops:
            reason = "nothing extractable"
        else:
            reason = "no valid ops survived validation; see flagged trace"
        return _nothing(reason, ctx)

    # ---- The ONLY write path: queue ops via the emitter ----
    # LOW-8 (deferred): a classification<->op cross-check (e.g. detecting a NEW
    # upsert that duplicates an existing statement the model already classified
    # as a duplicate) is NOT implemented here — it needs fragile text heuristics
    # and is a deliberate deferral.
    #
    # The emitter opens a draft together with its first op, so a draft exists
    # only once something landed in it; flags alone travel in the trace. Once a
    # draft exists its id is never discarded: an op that fails to queue moves
    # to `flagged` and the rest still queue.
    #
    # Alias suggestions go to their own draft: each one needs an individual
    # human decision, and a draft holding one can be neither applied nor
    # closed until it is decided, so sharing a draft would hold the knowledge
    # back.
    knowledge = [(i, p) for i, p in indexed if p.op != "alias_suggestion"]
    suggestions = [(i, p) for i, p in indexed if p.op == "alias_suggestion"]
    title = ctx.task.title
    draft_id, queued = _queue_ops(title, knowledge, flagged, ctx)
    alias_draft_id, alias_queued = _queue_ops(
        f"Alias suggestions from {title}"
        if draft_id is None
        else f"Alias suggestions from {draft_id}: {title}",
        suggestions,
        flagged,
        ctx,
    )
    if alias_draft_id is not None:
        try:
            emitter.submit_aliases(alias_draft_id)
        except Exception as exc:  # noqa: BLE001 — never throw; the draft exists
            flagged.append(f"alias suggestions left unsubmitted: {exc}")
    draft_id = draft_id or alias_draft_id
    if draft_id is None:
        return _degrade_no_draft(
            "degraded: could not assemble a draft (no op could be queued)", ctx
        )

    trace.proposed_ops = [p.model_dump() for p in queued + alias_queued]

    trace_dict = _build_trace(trace, "draft_created", ctx)
    return DraftCreated(
        draft_id=draft_id,
        alias_draft_id=alias_draft_id,
        ops=queued + alias_queued,
        flagged=flagged,
        skipped_duplicates=list(skipped),
        trace=trace_dict,
    )


def _screen_and_validate(
    op: dict,
    idx: int,
    valid_kinds: set[str],
    flagged: list[str],
    ctx: _RunContext,
    existing: Mapping[str, directions.Statement],
) -> ProposedOp | None:
    if ctx.task.screen is not None:
        screened, dropped = ctx.task.screen(op, existing, ctx.trace.candidate_ledger)
        flagged.extend(f"op[{idx}] {line}" for line in dropped)
        if screened is None:
            return None
        op = screened
    if op.get("op") == "alias_suggestion":
        from ..alias_suggestions import Proposal

        try:
            proposal = Proposal.model_validate(op.get("payload"))
            source = (
                ctx.task.text
                if proposal.statement_id is None
                else ctx.task.quotable.get(proposal.statement_id)
            )
            if source is None or proposal.quote not in source:
                raise ValueError(
                    "Alias evidence must quote the input text"
                    + (
                        " or a statement being connected."
                        if ctx.task.quotable
                        else "; omit statement_id."
                    )
                )
        except ValueError as exc:
            flagged.append(f"op[{idx}] alias suggestion dropped: {exc}")
            return None
    return _validate_op(op, idx, valid_kinds, flagged, ctx.emitter)


_DRAFT_REFERENCE = re.compile(r"@(\d+):(\d+)")


def _queue_ops(
    title: str,
    ops: list[tuple[int, ProposedOp]],
    flagged: list[str],
    ctx: _RunContext,
) -> tuple[str | None, list[ProposedOp]]:
    """Queue `ops` into a new draft, opened with the first op that lands.
    Returns the draft id (None when nothing landed) and the queued ops."""
    # A `@seq:index` reference counts the model's emitted operations from 1.
    # Alias suggestions and dropped operations are not queued here, so the
    # draft numbers differ; rewrite each reference to the producer's real seq.
    draft_id: str | None = None
    queued: list[ProposedOp] = []
    seqs: dict[int, int] = {}
    for i, p in ops:
        source_text = ctx.task.text if p.op == "alias_suggestion" else None
        payload = p.payload
        if p.op != "alias_suggestion":
            try:
                payload = _renumber_references(
                    p.payload, seqs, own=i + 1 if p.op == "upsert_statements" else None
                )
            except ValueError as exc:
                flagged.append(f"op[{i}] ({p.op}) dropped: {exc}")
                continue
        try:
            if draft_id is None:
                draft_id, seq = ctx.emitter.create(
                    title=title, kind=p.op, payload=payload, source_text=source_text
                )
            else:
                seq = ctx.emitter.add_op(
                    draft_id, p.op, payload, source_text=source_text
                )
        except Exception as exc:  # noqa: BLE001 — never throw; flag and continue
            flagged.append(
                f"op[{i}] ({p.op}) dropped: draft store error queueing it: {exc}"
            )
            continue
        seqs[i + 1] = seq
        queued.append(p.model_copy(update={"payload": payload}))
    return draft_id, queued


def _renumber_references(
    value: Any, seqs: dict[int, int], *, own: int | None = None
) -> Any:
    """`own` is the batch's own operation number: models sometimes name a
    sibling in the same batch with the later-operation form, which means `@N`."""
    if isinstance(value, dict):
        return {k: _renumber_references(v, seqs, own=own) for k, v in value.items()}
    if isinstance(value, list):
        return [_renumber_references(v, seqs, own=own) for v in value]
    if isinstance(value, str) and (match := _DRAFT_REFERENCE.fullmatch(value)):
        producer, index = int(match[1]), match[2]
        if producer == own:
            return f"@{index}"
        if producer not in seqs:
            raise ValueError(
                f"reference {value} names operation {producer}, which is not "
                "queued in this draft"
            )
        return f"@{seqs[producer]}:{index}"
    return value


def _validate_op(
    op: dict, idx: int, valid_kinds: set[str], flagged: list[str], emitter: DraftEmitter
) -> ProposedOp | None:
    """Hard-validate one op. Returns a `ProposedOp` to queue, or None after
    appending a reason to `flagged`. Never throws."""
    kind = op.get("op")
    payload = op.get("payload")
    rationale = str(op.get("rationale") or "")

    if kind not in _OP_KINDS:
        flagged.append(f"op[{idx}] dropped: '{kind}' is not a known draft op kind")
        return None
    if valid_kinds and kind not in valid_kinds:
        flagged.append(
            f"op[{idx}] dropped: '{kind}' is not a registered substrate tool "
            "(curator replay could never run it)"
        )
        return None
    if not isinstance(payload, dict):
        flagged.append(f"op[{idx}] ({kind}) dropped: payload is not an object")
        return None

    # A required key that is PRESENT-but-None is as fatal as a missing one: the
    # emitter drops None-valued keys before queueing, so the real tool would
    # raise "missing a required argument" at replay. Treat both as missing. Runs
    # BEFORE the mentions/links normalization, which is why mentions/links are
    # deliberately NOT in _REQUIRED_KEYS — they still normalize to [] below.
    missing = [k for k in _REQUIRED_KEYS.get(kind, ()) if payload.get(k) is None]
    if missing:
        flagged.append(f"op[{idx}] ({kind}) dropped: missing required key(s) {missing}")
        return None

    # Inner-shape validation + replay-safe normalization. The real tools do NO
    # validation at curator replay (the curator's all-or-nothing replay calls
    # wrapper(**payload) directly), so this is the only guard against a payload
    # that explodes at replay.
    payload, rationale, dropped = _normalize_and_check(
        kind, payload, rationale, flagged, idx
    )
    if dropped:
        return None

    # Unexpected top-level keys the real tool does not accept. The curator
    # replays as wrapper(**payload) with ZERO key filtering, so a plausible-but-
    # wrong key (e.g. patch_statement with 'links', merge_statements with
    # 'reason') would raise "unexpected keyword argument" and abort the whole
    # all-or-nothing draft. allowed_keys() comes through the emitter seam (the
    # real tool's PRE-draft-splice signature, draft_id already excluded). An
    # empty set means "unknown — do not filter", so we never over-drop. Flag-
    # and-skip the WHOLE op rather than silently strip a half-understood payload.
    allowed = _safe_allowed_keys(emitter, kind)
    if allowed:
        extra = set(payload) - allowed
        if extra:
            flagged.append(
                f"op[{idx}] ({kind}) dropped: unexpected key(s) {sorted(extra)} "
                "the tool does not accept (would TypeError at replay)"
            )
            return None

    # Phrasing pre-validation for statement-text ops. The curator's all-or-
    # nothing replay runs the real phrasing.check; pre-running it here lets us
    # set allow_phrasing_violations rather than have the whole draft rejected at
    # review time. We never silently drop the op.
    payload, rationale = _prevalidate_phrasing(kind, payload, rationale, flagged, idx)

    return ProposedOp(
        op=kind,
        payload=payload,
        rationale=rationale,
        targets_existing=op.get("targets_existing") or [],
    )


#: The wholesale-upsert advisory appended to a refinement upsert_statement's
#: rationale when it omits links (the real tool replaces the outgoing-link set).
_WHOLESALE_NOTE = (
    " [note: upsert_statement with an id wholesale-REPLACES outgoing links; "
    "prefer patch_statement/replace_text for a partial refinement]"
)


def _normalize_and_check(
    kind: str, payload: dict, rationale: str, flagged: list[str], idx: int
) -> tuple[dict, str, bool]:
    """Replay-safe normalization + lightweight inner-shape checks for the kinds
    whose real tool would otherwise explode at curator replay. Returns
    (payload, rationale, dropped). `dropped is True` means flag-and-skip (a
    reason was already appended to `flagged`); never throws.

    - upsert_statement: `links` is REQUIRED by the real tool with no default.
      Normalize a missing/None value to []. `mentions` are derived from text,
      not asserted — drop any the model proposes. If the op carries an id (a
      refinement/wholesale upsert) and links were absent, warn in the rationale
      that a wholesale upsert replaces the link set — but still queue it.
    - upsert_statements: statements must be a non-empty list of items each with
      kind & text; normalize each item's missing links to [] and drop any
      proposed mentions.
    - add_links: links must be a non-empty list of {from_id, to_id, link_type}.
    - add_entity_links: links must be a non-empty list of
      {from_entity_id, to_entity_id, link_type} (NOT from_id/to_id).
    """
    if kind == "upsert_statement":
        had_links = payload.get("links") is not None
        normalized = dict(payload)
        normalized.pop("mentions", None)  # derived from text, never asserted
        normalized.pop("strict_mentions", None)
        if not had_links:
            normalized["links"] = []
        if payload.get("id") is not None and not had_links:
            rationale = (rationale + _WHOLESALE_NOTE).strip()
        return normalized, rationale, False

    if kind == "upsert_statements":
        stmts = payload.get("statements")
        if not isinstance(stmts, list) or not stmts:
            flagged.append(
                f"op[{idx}] (upsert_statements) dropped: 'statements' must be a "
                "non-empty list"
            )
            return payload, rationale, True
        new_stmts: list[Any] = []
        for j, s in enumerate(stmts):
            if not isinstance(s, dict) or "kind" not in s or "text" not in s:
                flagged.append(
                    f"op[{idx}] (upsert_statements) dropped: statements[{j}] must "
                    "be an object with 'kind' and 'text'"
                )
                return payload, rationale, True
            item = dict(s)
            item.pop("mentions", None)  # derived from text, never asserted
            if item.get("links") is None:
                item["links"] = []
            new_stmts.append(item)
        normalized = {**payload, "statements": new_stmts}
        return normalized, rationale, False

    if kind == "add_links":
        offending = _check_edges(
            payload.get("links"), ("from_id", "to_id", "link_type")
        )
        if offending is not None:
            flagged.append(f"op[{idx}] (add_links) dropped: {offending}")
            return payload, rationale, True
        from ..link_authoring import reject_entity_statement_additions

        try:
            reject_entity_statement_additions(payload.get("links"))
            _validate_statement_link_references(payload.get("links"))
        except ValueError as ex:
            flagged.append(f"op[{idx}] (add_links) dropped: {ex}")
            return payload, rationale, True
        return payload, rationale, False

    if kind == "add_entity_links":
        offending = _check_edges(
            payload.get("links"), ("from_entity_id", "to_entity_id", "link_type")
        )
        if offending is not None:
            flagged.append(f"op[{idx}] (add_entity_links) dropped: {offending}")
            return payload, rationale, True
        return payload, rationale, False

    return payload, rationale, False


def _validate_statement_link_references(links: object) -> None:
    if not isinstance(links, list):
        raise ValueError("links must be a list")
    for index, edge in enumerate(links):
        if not isinstance(edge, dict):
            raise ValueError(f"links[{index}] must be an object")
        references: list[object] = [edge.get("from_id"), edge.get("to_id")]
        if "when" in edge:
            expression = edge["when"]
            when_expression.validate(expression)
            references.extend(when_expression.leaves(expression))
        for reference in references:
            if not isinstance(reference, str) or not re.fullmatch(
                r"stm_.+|@\d+:\d+", reference
            ):
                raise ValueError(
                    f"links[{index}] reference {reference!r} must be a statement ID "
                    "(stm_…) or draft statement result (@seq:index)"
                )


def _check_edges(links: Any, required: tuple[str, ...]) -> str | None:
    """Return None if `links` is a non-empty list of edges each carrying every
    key in `required`, else a human-readable reason string."""
    if not isinstance(links, list) or not links:
        return "'links' must be a non-empty list"
    for j, edge in enumerate(links):
        if not isinstance(edge, dict):
            return f"links[{j}] is not an object"
        missing = [k for k in required if k not in edge]
        if missing:
            return f"links[{j}] missing required key(s) {missing}"
    return None


def _prevalidate_phrasing(
    kind: str, payload: dict, rationale: str, flagged: list[str], idx: int
) -> tuple[dict, str]:
    """For statement-text ops, run phrasing.check; on violations set
    allow_phrasing_violations and record it (never drop the op)."""
    from .. import phrasing

    if kind == "upsert_statement":
        text = payload.get("text")
        skind = payload.get("kind") or "event"
        if isinstance(text, str) and text:
            try:
                violations = phrasing.check(text, kind=str(skind))
            except Exception:  # noqa: BLE001 — phrasing engine optional/unavailable
                return payload, rationale
            if violations:
                cats = sorted({v.get("category", "?") for v in violations})
                payload = {**payload, "allow_phrasing_violations": True}
                note = (
                    f" [phrasing: allow_phrasing_violations set; violations {cats} — "
                    "reviewer should re-phrase if possible]"
                )
                rationale = (rationale + note).strip()
                flagged.append(
                    f"op[{idx}] (upsert_statement) phrasing violations {cats}; "
                    "allow_phrasing_violations set — prefer rephrasing at review"
                )
        return payload, rationale

    if kind == "upsert_statements":
        stmts = payload.get("statements")
        if isinstance(stmts, list):
            new_stmts: list[Any] = []
            changed = False
            for j, s in enumerate(stmts):
                if not isinstance(s, dict):
                    new_stmts.append(s)
                    continue
                text = s.get("text")
                skind = s.get("kind") or "event"
                if isinstance(text, str) and text:
                    try:
                        violations = phrasing.check(text, kind=str(skind))
                    except Exception:  # noqa: BLE001
                        violations = []
                    if violations:
                        cats = sorted({v.get("category", "?") for v in violations})
                        s = {**s, "allow_phrasing_violations": True}
                        changed = True
                        flagged.append(
                            f"op[{idx}].statements[{j}] phrasing violations {cats}; "
                            "allow_phrasing_violations set"
                        )
                new_stmts.append(s)
            if changed:
                payload = {**payload, "statements": new_stmts}
                rationale = (
                    rationale
                    + " [phrasing: allow_phrasing_violations set on some items]"
                ).strip()
        return payload, rationale

    return payload, rationale


# --------------------------------------------------------------------------- #
# Outcome builders
# --------------------------------------------------------------------------- #


def _nothing(reason: str, ctx: _RunContext) -> NothingToIngest:
    trace_dict = _build_trace(ctx.trace, "nothing_to_ingest", ctx)
    return NothingToIngest(reason=reason, trace=trace_dict)


def _degrade_no_draft(reason: str, ctx: _RunContext) -> NothingToIngest:
    trace: TraceBuilder = ctx.trace
    trace.degraded = True
    trace.candidate_ledger = trace.candidate_ledger or []
    trace_dict = _build_trace(trace, "nothing_to_ingest", ctx)
    return NothingToIngest(reason=reason, trace=trace_dict)


def _build_trace(trace: TraceBuilder, outcome: str, ctx: _RunContext) -> dict:
    config: IngestConfig = ctx.config
    latency_ms = (time.monotonic() - ctx.start) * 1000.0
    record = trace.build(
        outcome=outcome,
        latency_ms=latency_ms,
        floor=_floor_state(ctx.reads_after_vocab),
    )
    tracing.emit_trace(
        trace.spans,
        kind="ingest",
        label=f"{trace.input_chars} chars",
        record=record,
        trace_dir=config.trace_dir,
    )
    return record


# --------------------------------------------------------------------------- #
# Floor + ledger checks
# --------------------------------------------------------------------------- #


def _floor_state(reads_after_vocab: list[str]) -> dict:
    """The structural anti-premature-closure floor.

    Mirrors ask/loop.py:_floor_state. `_RECONCILE_TOOLS` and `_ADJACENCY_TOOLS`
    overlap on search_statements, so a single search would
    otherwise satisfy both halves at once. As ask does, the adjacency read must
    be a DISTINCT, non-first post-vocab move: at least one reconcile-class read
    AND at least one adjacency-class read counted only from index >= 1 (i.e. the
    model reconciled, then came back and searched for adjacent statements). This
    requires at least two post-vocab reads.
    """
    reconcile = sum(1 for n in reads_after_vocab if n in _RECONCILE_TOOLS)
    adjacency = sum(
        1
        for i in range(1, len(reads_after_vocab))
        if reads_after_vocab[i] in _ADJACENCY_TOOLS
    )
    return {
        "reconcile_reads": reconcile,
        "adjacency_reads": adjacency,
        "satisfied": reconcile >= 1 and adjacency >= 1,
    }


#: Op kinds that create or change a statement's text and therefore require a
#: backing new/refinement ledger row (the anti-closure coverage check).
_STATEMENT_OPS: frozenset[str] = frozenset(
    {"upsert_statement", "patch_statement", "replace_text"}
)


def _statement_op_count(ops: list[dict]) -> int:
    """Count statement-creating/refining ops the ledger must back. An
    `upsert_statements` op contributes one per item in its statements list."""
    count = 0
    for op in ops:
        kind = op.get("op")
        if kind in _STATEMENT_OPS:
            count += 1
        elif kind == "upsert_statements":
            stmts = (op.get("payload") or {}).get("statements")
            count += len(stmts) if isinstance(stmts, list) else 1
    return count


def _coverage_unmet(ops: list[dict], ledger: list[dict]) -> str | None:
    """Anti-closure coverage: every statement-creating op must have a backing
    new/refinement ledger row. Count-based (no text matching). Returns a reason
    string when coverage is unmet, else None."""
    needed = _statement_op_count(ops)
    backing = sum(1 for r in ledger if r.get("classification") in ("new", "refinement"))
    if needed > backing:
        return (
            f"{needed} statement-creating op(s) but only {backing} new/refinement "
            "ledger row(s) — each statement op needs a backing reconcile row"
        )
    return None


def _ledger_unmet(ledger: list[dict]) -> list[str]:
    """Per-candidate ledger validation for NEW/REFINEMENT rows. Returns the list
    of offending candidate descriptions (empty means well-formed)."""
    offenders: list[str] = []
    for row in ledger:
        cls = row.get("classification")
        if cls not in ("new", "refinement"):
            continue
        matched = row.get("matched_against") or []
        considered = row.get("link_candidates_considered") or []
        note = (row.get("note") or "").strip()
        if not matched:
            offenders.append(f"{row.get('candidate', '?')} (no matched_against)")
            continue
        if not considered and not note:
            offenders.append(
                f"{row.get('candidate', '?')} (no link_candidates_considered and no note)"
            )
    return offenders


def _floor_detail(floor: dict, unmet: list[str]) -> str:
    parts = [
        f"So far: {floor['reconcile_reads']} reconcile read(s) and "
        f"{floor['adjacency_reads']} adjacency search(es) after the vocab fetch."
    ]
    if unmet:
        shown = ", ".join(unmet[:5])
        parts.append(f"These NEW/REFINEMENT ledger rows are under-supported: {shown}.")
    return " ".join(parts)


def _ledger_empty_or_all_duplicate(ledger: list[dict]) -> bool:
    if not ledger:
        return True
    return all(r.get("classification") == "duplicate" for r in ledger)


def _mark_unprocessed_gaps(ledger: list[dict], trace: TraceBuilder) -> list[dict]:
    """Surface any 'unprocessed' ledger rows as trace gaps (these happen when a
    budget cap fired mid-reconcile and the forced emit left candidates untouched).

    LOW-7: gap detection cannot be delegated entirely to a (possibly degraded)
    model. On ANY forced finalize, always record a harness-side gap regardless
    of model cooperation, so a degraded run is never silently gap-free. The
    model-labeled 'unprocessed' rows are kept too."""
    if trace.forced_finalize:
        trace.gaps.append(
            f"forced finalize ({trace.forced_finalize}): candidates beyond those "
            "reconciled may be unprocessed"
        )
    for row in ledger:
        if row.get("classification") == "unprocessed":
            cand = row.get("candidate", "?")
            trace.gaps.append(f"unprocessed candidate: {cand}")
    return ledger


def _normalize_ledger_row(row: dict) -> dict:
    """Round-trip a ledger row through CandidateLedger so the trace carries the
    validated shape (and an unknown classification is coerced sanely)."""
    cls = row.get("classification")
    allowed = {
        "new",
        "duplicate",
        "refinement",
        "contradiction",
        "unphraseable",
        "unprocessed",
    }
    if cls not in allowed:
        cls = "unprocessed"
    return CandidateLedger(
        candidate=str(row.get("candidate") or ""),
        classification=cls,  # type: ignore[arg-type]
        matched_against=row.get("matched_against") or [],
        link_candidates_considered=row.get("link_candidates_considered") or [],
        note=str(row.get("note") or ""),
    ).model_dump()


# --------------------------------------------------------------------------- #
# Model call + message helpers (mirror ask/loop.py)
# --------------------------------------------------------------------------- #


def _model_turn(
    client: ai.ClaudeClient | httpx.Client | None,
    config: IngestConfig,
    system_prompt: str,
    messages: Sequence[Mapping[str, object]],
    tools: Sequence[Mapping[str, object]],
    *,
    force: bool,
    until: float,
) -> ai.ModelResponse:
    # Stream when no client is injected: an emit_draft turn can outlast
    # request_timeout_s as one blocking read, but not between streamed chunks.
    owned = client is None
    remaining = max(until - time.monotonic(), 1.0)
    return ai.turn(
        ai.ToolTask(
            system=system_prompt,
            messages=messages,
            tools=tools,
            force_tool=EMIT_TOOL if force else None,
            parallel_tools=not force,
            on_tool_delta=_discard_tool_delta if owned else None,
            deadline=until,
        ),
        ai.ModelConfig(
            provider=config.provider,
            model=config.model,
            max_tokens=config.limits.max_tokens,
            request_timeout_s=min(config.limits.request_timeout_s, remaining),
            max_retries=config.limits.max_retries,
            thinking=config.limits.thinking,
            reasoning_effort=config.reasoning_effort,
            cache=True,
        ),
        client=client,
    )


def _discard_tool_delta(_id: str, _name: str, _delta: str) -> None:
    pass


def _append_tool_result(
    messages: list[dict[str, Any]], tool_use_id: str, result: Any, *, is_error: bool
) -> None:
    block = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": _serialize(result),
        "is_error": is_error,
    }
    # A turn with several reads answers them all in one user message.
    pending = messages[-1] if messages else {}
    content = pending.get("content")
    if (
        pending.get("role") == "user"
        and isinstance(content, list)
        and any(item.get("type") == "tool_result" for item in content)
    ):
        content.append(block)
    else:
        messages.append({"role": "user", "content": [block]})


def _safe_valid_kinds(emitter: DraftEmitter) -> set[str]:
    try:
        return set(emitter.valid_kinds())
    except Exception:  # noqa: BLE001 — a stub emitter may not implement it
        return set()


def _safe_allowed_keys(emitter: DraftEmitter, kind: str) -> set[str]:
    """The kwarg names the real `kind` tool accepts, via the emitter seam. An
    empty set means "unknown — do not filter" (so we never over-drop). A stub
    emitter that doesn't implement allowed_keys degrades to that same empty
    set rather than throwing."""
    try:
        return set(emitter.allowed_keys(kind))
    except Exception:  # noqa: BLE001 — a stub emitter may not implement it
        return set()


def _draft_title(text: str) -> str:
    snippet = " ".join((text or "").split())[:60]
    return f"ingest: {snippet}" if snippet else "ingest: (empty)"
