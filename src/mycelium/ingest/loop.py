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
the real Anthropic client + in-process substrate + in-process draft emitter and
writes the trace.

THE NO-LIVE-WRITE GUARANTEE: the model is handed READ tools plus one terminal
`emit_draft` tool and never sees a write tool. The only write path in the whole
package is `drafts_store.create_draft`/`add_op`, reached exclusively through the
injected `DraftEmitter` in `_assemble_draft`. This module imports no substrate
write tool and never touches `server._conn`.
"""

from __future__ import annotations

import time
from typing import Any

from .. import tracing
from ..agentloop import (
    append_tool_error as _append_tool_error,
)
from ..agentloop import (
    check_budget,
    default_client,
    load_doctrine,
)
from ..agentloop import (
    first_tool_use as _first_tool_use,
)
from ..agentloop import (
    serialize as _serialize,
)
from ..agentloop import (
    strip_thinking as _strip_thinking,
)
from ..agentloop import (
    substrate_has as _substrate_has,
)

# Reuse ask's read seam wholesale — do NOT duplicate it.
from ..ask.substrate import InProcessSubstrate, SubstrateError, SubstrateReader
from . import prompts
from .config import IngestConfig
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
_RECONCILE_TOOLS = frozenset(
    {"discover_facts", "find_duplicates", "search_statements", "survey_statements"}
)
#: Adjacency searches — at least one must have happened before emit is accepted.
_ADJACENCY_TOOLS = frozenset(
    {"search_statements", "survey_statements", "grep_statements"}
)

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
    production they default to the real Anthropic client, the in-process
    substrate, the in-process draft emitter, and env-derived config.
    """
    config = config or IngestConfig.from_env()
    if substrate is None:
        substrate = InProcessSubstrate()
    if emitter is None:
        emitter = InProcessDraftEmitter()
    if client is None:
        client = default_client(config.max_retries)

    doctrine_text, doctrine_note = load_doctrine(config.doctrine_path)

    with tracing.profile_to_html("ingest", f"{len(text)} chars"):
        result = _execute(
            text, client, substrate, emitter, config, doctrine_text, doctrine_note
        )

    if config.trace_log_path:
        from .trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


