"""The `research` write-harness loop.

One model context drives explore -> conclude -> reconcile -> classify -> link
-> emit over the workspace read tools plus the substrate READ primitives; this
module is the deterministic harness around it — source fetch, vocab fetch, the
tool-use loop, the exploration+reconcile floor, the op-cap / wall-clock
ceilings, draft assembly + validation, and graceful degradation. The model
reasons; this code fetches, counts, bounds, validates, and records.

Core-at-the-center: `_execute` depends only on a client-like object (anything
with `.messages.create(...)`), a `SubstrateReader`, a `WorkspaceReader`-shaped
object, and a `DraftEmitter`. All four are injectable, so the loop is
exercisable with plain fakes — no server, no DB, no network, no git. The
framework seam (`run_research`) wires the real Anthropic client, in-process
substrate, a fresh shallow-clone workspace, and the in-process draft emitter.

THE NO-LIVE-WRITE GUARANTEE: the model is handed READ tools plus one terminal
`emit_draft` tool and never sees a write tool. The only write path is the
injected `DraftEmitter` (ingest's seam) inside `_assemble_draft`. This module
imports no substrate write tool and never touches `server._conn`.

The emit/validation machinery is ingest's, imported — not copied — so the op
vocabulary, replay-safety checks, and phrasing pre-validation stay in lockstep
with ingest by construction.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import prompts, sources
from .config import ResearchConfig
from .schema import NothingFound, ProposedOp, ResearchDraftCreated, ResearchResult
from .sources import Source, SourceError
from .workspace import WorkspaceError, WorkspaceReader
from .. import tracing

# Reuse ingest's harness machinery wholesale — do NOT duplicate it. The loop
# below imports only read/validate/assemble helpers; no write tool exists in
# ingest.loop to import.
from ..ingest.draft import DraftEmitter, InProcessDraftEmitter
from ..ingest.loop import (
    _MAX_FLOOR_BLOCKS,
    _MAX_MALFORMED_RETRIES,
    _TURN_HEADROOM,
    _append_tool_error,
    _append_tool_result,
    _coverage_unmet,
    _fetch_vocab,
    _first_tool_use,
    _floor_state,
    _ledger_empty_or_all_duplicate,
    _ledger_unmet,
    _mark_unprocessed_gaps,
    _model_turn,
    _normalize_ledger_row,
    _safe_valid_kinds,
    _substrate_has,
    _validate_op,
)
from ..ingest.tools import EMIT_TOOL, build_tools, parse_emit_input
from ..ingest.trace import TraceBuilder
from ..ask.substrate import InProcessSubstrate, SubstrateError, SubstrateReader

#: Exploration floor: this many successful workspace reads, at least one of
#: which actually read a file (listing/grepping without reading is not
#: exploration).
_MIN_WORKSPACE_READS = 3
_FILE_READ_TOOL = "ws_read_file"


def run_research(
    topic: str,
    source: Source | str | None = None,
    *,
    client: Any | None = None,
    substrate: SubstrateReader | None = None,
    workspace: Any | None = None,
    emitter: DraftEmitter | None = None,
    config: ResearchConfig | None = None,
) -> ResearchResult:
    """Research `topic` in `source`'s codebase and produce a reviewable DRAFT.

    Returns `ResearchDraftCreated` or `NothingFound` — never raises for
    fetch/exploration/closure reasons, and never writes live.

    `source` is a configured source name or a `Source`; it may be omitted only
    when a `workspace` is injected. When `workspace` is None the source is
    shallow-cloned into a temp dir that is always wiped afterward; an injected
    workspace means no git/network is touched at all (how tests run).
    """
    config = config or ResearchConfig.from_env()

    src: Source | None = None
    if isinstance(source, Source):
        src = source
    elif isinstance(source, str):
        try:
            src = sources.get_source(source)
        except SourceError as exc:
            return NothingFound(
                reason=f"source error: {exc}", source=source, topic=topic
            )
    source_name = src.name if src is not None else "(injected workspace)"

    if substrate is None:
        substrate = InProcessSubstrate()
    if emitter is None:
        emitter = InProcessDraftEmitter()
    if client is None:
        client = _default_client(config)

    doctrine_text, doctrine_note = _load_doctrine(config)

    with tracing.profile_to_html("research", f"{source_name}: {topic[:40]}"):
        if workspace is None:
            if src is None:
                return NothingFound(
                    reason="no source given and no workspace injected",
                    source="",
                    topic=topic,
                )
            try:
                with sources.fetch(src) as root:
                    result = _execute(
                        topic,
                        source_name,
                        client,
                        substrate,
                        WorkspaceReader(root),
                        emitter,
                        config,
                        doctrine_text,
                        doctrine_note,
                    )
            except SourceError as exc:
                # Message is pre-scrubbed by sources; never re-raise.
                return NothingFound(
                    reason=f"source fetch failed: {exc}",
                    source=source_name,
                    topic=topic,
                )
        else:
            result = _execute(
                topic,
                source_name,
                client,
                substrate,
                workspace,
                emitter,
                config,
                doctrine_text,
                doctrine_note,
            )

    if config.trace_log_path:
        from ..ingest.trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


def _default_client(config: ResearchConfig) -> Any:
    import anthropic  # local import: keeps the package importable without the key

    return anthropic.Anthropic(max_retries=config.max_retries)


def _load_doctrine(config: ResearchConfig) -> tuple[str, str | None]:
    """Read the research doctrine best-effort. On failure, return ("", note)
    so the loop proceeds on the base prompt and records why."""
    try:
        return Path(config.doctrine_path).read_text(encoding="utf-8"), None
    except Exception as exc:  # noqa: BLE001 — best-effort; proceed without it
        return "", f"doctrine unreadable ({config.doctrine_path}): {exc}"


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


def _execute(
    topic: str,
    source_name: str,
    client: Any,
    substrate: SubstrateReader,
    workspace: Any,
    emitter: DraftEmitter,
    config: ResearchConfig,
    doctrine_text: str,
    doctrine_note: str | None,
) -> ResearchResult:
    start = time.monotonic()

    topic, input_note = _guard_topic(topic, config)

    trace = TraceBuilder(
        model=config.model,
        op_cap=config.op_cap,
        wall_clock_s=config.wall_clock_s,
        input_chars=len(topic),
    )
    if doctrine_note:
        trace.notes.append(doctrine_note)
    if input_note:
        trace.notes.append(input_note)

    system_prompt = prompts.build_system_prompt(doctrine_text)
    tools = build_tools([*workspace.tool_specs(), *substrate.tool_specs()])

    vocab = _fetch_vocab(substrate, trace)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": prompts.initial_user_message(topic, source_name, vocab),
        }
    ]

    # Successful read names, split by seam: substrate reads feed ingest's
    # reconcile floor; workspace reads feed the exploration floor. `files_read`
    # collects the distinct paths ws_read_file succeeded on, for the trace.
    substrate_reads: list[str] = []
    workspace_reads: list[str] = []
    files_read: set[str] = set()

    ctx = _RunContext(
        topic=topic,
        source_name=source_name,
        system_prompt=system_prompt,
        client=client,
        config=config,
        tools=tools,
        messages=messages,
        emitter=emitter,
        trace=trace,
        start=start,
        substrate_reads=substrate_reads,
        workspace_reads=workspace_reads,
        files_read=files_read,
    )

    nudged = False
    floor_blocks = 0
    malformed_retries = 0
    max_turns = config.op_cap + _TURN_HEADROOM

    while True:
        # ---- Budget gates first — forced finalize bypasses the floor ----
        if trace.op_count >= config.op_cap:
            return _forced_finalize("op_cap", ctx)
        if (time.monotonic() - start) > config.wall_clock_s:
            return _forced_finalize("wall_clock", ctx)
        if trace.model_turns >= max_turns:
            return _forced_finalize("turn_limit", ctx)

        try:
            with trace.span("model_turn"):
                resp = _model_turn(
                    client, config, system_prompt, messages, tools, force=False
                )
        except Exception as exc:  # noqa: BLE001 — terminal API error after SDK backoff
            trace.notes.append(f"model error: {exc}")
            return _forced_finalize("api_error", ctx)
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        messages.append({"role": "assistant", "content": resp.content})

        tool_use = _first_tool_use(resp)
        if tool_use is None:
            if not nudged:
                nudged = True
                messages.append({"role": "user", "content": prompts.NO_TERMINAL_NUDGE})
                continue
            return _forced_finalize("no_terminal", ctx)

        nudged = False
        name = tool_use.name
        tool_input = dict(tool_use.input or {})

        # ---- Terminal: emit_draft (gated by the floor + ledger checks) ----
        if name == EMIT_TOOL:
            try:
                ops, ledger, flagged, skipped = parse_emit_input(tool_input)
            except ValueError as exc:
                if malformed_retries < _MAX_MALFORMED_RETRIES:
                    malformed_retries += 1
                    _append_tool_error(
                        messages, tool_use.id, prompts.malformed_retry_message(str(exc))
                    )
                    continue
                trace.notes.append(f"emit_draft malformed twice: {exc}")
                return _degrade_no_draft("degraded: emit_draft malformed twice", ctx)

            floor = _research_floor(workspace_reads, substrate_reads)
            unmet = _ledger_unmet(ledger)
            coverage = _coverage_unmet(ops, ledger)
            if coverage:
                unmet = [*unmet, coverage]
            if not floor["satisfied"] or unmet:
                if floor_blocks < _MAX_FLOOR_BLOCKS:
                    floor_blocks += 1
                    _append_tool_error(
                        messages,
                        tool_use.id,
                        prompts.floor_block_message(
                            _research_floor_detail(floor, unmet)
                        ),
                    )
                    continue
                _append_tool_error(
                    messages,
                    tool_use.id,
                    "Floor still unmet after repeated attempts; finalizing with "
                    "what has been established.",
                )
                return _forced_finalize("floor_stuck", ctx)
            return _assemble_draft(ops, ledger, flagged, skipped, ctx, degraded=False)

        # ---- A read: workspace or substrate, dispatched by name ----
        _dispatch_read(name, tool_input, tool_use.id, substrate, workspace, ctx)


class _RunContext:
    """Plain bag of per-run harness state, so the helpers below don't need
    ten positional parameters each (ingest predates this; research has two
    extra read seams, which tipped the balance)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _guard_topic(topic: str, config: ResearchConfig) -> tuple[str, str | None]:
    topic = topic or ""
    if len(topic) <= config.max_topic_chars:
        return topic, None
    head = topic[: config.max_topic_chars]
    note = (
        f"topic truncated: {len(topic)} chars exceeded max_topic_chars="
        f"{config.max_topic_chars}; only the head was processed"
    )
    return head, note


