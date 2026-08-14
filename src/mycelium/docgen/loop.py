"""The `docgen` generation loop.

One model context resolves what to write, reads the substrate, and hands back
a document; this module is the deterministic harness around it — the
resolution turn, recon, the tool-use loop, the grounding gate, the op-cap /
wall-clock ceilings, and graceful degradation. The model writes; this code
chooses nothing about the prose, and refuses what it cannot let stand.

Core-at-the-center: `_execute` depends only on a client-like object (anything
with `.messages.create(...)`), a `SubstrateReader`, a gap-reporting callable,
and a `load_texts` callable. All four are injectable, so the loop is
exercisable with plain fakes — no server, no DB, no network. The framework
seam (`run_docgen`) wires the real Anthropic client, the in-process substrate,
`server.report_knowledge_gap`, and the prompt store.

Structurally read-only over the substrate
-----------------------------------------
The model is handed the discovered READ primitives, `report_knowledge_gap`,
and `emit_document`. No tool it can reach carries a mutation prefix or a
`draft_id`, so a generation run cannot enter the draft pipeline and nothing it
writes becomes substrate truth. `report_knowledge_gap` does write — a gap
record for a human — which is exactly why `ask/substrate.py` withholds it from
discovery and why this package names it explicitly.

What is NOT shared with `ingest` / `research`
---------------------------------------------
Their loops terminate in substrate ops, so they share op validation, ledger
normalization, draft assembly and the phrasing gate. A loop terminating in a
document body can use none of that. What it does share is `..agentloop` — the
injectable client, `load_doctrine`, the budget gate, tool-result
serialization, the trace mechanics — and the package layout. The resemblance
between the four packages is a layout, not a common implementation.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from .. import tracing
from ..agentloop import (
    append_tool_error as _append_tool_error,
)
from ..agentloop import (
    check_budget,
    collect_statement_ids,
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
from ..ask.substrate import InProcessSubstrate, SubstrateError, SubstrateReader
from . import prompts
from .config import DOCTRINE_NAME, DocgenConfig
from .schema import DocgenResult, DocumentWritten, NothingWritten
from .tools import (
    EMIT_TOOL,
    GAP_TOOL,
    RESOLVE_TOOL,
    build_tools,
    parse_emit_input,
    resolve_tool_def,
)
from .trace import TraceBuilder

#: Safety stops so a stubborn model can't spin forever without consuming ops.
_MAX_EMIT_BLOCKS = 3
_MAX_MALFORMED_RETRIES = 1
_MAX_RESOLUTION_RETRIES = 1
#: Hard ceiling on model turns, well above any real run (op cap bounds reads).
_TURN_HEADROOM = 16
#: How many unretrieved ids to name back when an emit cites them.
_MAX_NAMED_IDS = 10
#: Longest slug the harness will derive from a title.
_MAX_SLUG_CHARS = 80


def run_docgen(
    prompt: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
    client: Any | None = None,
    substrate: SubstrateReader | None = None,
    report_gap: Callable[[str], Any] | None = None,
    config: DocgenConfig | None = None,
) -> DocgenResult:
    """Write one document for `prompt`. Returns `DocumentWritten` or
    `NothingWritten` — never raises for retrieval, resolution or closure
    reasons, and never writes to the substrate.

    `guideline_set` / `document_type` are what the REQUEST named; either may
    be None, in which case the run resolves it. Everything else is injectable
    for tests; in production they default to the real Anthropic client, the
    in-process substrate, `server.report_knowledge_gap`, and env-derived
    config.
    """
    config = config or DocgenConfig.from_env()
    if substrate is None:
        substrate = InProcessSubstrate()
    if client is None:
        client = default_client(config.max_retries)
    if report_gap is None:
        report_gap = _default_gap_reporter

    doctrine_text, doctrine_note = load_doctrine(
        config.doctrine_path, name=DOCTRINE_NAME
    )

    with tracing.profile_to_html("docgen", prompt[:40]):
        result = _execute(
            prompt,
            requested_set=guideline_set,
            requested_type=document_type,
            client=client,
            substrate=substrate,
            report_gap=report_gap,
            config=config,
            doctrine_text=doctrine_text,
            doctrine_note=doctrine_note,
            catalogue=_store_catalogue(),
            load_texts=_store_texts,
        )

    if config.trace_log_path:
        from .trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


# --------------------------------------------------------------------------- #
# Framework seams: the prompt store and the gap report
# --------------------------------------------------------------------------- #


def _store_catalogue() -> dict[str, list[str]]:
    """What sets are configured, best-effort.

    Same posture as `load_doctrine`: no store wired up (a bench script, a unit
    test) and a broken store both read as "nothing configured", and the run
    then refuses on its own terms instead of taking an exception to the
    caller.
    """
    from .. import guidelines, prompt_store

    if not prompt_store.is_configured():
        return {}
    try:
        return guidelines.catalogue(prompt_store.connection())
    except Exception:  # noqa: BLE001 — best-effort; an empty catalogue refuses
        return {}


def _store_texts(set_name: str, document_type: str) -> tuple[str | None, str | None]:
    from .. import guidelines, prompt_store

    if not prompt_store.is_configured():
        return None, None
    try:
        return guidelines.texts(prompt_store.connection(), set_name, document_type)
    except Exception:  # noqa: BLE001 — best-effort; a missing template refuses
        return None, None


def _default_gap_reporter(text: str) -> Any:
    """File a knowledge gap through the substrate's own tool.

    Imported here rather than at module scope so the package imports without
    a booted server, and called through `server` so a gap filed by a run is
    indistinguishable from one filed by any other caller.
    """
    from .. import server

    return server.report_knowledge_gap(text)


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


class _RunContext:
    """Plain bag of per-run harness state, so the handlers below don't each
    need a dozen positional parameters (mirrors ask/ingest/research)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _execute(
    prompt: str,
    *,
    requested_set: str | None,
    requested_type: str | None,
    client: Any,
    substrate: SubstrateReader,
    report_gap: Callable[[str], Any],
    config: DocgenConfig,
    doctrine_text: str,
    doctrine_note: str | None,
    catalogue: dict[str, list[str]],
    load_texts: Callable[[str, str], tuple[str | None, str | None]],
) -> DocgenResult:
    start = time.monotonic()
    trace = TraceBuilder(
        model=config.model,
        op_cap=config.op_cap,
        wall_clock_s=config.wall_clock_s,
        prompt=prompt,
        requested_set=requested_set,
        requested_type=requested_type,
    )
    if doctrine_note:
        trace.notes.append(doctrine_note)

    ctx = _RunContext(
        prompt=prompt,
        client=client,
        substrate=substrate,
        report_gap=report_gap,
        config=config,
        trace=trace,
        start=start,
        messages=[],
        system_prompt="",
        tools=[],
        guideline_set=None,
        document_type=None,
        unresolved="",
        retrieved_ids=set(),
        successful_reads=0,
        gaps=[],
        nudged=False,
        emit_blocks=0,
        malformed_retries=0,
    )

    resolved = _resolve(prompt, catalogue, requested_set, requested_type, ctx)
    if resolved is None:
        return _nothing(ctx, ctx.unresolved)
    ctx.guideline_set, ctx.document_type = resolved
    trace.guideline_set, trace.document_type = resolved

    guidance, template = load_texts(*resolved)
    if not (template or "").strip():
        return _nothing(
            ctx,
            f"guideline set '{ctx.guideline_set}' has no template stored for "
            f"'{ctx.document_type}'",
        )
    if not (guidance or "").strip():
        trace.notes.append(f"no set-wide guidance row for '{ctx.guideline_set}'")

    ctx.system_prompt = prompts.build_system_prompt(
        doctrine_text,
        guideline_set=ctx.guideline_set,
        document_type=ctx.document_type,
        guidance=guidance,
        template=template,
    )
    ctx.tools = build_tools(substrate.tool_specs())

    recon = _recon(ctx)
    ctx.messages = [
        {
            "role": "user",
            "content": prompts.initial_user_message(
                prompt,
                recon,
                guideline_set=ctx.guideline_set,
                document_type=ctx.document_type,
            ),
        }
    ]
    return _write(ctx)