class _RunContext:
    """Plain bag of per-run harness state, so the finalizers/handlers below
    don't each need ten-plus positional parameters (mirrors research/loop.py)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _execute(
    text: str,
    client: Any,
    substrate: SubstrateReader,
    emitter: DraftEmitter,
    config: IngestConfig,
    doctrine_text: str,
    doctrine_note: str | None,
) -> IngestResult:
    start = time.monotonic()

    # ---- Step 1: input guard — head-truncate, never silently blow the cap ----
    text, input_note = _guard_input(text, config)

    trace = TraceBuilder(
        model=config.model,
        op_cap=config.op_cap,
        wall_clock_s=config.wall_clock_s,
        input_chars=len(text),
    )
    if doctrine_note:
        trace.notes.append(doctrine_note)
    if input_note:
        trace.notes.append(input_note)

    system_prompt = prompts.build_system_prompt(doctrine_text)
    tools = build_tools(substrate.tool_specs())

    # ---- Step 2: vocab fetch (deterministic; each counts toward the op cap) ----
    vocab = _fetch_vocab(substrate, trace)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompts.initial_user_message(text, vocab)}
    ]

    reads_after_vocab: list[str] = []  # successful read names, for the floor
    max_turns = config.op_cap + _TURN_HEADROOM

    ctx = _RunContext(
        text=text,
        system_prompt=system_prompt,
        client=client,
        substrate=substrate,
        config=config,
        tools=tools,
        messages=messages,
        emitter=emitter,
        trace=trace,
        start=start,
        reads_after_vocab=reads_after_vocab,
        nudged=False,
        floor_blocks=0,
        malformed_retries=0,
    )

    while True:
        # ---- Budget gates first — forced finalize bypasses the floor ----
        reason = check_budget(trace, config, start, max_turns)
        if reason:
            return _forced_finalize(reason, ctx)

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
        name = tool_use.name

        # ---- Terminal: emit_draft (gated by the floor + ledger well-formedness) ----
        if name == EMIT_TOOL:
            result = _handle_emit(tool_use, ctx)
            if result is not None:
                return result
            continue

        # ---- A substrate READ primitive ----
        # Only a SUCCESSFUL read counts toward the floor — a SubstrateError
        # gathered no data. It still counts toward the op cap (recorded).
        if _dispatch_read(
            name, dict(tool_use.input or {}), tool_use.id, substrate, trace, messages
        ):
            reads_after_vocab.append(name)


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


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _guard_input(text: str, config: IngestConfig) -> tuple[str, str | None]:
    text = text or ""
    if len(text) <= config.max_input_chars:
        return text, None
    head = text[: config.max_input_chars]
    note = (
        f"input truncated: {len(text)} chars exceeded max_input_chars="
        f"{config.max_input_chars}; only the head was processed (tail is a gap)"
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
    """Last resort: force one emit_draft turn (floor bypassed, thinking off),
    else give up gracefully with NothingToIngest. Never throws, never partial
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

    valid_kinds = _safe_valid_kinds(emitter)
    validated: list[ProposedOp] = []
    for idx, op in enumerate(ops):
        kept = _validate_op(op, idx, valid_kinds, flagged, emitter)
        if kept is not None:
            validated.append(kept)

    trace.proposed_ops = [p.model_dump() for p in validated]
    trace.flagged = flagged

    # Create a draft if there is at least one queue-able op OR the model raised a
    # real flag (a contradiction is itself a reviewable artifact). If every op
    # was rejected by validation and the model raised no flag of its own, there
    # is nothing worth a draft — degrade gracefully rather than emit an empty one.
    if not validated and not model_flags:
        reason = (
            "no valid ops survived validation; see flagged trace"
            if ops
            else "nothing extractable"
        )
        return _nothing(reason, ctx)

    # ---- The ONLY write path: create the draft + queue ops via the emitter ----
    # LOW-8 (deferred): a classification<->op cross-check (e.g. detecting a NEW
    # upsert that duplicates an existing statement the model already classified
    # as a duplicate) is NOT implemented here — it needs fragile text heuristics
    # and is a deliberate deferral.
    #
    # MED-4: draft assembly is atomic in spirit — once create() returns a
    # draft_id we NEVER discard it. A create() failure means no draft exists, so
    # we degrade with NothingToIngest. But once the draft exists, an add_op
    # failure on one op moves that op to `flagged` and we keep queueing the rest,
    # then always return DraftCreated with the real draft_id and whatever landed.
    # That honors "emit what was processed; never partial/orphaned write".
    try:
        draft_id = emitter.create(title=_draft_title(ctx.text))
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
    return DraftCreated(
        draft_id=draft_id,
        ops=queued,
        flagged=flagged,
        skipped_duplicates=list(skipped),
        trace=trace_dict,
    )


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
        input_per_mtok=config.input_per_mtok,
        output_per_mtok=config.output_per_mtok,
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
    overlap on search_statements/survey_statements, so a single search would
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
    client: Any,
    config: IngestConfig,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict],
    *,
    force: bool,
) -> Any:
    c = client
    if hasattr(client, "with_options"):
        c = client.with_options(
            timeout=config.request_timeout_s, max_retries=config.max_retries
        )
    kwargs: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
    }
    if force:
        # Forcing a specific tool is incompatible with extended thinking, so we
        # leave thinking off on the emergency finalize turn — and strip the
        # thinking blocks the adaptive turns left in history.
        kwargs["messages"] = _strip_thinking(messages)
        kwargs["tool_choice"] = {
            "type": "tool",
            "name": EMIT_TOOL,
            "disable_parallel_tool_use": True,
        }
    else:
        kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        if config.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
    return c.messages.create(**kwargs)


def _append_tool_result(
    messages: list[dict[str, Any]], tool_use_id: str, result: Any, *, is_error: bool
) -> None:
    text = _serialize(result)
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": text,
                    "is_error": is_error,
                }
            ],
        }
    )


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