def _workspace_has(workspace: Any, name: str) -> bool:
    has = getattr(workspace, "has", None)
    if callable(has):
        return bool(has(name))
    return any(spec.name == name for spec in workspace.tool_specs())


def _dispatch_read(
    name: str,
    arguments: dict[str, Any],
    tool_use_id: str,
    substrate: SubstrateReader,
    workspace: Any,
    ctx: _RunContext,
) -> None:
    """Execute one read against whichever seam owns the tool. Only a SUCCESSFUL
    read counts toward its floor; every attempt counts toward the op cap."""
    trace: TraceBuilder = ctx.trace
    messages: list[dict[str, Any]] = ctx.messages

    if _workspace_has(workspace, name):
        try:
            with trace.span(f"tool:{name}"):
                result = workspace.call(name, arguments)
            trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
            _append_tool_result(messages, tool_use_id, result, is_error=False)
            ctx.workspace_reads.append(name)
            if name == _FILE_READ_TOOL and arguments.get("path"):
                ctx.files_read.add(str(arguments["path"]))
        except WorkspaceError as exc:
            trace.record_tool_call(
                name, arguments, None, ok=False, counts_as_op=True, error=str(exc)
            )
            _append_tool_result(
                messages, tool_use_id, {"error": str(exc)}, is_error=True
            )
        return

    if not _substrate_has(substrate, name):
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error="unknown tool"
        )
        _append_tool_error(messages, tool_use_id, f"unknown tool: {name}")
        return
    try:
        with trace.span(f"tool:{name}"):
            result = substrate.call(name, arguments)
        trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
        _append_tool_result(messages, tool_use_id, result, is_error=False)
        ctx.substrate_reads.append(name)
    except SubstrateError as exc:
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error=str(exc)
        )
        _append_tool_result(messages, tool_use_id, {"error": str(exc)}, is_error=True)