def _write(ctx: _RunContext) -> DocgenResult:
    """The tool-use loop: read, file gaps, emit. Returns the outcome."""
    trace: TraceBuilder = ctx.trace
    max_turns = ctx.config.op_cap + _TURN_HEADROOM

    while True:
        reason = check_budget(trace, ctx.config, ctx.start, max_turns)
        if reason:
            return _forced_finalize(reason, ctx)

        try:
            with trace.span("model_turn"):
                resp = _model_turn(ctx, ctx.messages, force_tool=None)
        except Exception as exc:  # noqa: BLE001 — terminal API error after backoff
            trace.notes.append(f"model error: {exc}")
            return _forced_finalize("api_error", ctx)
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        ctx.messages.append({"role": "assistant", "content": resp.content})

        tool_use = _first_tool_use(resp)
        if tool_use is None:
            if not ctx.nudged:
                ctx.nudged = True
                ctx.messages.append(
                    {"role": "user", "content": prompts.NO_TERMINAL_NUDGE}
                )
                continue
            return _forced_finalize("no_terminal", ctx)

        ctx.nudged = False
        if tool_use.name == EMIT_TOOL:
            result = _handle_emit(tool_use, ctx, degraded=False)
            if result is not None:
                return result
            continue
        if tool_use.name == GAP_TOOL:
            _handle_gap(tool_use, ctx)
            continue
        _dispatch_read(tool_use.name, dict(tool_use.input or {}), tool_use.id, ctx)


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def _resolve(
    prompt: str,
    catalogue: dict[str, list[str]],
    requested_set: str | None,
    requested_type: str | None,
    ctx: _RunContext,
) -> tuple[str, str] | None:
    """Settle which guideline set and document type the run writes against.

    The catalogue is the store's, so what is selectable is what is
    configured — a set added as three `save_prompt_text` calls is choosable
    here with no code change. A request that named a valid pair is taken as
    given and costs no model turn; anything else is one forced tool call, and
    a pair that does not appear together in the catalogue is sent back once
    rather than accepted.

    None means "could not settle it", with the reason left on `ctx.unresolved`
    so the refusal the caller reads says which of these happened.
    """
    trace: TraceBuilder = ctx.trace
    if not catalogue:
        return _unresolvable(ctx, "no guideline sets are configured")
    if requested_set and requested_set not in catalogue:
        return _unresolvable(
            ctx,
            f"the request named guideline set '{requested_set}', which is not "
            f"configured; configured: {sorted(catalogue)}",
        )
    if requested_set and requested_type:
        if requested_type not in catalogue[requested_set]:
            return _unresolvable(
                ctx,
                f"the request named document type '{requested_type}', which "
                f"'{requested_set}' has no template for; it can write: "
                f"{catalogue[requested_set]}",
            )
        trace.resolution_reason = "named by the request"
        return requested_set, requested_type

    narrowed = _narrow(catalogue, requested_set, requested_type)
    if not narrowed:
        return _unresolvable(
            ctx,
            f"no configured guideline set has a template for document type "
            f"'{requested_type}'; configured: {catalogue}",
        )
    tool = resolve_tool_def(narrowed, ctx.config.guideline_set)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": prompts.resolution_message(
                prompt,
                narrowed,
                requested_set=requested_set,
                requested_type=requested_type,
            ),
        }
    ]

    for attempt in range(_MAX_RESOLUTION_RETRIES + 1):
        choice = _resolution_turn(ctx, messages, tool)
        if choice is None:
            return None  # `_resolution_turn` already recorded why
        tool_use_id, chosen_set, chosen_type, reason = choice
        # Checked against `narrowed`, not the whole catalogue: it already
        # carries what the request fixed, so a model that wandered off a named
        # document type is caught here rather than trusted to have kept it.
        if chosen_type in narrowed.get(chosen_set, []):
            trace.resolution_reason = reason
            return chosen_set, chosen_type
        if attempt == _MAX_RESOLUTION_RETRIES:
            break
        # As a tool_result, not as plain user text: the assistant turn just
        # added carries a pending tool_use, and the API requires it be
        # answered before the next turn.
        _append_tool_error(
            messages,
            tool_use_id,
            prompts.resolution_retry_message(
                chosen_set, chosen_type, narrowed.get(chosen_set, [])
            ),
        )
    return _unresolvable(
        ctx, "could not settle a guideline set and document type that exist together"
    )


def _narrow(
    catalogue: dict[str, list[str]],
    requested_set: str | None,
    requested_type: str | None,
) -> dict[str, list[str]]:
    """The catalogue reduced to what the request left open.

    Whatever the request named is not up for decision, so it is removed from
    the choice rather than merely asked for in prose: a named set leaves one
    set, and a named type leaves that type on every set that can write it.
    Empty means nothing configured can satisfy what was named.
    """
    sets = {requested_set: catalogue[requested_set]} if requested_set else catalogue
    if requested_type is None:
        return dict(sets)
    return {
        name: [requested_type]
        for name, types in sets.items()
        if requested_type in types
    }


def _unresolvable(ctx: _RunContext, reason: str) -> None:
    """Record why the run has nothing to write against, and give up on it."""
    ctx.unresolved = reason
    ctx.trace.notes.append(reason)
    return None


def _resolution_turn(
    ctx: _RunContext, messages: list[dict[str, Any]], tool: dict
) -> tuple[str, str, str, str] | None:
    """One forced `choose_guideline_set` call, as (tool_use_id, set, type,
    reason). None on an API or shape failure, with the reason noted."""
    trace: TraceBuilder = ctx.trace
    try:
        with trace.span("model_turn:resolve"):
            resp = _model_turn(ctx, messages, force_tool=RESOLVE_TOOL, tools=[tool])
    except Exception as exc:  # noqa: BLE001 — terminal API error after backoff
        return _unresolvable(ctx, f"guideline resolution failed: {exc}")
    trace.model_turns += 1
    trace.add_usage(getattr(resp, "usage", None))
    messages.append({"role": "assistant", "content": resp.content})

    tool_use = _first_tool_use(resp)
    if tool_use is None or tool_use.name != RESOLVE_TOOL:
        return _unresolvable(ctx, "the run did not choose a guideline set")
    data = dict(tool_use.input or {})
    chosen_set = str(data.get("guideline_set") or "").strip()
    chosen_type = str(data.get("document_type") or "").strip()
    if not chosen_set or not chosen_type:
        return _unresolvable(ctx, "the run's guideline choice was incomplete")
    return tool_use.id, chosen_set, chosen_type, str(data.get("reason") or "").strip()


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _recon(ctx: _RunContext) -> Any:
    """The opening wide map of the request. Counts toward the op cap, and its
    ids count as retrieved — the map is how a run finds what to hydrate."""
    trace: TraceBuilder = ctx.trace
    args = {"query": ctx.prompt, "k": ctx.config.recon_k}
    if not _substrate_has(ctx.substrate, "survey_statements"):
        trace.notes.append("recon skipped: survey_statements not available")
        return []
    try:
        with trace.span("recon"):
            recon = ctx.substrate.call("survey_statements", args)
        trace.record_tool_call(
            "survey_statements", args, recon, ok=True, counts_as_op=True
        )
        ctx.successful_reads += 1
        _note_retrieved(ctx, recon, prompts.format_recon(recon))
        return recon
    except SubstrateError as exc:
        trace.record_tool_call(
            "survey_statements", args, None, ok=False, counts_as_op=True, error=str(exc)
        )
        trace.notes.append(f"recon failed: {exc}")
        return []