def _forced_finalize(reason: str, ctx: _RunContext) -> ResearchResult:
    """Last resort: force one emit_draft turn (floor bypassed, thinking off),
    else give up gracefully with NothingFound. Never throws, never partial
    live-write."""
    trace: TraceBuilder = ctx.trace
    trace.forced_finalize = reason
    trace.degraded = True
    ctx.messages.append(
        {"role": "user", "content": prompts.forced_finalize_message(reason)}
    )
    try:
        with trace.span("model_turn:forced"):
            resp = _model_turn(
                ctx.client,
                ctx.config,
                ctx.system_prompt,
                ctx.messages,
                ctx.tools,
                force=True,
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
        trace.notes.append(f"forced finalize failed: {exc}")
    return _degrade_no_draft(f"degraded: could not assemble a draft ({reason})", ctx)


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
) -> ResearchResult:
    """Validate the model's ops (ingest's `_validate_op`, imported), queue the
    valid ones into a draft via the emitter, and return the structured outcome.
    Never throws; hard-validation failures are moved to `flagged`, not queued,
    and never become a live write."""
    trace: TraceBuilder = ctx.trace
    emitter: DraftEmitter = ctx.emitter
    if degraded:
        trace.degraded = True

    model_flags = list(flagged)
    flagged = list(flagged)
    ledger = _mark_unprocessed_gaps(ledger, trace)
    trace.candidate_ledger = [_normalize_ledger_row(r) for r in ledger]
    trace.skipped_duplicates = list(skipped)

    if not ops and not model_flags and _ledger_empty_or_all_duplicate(ledger):
        reason = (
            "all candidates were duplicates"
            if any(r.get("classification") == "duplicate" for r in ledger)
            else "nothing substantiated on the topic"
        )
        trace.flagged = flagged
        return _nothing(reason, ctx)

    valid_kinds = _safe_valid_kinds(emitter)
    validated: list[ProposedOp] = []
    for idx, op in enumerate(ops):
        kept = _validate_op(op, idx, valid_kinds, flagged, emitter)
        if kept is not None:
            validated.append(kept)

    trace.proposed_ops = [p.model_dump() for p in validated]
    trace.flagged = flagged

    if not validated and not model_flags:
        reason = (
            "no valid ops survived validation; see flagged trace"
            if ops
            else "nothing substantiated on the topic"
        )
        return _nothing(reason, ctx)

    # ---- The ONLY write path: create the draft + queue ops via the emitter ----
    # Same atomicity posture as ingest (MED-4 there): once create() returns a
    # draft_id we never discard it; a per-op add_op failure flags that op and
    # queueing continues.
    try:
        draft_id = emitter.create(title=_draft_title(ctx.source_name, ctx.topic))
    except Exception as exc:  # noqa: BLE001 — no draft exists yet: degrade cleanly
        trace.notes.append(f"draft create failed: {exc}")
        return _degrade_no_draft(
            f"degraded: could not assemble a draft (draft store error: {exc})", ctx
        )

    queued: list[ProposedOp] = []
    for i, p in enumerate(validated):
        try:
            emitter.add_op(draft_id, p.op, p.payload)
            queued.append(p)
        except Exception as exc:  # noqa: BLE001 — never throw; flag and continue
            flagged.append(
                f"op[{i}] ({p.op}) dropped: draft store error queueing it: {exc}"
            )

    trace.proposed_ops = [p.model_dump() for p in queued]
    trace.flagged = flagged

    trace_dict = _build_trace(trace, "draft_created", ctx)
    return ResearchDraftCreated(
        draft_id=draft_id,
        source=ctx.source_name,
        topic=ctx.topic,
        ops=queued,
        flagged=flagged,
        skipped_duplicates=list(skipped),
        trace=trace_dict,
    )


# --------------------------------------------------------------------------- #
# Outcome builders
# --------------------------------------------------------------------------- #


def _nothing(reason: str, ctx: _RunContext) -> NothingFound:
    trace_dict = _build_trace(ctx.trace, "nothing_found", ctx)
    return NothingFound(
        reason=reason, source=ctx.source_name, topic=ctx.topic, trace=trace_dict
    )


def _degrade_no_draft(reason: str, ctx: _RunContext) -> NothingFound:
    trace: TraceBuilder = ctx.trace
    trace.degraded = True
    trace.candidate_ledger = trace.candidate_ledger or []
    trace_dict = _build_trace(trace, "nothing_found", ctx)
    return NothingFound(
        reason=reason, source=ctx.source_name, topic=ctx.topic, trace=trace_dict
    )


def _build_trace(trace: TraceBuilder, outcome: str, ctx: _RunContext) -> dict:
    config: ResearchConfig = ctx.config
    latency_ms = (time.monotonic() - ctx.start) * 1000.0
    record = trace.build(
        outcome=outcome,
        latency_ms=latency_ms,
        floor=_research_floor(ctx.workspace_reads, ctx.substrate_reads),
        input_per_mtok=config.input_per_mtok,
        output_per_mtok=config.output_per_mtok,
    )
    record["source"] = ctx.source_name
    record["topic"] = ctx.topic
    record["files_read"] = sorted(ctx.files_read)
    tracing.emit_trace(
        trace.spans,
        kind="research",
        label=f"{ctx.source_name}: {ctx.topic[:40]}",
        record=record,
        trace_dir=config.trace_dir,
    )
    return record