def _dispatch_read(
    name: str, arguments: dict[str, Any], tool_use_id: str, ctx: _RunContext
) -> None:
    """Execute one substrate read and feed its result back.

    Only a successful read adds to `retrieved_ids`, which is what the emit
    gate checks citations against: absence and failure are reported to the
    model, never fabricated into an empty success it could then cite.
    """
    trace: TraceBuilder = ctx.trace
    if not _substrate_has(ctx.substrate, name):
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error="unknown tool"
        )
        _append_tool_error(ctx.messages, tool_use_id, f"unknown tool: {name}")
        return
    try:
        with trace.span(f"tool:{name}"):
            result = ctx.substrate.call(name, arguments)
    except SubstrateError as exc:
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error=str(exc)
        )
        _append_tool_result(
            ctx.messages, tool_use_id, _serialize({"error": str(exc)}), error=True
        )
        return
    trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
    ctx.successful_reads += 1
    sent = _serialize(result)
    _note_retrieved(ctx, result, sent)
    _append_tool_result(ctx.messages, tool_use_id, sent, error=False)


def _note_retrieved(ctx: _RunContext, result: Any, sent: str) -> None:
    """Record which statements this read actually put in front of the model.

    Two filters, and both matter. The structural one (`collect_statement_ids`)
    takes only `id` keys, so a link's `to_id` — a pointer to something not
    fetched — is not counted as read. The textual one intersects with what was
    actually SENT, because a large result is truncated on its way into the
    conversation: an id past the cut never reached the model, and treating it
    as retrieved would let a citation the model could only have guessed pass
    the emit gate.
    """
    seen: set[str] = set()
    collect_statement_ids(result, seen)
    ctx.retrieved_ids.update(i for i in seen if i in sent)


def _handle_gap(tool_use: Any, ctx: _RunContext) -> None:
    """File one knowledge gap. Never terminal, never fatal: a gap store that
    refuses is reported back to the model and the run keeps writing."""
    trace: TraceBuilder = ctx.trace
    arguments = dict(tool_use.input or {})
    text = str(arguments.get("text") or "").strip()
    if not text:
        trace.record_tool_call(
            GAP_TOOL, arguments, None, ok=False, counts_as_op=False, error="empty text"
        )
        _append_tool_error(
            ctx.messages, tool_use.id, "report_knowledge_gap needs a non-empty text."
        )
        return
    try:
        with trace.span(f"tool:{GAP_TOOL}"):
            result = ctx.report_gap(text)
    except Exception as exc:  # noqa: BLE001 — a gap store failure is not fatal
        trace.record_tool_call(
            GAP_TOOL, arguments, None, ok=False, counts_as_op=True, error=str(exc)
        )
        _append_tool_result(
            ctx.messages, tool_use.id, _serialize({"error": str(exc)}), error=True
        )
        return
    trace.record_tool_call(GAP_TOOL, arguments, result, ok=True, counts_as_op=True)
    gap_id = result.get("gap_id") if isinstance(result, dict) else None
    trace.reported_gaps.append(f"{gap_id or '(unknown id)'} :: {text}")
    ctx.gaps.append(text)
    _append_tool_result(ctx.messages, tool_use.id, _serialize(result), error=False)


def _handle_emit(
    tool_use: Any, ctx: _RunContext, *, degraded: bool
) -> DocgenResult | None:
    """Terminal: `emit_document`, gated on grounding. Returns a result to
    finish, or None to keep looping after a re-prompt."""
    trace: TraceBuilder = ctx.trace
    try:
        title, body, ids, gaps = parse_emit_input(dict(tool_use.input or {}))
    except ValueError as exc:
        if ctx.malformed_retries < _MAX_MALFORMED_RETRIES and not degraded:
            ctx.malformed_retries += 1
            _append_tool_error(
                ctx.messages, tool_use.id, prompts.malformed_retry_message(str(exc))
            )
            return None
        trace.notes.append(f"emit_document malformed: {exc}")
        return _nothing(ctx, f"the emitted document was malformed: {exc}")

    problem = _emit_problem(title, body, ids, ctx.retrieved_ids)
    if problem is not None:
        trace.refused_emits.append(problem)
        if ctx.emit_blocks < _MAX_EMIT_BLOCKS and not degraded:
            ctx.emit_blocks += 1
            _append_tool_error(
                ctx.messages, tool_use.id, prompts.emit_block_message(problem)
            )
            return None
        return _nothing(ctx, f"the document was not recorded: {problem}")

    trace.declared_gaps = list(gaps)
    if degraded:
        trace.degraded = True
    return DocumentWritten(
        slug=_slug(title),
        title=title,
        body=body,
        statement_ids=ids,
        guideline_set=ctx.guideline_set,
        document_type=ctx.document_type,
        gaps=_merged_gaps(ctx, gaps),
        trace=_build_trace(ctx, "document_written", cited=ids),
    )


def _emit_problem(
    title: str, body: str, ids: list[str], retrieved: set[str]
) -> str | None:
    """Why this document may not be recorded, or None.

    Two of these are the issue's contract — a document resting on no
    statement ids is refused, and a claim the substrate did not supply is a
    gap to file rather than prose to invent. The id check is the structural
    half of the second: a run can only cite what it actually retrieved, so
    "I read this somewhere" cannot become provenance.
    """
    if not title:
        return "the title is blank"
    if not _slug(title):
        return "the title has no letters or digits to form a page identity from"
    if not body.strip():
        return "the body is blank"
    if not ids:
        return (
            "it carried no statement_ids. A document that rests on nothing is "
            "not recorded — cite the statements each section came from"
        )
    unknown = [i for i in ids if i not in retrieved]
    if unknown:
        shown = ", ".join(sorted(unknown)[:_MAX_NAMED_IDS])
        return (
            "it cited statement ids this run never retrieved: "
            f"{shown}. Retrieve them with get_statements, or cite only what "
            "you read"
        )
    return None