# --------------------------------------------------------------------------- #
# Floor
# --------------------------------------------------------------------------- #


def _research_floor(workspace_reads: list[str], substrate_reads: list[str]) -> dict:
    """The structural floor for research: EXPLORED and RECONCILED.

    Exploration half: at least `_MIN_WORKSPACE_READS` successful workspace
    reads, of which at least one actually read a file — listing and grepping
    without reading is hypothesis generation, not evidence.

    Reconcile half: ingest's substrate floor verbatim (>=1 reconcile-class
    read AND >=1 distinct, non-first adjacency search), over the substrate
    reads only.
    """
    substrate_floor = _floor_state(substrate_reads)
    file_reads = sum(1 for n in workspace_reads if n == _FILE_READ_TOOL)
    explored = len(workspace_reads) >= _MIN_WORKSPACE_READS and file_reads >= 1
    return {
        "workspace_reads": len(workspace_reads),
        "file_reads": file_reads,
        "explored": explored,
        "reconcile_reads": substrate_floor["reconcile_reads"],
        "adjacency_reads": substrate_floor["adjacency_reads"],
        "reconciled": substrate_floor["satisfied"],
        "satisfied": explored and substrate_floor["satisfied"],
    }


def _research_floor_detail(floor: dict, unmet: list[str]) -> str:
    parts = [
        f"So far: {floor['workspace_reads']} workspace read(s) of which "
        f"{floor['file_reads']} read a file; {floor['reconcile_reads']} "
        f"reconcile read(s) and {floor['adjacency_reads']} adjacency "
        "search(es) against the substrate."
    ]
    if unmet:
        shown = ", ".join(unmet[:5])
        parts.append(f"These NEW/REFINEMENT ledger rows are under-supported: {shown}.")
    return " ".join(parts)


def _draft_title(source_name: str, topic: str) -> str:
    snippet = " ".join((topic or "").split())[:60]
    return (
        f"research: {source_name}: {snippet}" if snippet else f"research: {source_name}"
    )