def _forced_finalize(reason: str, ctx: _RunContext) -> DocgenResult:
    """Last resort: force one `emit_document`, still gated. A budget cap is a
    reason to stop gathering, never a reason to record a groundless page."""
    trace: TraceBuilder = ctx.trace
    trace.forced_finalize = reason
    trace.degraded = True
    ctx.messages.append(
        {"role": "user", "content": prompts.forced_finalize_message(reason)}
    )
    try:
        with trace.span("model_turn:forced"):
            resp = _model_turn(ctx, ctx.messages, force_tool=EMIT_TOOL)
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        tool_use = _first_tool_use(resp)
        if tool_use is not None and tool_use.name == EMIT_TOOL:
            result = _handle_emit(tool_use, ctx, degraded=True)
            if result is not None:
                return result
        else:
            trace.notes.append("forced finalize: model did not emit a document")
    except Exception as exc:  # noqa: BLE001
        trace.notes.append(f"forced finalize failed: {exc}")
    return _nothing(
        ctx, f"no document could be grounded before the run ended ({reason})"
    )


# --------------------------------------------------------------------------- #
# Outcome builders
# --------------------------------------------------------------------------- #


def _nothing(ctx: _RunContext, reason: str) -> NothingWritten:
    return NothingWritten(
        reason=reason,
        guideline_set=ctx.guideline_set,
        document_type=ctx.document_type,
        gaps=list(ctx.gaps),
        trace=_build_trace(ctx, "nothing_written", cited=[]),
    )


def _merged_gaps(ctx: _RunContext, declared: list[str]) -> list[str]:
    """Everything the run says the substrate could not supply: what it filed
    as it went, plus anything the emit declared that it did not file."""
    out = list(ctx.gaps)
    out.extend(g for g in declared if g not in out)
    return out


def _build_trace(ctx: _RunContext, outcome: str, *, cited: list[str]) -> dict:
    trace: TraceBuilder = ctx.trace
    config: DocgenConfig = ctx.config
    latency_ms = (time.monotonic() - ctx.start) * 1000.0
    record = trace.build(
        outcome=outcome,
        latency_ms=latency_ms,
        grounding={
            "successful_reads": ctx.successful_reads,
            "retrieved_ids": len(ctx.retrieved_ids),
            "cited_ids": len(cited),
            "gaps_filed": len(trace.reported_gaps),
        },
        input_per_mtok=config.input_per_mtok,
        output_per_mtok=config.output_per_mtok,
    )
    tracing.emit_trace(
        trace.spans,
        kind="docgen",
        label=ctx.prompt[:40],
        record=record,
        trace_dir=config.trace_dir,
    )
    return record


# --------------------------------------------------------------------------- #
# Slug
# --------------------------------------------------------------------------- #


def _slug(title: str) -> str:
    """The page's stable identity, derived from its title.

    Derived rather than chosen because the store keys a document on it: two
    runs told to document the same topic should land on the same page, and
    that is likelier to survive if it follows from the title than if a model
    has to reinvent a naming convention. `\\w` keeps non-ASCII letters, so a
    non-English title still yields an identity rather than an empty string.
    """
    cleaned = re.sub(r"[^\w]+", "-", title.lower(), flags=re.UNICODE)
    return cleaned.replace("_", "-").strip("-")[:_MAX_SLUG_CHARS].strip("-")


# --------------------------------------------------------------------------- #
# Model call + message helpers
# --------------------------------------------------------------------------- #


def _model_turn(
    ctx: _RunContext,
    messages: list[dict[str, Any]],
    *,
    force_tool: str | None,
    tools: list[dict] | None = None,
) -> Any:
    config: DocgenConfig = ctx.config
    client = ctx.client
    if hasattr(client, "with_options"):
        client = client.with_options(
            timeout=config.request_timeout_s, max_retries=config.max_retries
        )
    kwargs: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": messages,
        "tools": tools if tools is not None else ctx.tools,
    }
    if ctx.system_prompt:
        kwargs["system"] = ctx.system_prompt
    if force_tool:
        # Forcing a specific tool is incompatible with extended thinking, so
        # thinking stays off on a forced turn — and the thinking blocks the
        # adaptive turns left in history are stripped, which a
        # thinking-disabled request should not carry.
        kwargs["messages"] = _strip_thinking(messages)
        kwargs["tool_choice"] = {
            "type": "tool",
            "name": force_tool,
            "disable_parallel_tool_use": True,
        }
    else:
        kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        if config.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
    return client.messages.create(**kwargs)


def _append_tool_result(
    messages: list[dict[str, Any]], tool_use_id: str, content: str, *, error: bool
) -> None:
    """Answer one tool_use. Takes already-serialized text rather than the raw
    result, because the caller needs to know exactly what was sent — see
    `_note_retrieved`."""
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": error,
                }
            ],
        }
    )
