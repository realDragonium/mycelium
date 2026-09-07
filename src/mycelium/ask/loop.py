"""The `ask` reasoning loop.

One Sonnet context drives retrieval over the substrate read primitives; this
module is the deterministic harness around it — recon, the tool-use loop, the
anti-premature-closure floor, the op-cap / wall-clock ceilings, and graceful
degradation. The model reasons; this code fetches, counts, bounds, and records.

Core-at-the-center: `_execute` depends only on a client-like object (anything
with `.messages.create(...)`) and a `SubstrateReader`. Both are injectable, so
the loop is exercisable with plain fakes — no server, no network. The framework
seam (`run_ask`) wires the shared model transport + in-process substrate and
writes the trace.

The boundary-facing spine (client construction, the budget gate, thinking
stripping, tool-result serialization, …) is shared with `ingest`/`research` via
`..agentloop`; what stays here is ask-specific: recon, parallel tool use, the
two terminals, and the semantic-adjacency floor.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import JsonValue, TypeAdapter

from .. import ai, ai_prompts, tracing
from ..agentloop import (
    append_tool_error as _append_tool_error,
)
from ..agentloop import (
    check_budget,
)
from ..agentloop import (
    first_tool_use as _first_tool_use,
)
from ..agentloop import (
    serialize as _serialize,
)
from ..agentloop import (
    substrate_has as _substrate_has,
)
from . import prompts
from .config import AskConfig
from .events import AnswerDeltas, AskCancelled, AskEvent, AskStream, current_stream
from .evidence import Evidence
from .schema import Answered, AskResult, Interpretation, NeedsClarification
from .substrate import InProcessSubstrate, SubstrateError, SubstrateReader
from .tools import (
    CLARIFY_TOOL,
    SUBMIT_TOOL,
    TERMINAL_TOOLS,
    AnswerInput,
    ClarificationInput,
    answered_from_tool_input,
    build_tools,
    clarification_from_tool_input,
)
from .trace import TraceBuilder

#: Searches that count as semantic-adjacency moves for the floor check.
_SEARCH_TOOLS = frozenset({"search_statements", "survey_statements"})

#: Safety stops so a stubborn model can't spin forever without consuming ops.
_MAX_FLOOR_BLOCKS = 3
_MAX_CLARIFY_RETRIES = 1
_MAX_MALFORMED_RETRIES = 1
#: Hard ceiling on model turns, well above any real run (op cap bounds reads).
_TURN_HEADROOM = 12


def run_ask(
    question: str,
    *,
    client: ai.ClaudeClient | httpx.Client | None = None,
    substrate: SubstrateReader | None = None,
    config: AskConfig | None = None,
    stream: AskStream | None = None,
) -> AskResult:
    """Resolve `question` against the substrate. Returns `Answered` or
    `NeedsClarification` — never raises for retrieval/closure reasons.

    `client` / `substrate` / `config` are injectable for tests; in production
    they default to the shared model transport, the in-process substrate, and
    effective saved configuration.
    """
    config = config or AskConfig.from_env()
    if substrate is None:
        substrate = InProcessSubstrate()

    stream = stream or current_stream.get() or AskStream()
    stream.check()
    token = current_stream.set(stream)
    try:
        with tracing.profile_to_html("ask", question):
            result = _execute(question, client, substrate, config, stream)
    finally:
        current_stream.reset(token)
    stream.check()
    stream.timings.setdefault(
        "completion_ms", round((time.monotonic() - stream.started) * 1000, 2)
    )
    result.trace["stream_timing_ms"] = dict(stream.timings)
    stream.send(
        AskEvent(
            type="complete",
            result=TypeAdapter(dict[str, JsonValue]).validate_python(
                result.model_dump()
            ),
        )
    )

    if config.trace_log_path:
        from .trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


@dataclass
class _RunContext:
    question: str
    system_prompt: str
    client: ai.ClaudeClient | httpx.Client | None
    substrate: SubstrateReader
    config: AskConfig
    tools: list[dict]
    messages: list[dict[str, object]]
    trace: TraceBuilder
    start: float
    ops_after_recon: list[ReadCheck]
    evidence: Evidence
    targeted_ids: set[str]
    stream: AskStream
    deltas: AnswerDeltas
    nudged: bool = False
    floor_blocks: int = 0
    clarify_retries: int = 0
    malformed_retries: int = 0


@dataclass(frozen=True)
class ReadCheck:
    name: str
    adjacency: bool = False


def _execute(
    question: str,
    client: ai.ClaudeClient | httpx.Client | None,
    substrate: SubstrateReader,
    config: AskConfig,
    stream: AskStream,
) -> AskResult:
    start = time.monotonic()
    trace = TraceBuilder(
        question=question,
        model=config.model,
        provider=config.provider,
        op_cap=config.op_cap,
        wall_clock_s=config.wall_clock_s,
    )
    instructions = ai_prompts.resolve("ask")
    trace.prompts.append(instructions.reference())
    tools = build_tools(substrate.tool_specs(), enforce_floor=config.enforce_floor)
    evidence = Evidence()
    ctx = _RunContext(
        question=question,
        system_prompt=prompts.build_system_prompt(instructions.text),
        evidence=evidence,
        targeted_ids=set(),
        stream=stream,
        deltas=AnswerDeltas(stream, allowed=False),
        client=client,
        substrate=substrate,
        config=config,
        tools=tools,
        messages=[],
        trace=trace,
        start=start,
        ops_after_recon=[],
        nudged=False,
        floor_blocks=0,
        clarify_retries=0,
        malformed_retries=0,
    )

    try:
        _prepare(ctx)
        return _drive(ctx)
    except Exception as exc:
        outcome = "cancelled" if isinstance(exc, AskCancelled) else "error"
        trace.notes.append(f"run ended: {outcome}")
        record = _build_trace(ctx, outcome)
        if config.trace_log_path:
            from .trace import write_record

            write_record(config.trace_log_path, record)
        raise


def _prepare(ctx: _RunContext) -> None:
    ctx.stream.progress("retrieval", "Surveying statements relevant to the question.")
    recon = _recon(ctx.question, ctx.substrate, ctx.config, ctx.trace)
    ctx.stream.check()
    formatted = prompts.format_recon(recon)
    # Only the compact, bounded recon reaches the model and can support citations.
    supplied = (
        ctx.evidence.supply(json.loads(formatted))
        if formatted.startswith("[")
        else formatted
    )
    ctx.messages.append(
        {
            "role": "user",
            "content": prompts.initial_user_message(
                ctx.question, supplied, quick=not ctx.config.enforce_floor
            ),
        }
    )


def _drive(ctx: _RunContext) -> AskResult:
    stream, trace, config = ctx.stream, ctx.trace, ctx.config
    client, messages, tools = ctx.client, ctx.messages, ctx.tools
    start = ctx.start
    max_turns = config.op_cap + _TURN_HEADROOM
    while True:
        # Budget gates — forced finalize bypasses the floor and degrades.
        stream.check()
        reason = check_budget(trace, config, start, max_turns)
        if reason:
            return _forced_finalize(reason, ctx)

        floor = _floor_state(ctx)
        stream.progress(
            "evidence_check",
            f"Completed {floor['targeted_retrievals']} targeted retrievals and {floor['adjacency_research']} grounded adjacency searches.",
        )
        ctx.deltas = AnswerDeltas(
            stream, allowed=not config.enforce_floor or floor["satisfied"]
        )
        try:
            with trace.span("model_turn"):
                resp = _model_turn(
                    client,
                    config,
                    messages,
                    tools,
                    force=False,
                    deltas=ctx.deltas,
                    system=ctx.system_prompt,
                )
        except AskCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — terminal API error after SDK backoff
            ctx.deltas.reset()
            trace.notes.append(f"model error: {exc}")
            return _forced_finalize("api_error", ctx)
        stream.check()
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = _tool_uses(resp)
        if not tool_uses:
            # Text only / end_turn with no tool call.
            if not ctx.nudged:
                ctx.nudged = True
                messages.append({"role": "user", "content": prompts.NO_TERMINAL_NUDGE})
                continue
            return _forced_finalize("no_terminal", ctx)

        # The model is calling a tool again — reset the no-terminal nudge so a
        # single stray text turn earlier doesn't doom a later one. The nudge
        # budget is per consecutive-text-streak, not per session.
        ctx.nudged = False

        # Execute every substrate read in this turn FIRST (see `_run_reads`), so
        # each tool_use gets its tool_result before the next turn even when a
        # sibling terminal then finishes or degrades the loop.
        _run_reads(tool_uses, ctx)

        # Synthesis must consume earlier results, not sibling reads from this turn.
        tool_use = next((t for t in tool_uses if t.name in TERMINAL_TOOLS), None)
        if tool_use is None:
            continue
        if len(tool_uses) != 1:
            ctx.deltas.reset()
            for terminal in tool_uses:
                if terminal.name in TERMINAL_TOOLS:
                    _append_tool_error(
                        messages,
                        terminal.id,
                        "Finish in a separate turn after reading the tool results; call exactly one terminal.",
                    )
            continue
        if tool_use.name == CLARIFY_TOOL:
            ctx.deltas.reset()
            result = _handle_clarify(tool_use, ctx)
        else:
            result = _handle_submit(tool_use, ctx)
        if result is not None:
            return result


def _run_reads(tool_uses: list[ai.ToolUse], ctx: _RunContext) -> None:
    read_results: list[dict[str, Any]] = []
    previous_targeted = bool(ctx.ops_after_recon)
    available_ids = set(ctx.targeted_ids)
    for tu in tool_uses:
        if tu.name in TERMINAL_TOOLS:
            continue
        ctx.stream.check()
        arguments = dict(tu.input or {})
        sources = (
            arguments.pop("adjacency_sources", []) if tu.name in _SEARCH_TOOLS else []
        )
        try:
            source_ids = ctx.evidence.expand(
                TypeAdapter(list[str]).validate_python(sources, strict=True)
            )
            if source_ids and not set(source_ids) <= available_ids:
                raise ValueError(
                    "Adjacency sources must have been supplied by a completed targeted retrieval in an earlier turn."
                )
        except ValueError as exc:
            ctx.trace.evidence_checks.append(
                {
                    "tool": tu.name,
                    "turn": ctx.trace.model_turns,
                    "sources": [],
                    "adjacency": False,
                    "ok": False,
                    "error": str(exc),
                }
            )
            read_results.append(_tool_result_block(tu.id, str(exc), is_error=True))
            continue
        if check_budget(
            ctx.trace, ctx.config, ctx.start, ctx.config.op_cap + _TURN_HEADROOM
        ):
            read_results.append(
                _tool_result_block(tu.id, "Retrieval budget exhausted", is_error=True)
            )
            continue
        ctx.stream.progress("retrieval", f"Retrieving evidence with {tu.name}.")
        ok = _dispatch_read(
            tu.name,
            arguments,
            tu.id,
            ctx.substrate,
            ctx.trace,
            read_results,
            ctx.evidence,
        )
        adjacency = False
        if ok:
            if tu.name in {
                "search_statements",
                "survey_statements",
                "get_statements",
                "grep_statements",
                "get_entity",
                "retrieve_context",
                "find_statement_connections",
            }:
                adjacency = bool(
                    tu.name in _SEARCH_TOOLS
                    and previous_targeted
                    and source_ids
                    and set(source_ids) <= available_ids
                    and arguments.get("query", "").strip().casefold()
                    != ctx.question.strip().casefold()
                )
                ctx.ops_after_recon.append(ReadCheck(tu.name, adjacency))
                ctx.targeted_ids.update(ctx.evidence.last_ids)
        ctx.trace.evidence_checks.append(
            {
                "tool": tu.name,
                "turn": ctx.trace.model_turns,
                "sources": source_ids,
                "adjacency": adjacency,
                "ok": ok,
            }
        )
        ctx.stream.progress(
            "retrieval",
            f"{tu.name} {'completed' if ok else 'failed'}. {len(ctx.evidence.ids)} statements supplied so far.",
        )
        ctx.stream.check()
    if read_results:
        ctx.messages.append({"role": "user", "content": read_results})


def _handle_clarify(tool_use: ai.ToolUse, ctx: _RunContext) -> AskResult | None:
    """Terminal: request_clarification (allowed any time after recon). Returns a
    result to finish, or None to keep looping after a re-prompt."""
    tool_input = dict(tool_use.input or {})
    try:
        ClarificationInput.model_validate(tool_input)
    except ValueError:
        if ctx.clarify_retries < _MAX_CLARIFY_RETRIES:
            ctx.clarify_retries += 1
            _append_tool_error(
                ctx.messages,
                tool_use.id,
                "request_clarification needs a non-empty question and at least two genuinely distinct "
                "candidates, each naming what it would pull. If it isn't "
                "genuinely ambiguous, retrieve and submit_answer instead.",
            )
            return None
        # Retry spent and still under-specified: never emit a broken
        # clarification (the contract requires >=2 candidates). Degrade
        # to a forced answer rather than handing back a useless one.
        _append_tool_error(
            ctx.messages,
            tool_use.id,
            "Clarification still under-specified; finalizing with what has "
            "been gathered.",
        )
        return _forced_finalize("clarify_stuck", ctx)
    return _finish_clarification(tool_input, ctx)


def _handle_submit(tool_use: ai.ToolUse, ctx: _RunContext) -> AskResult | None:
    """Terminal: submit_answer (gated by the floor). Returns a result to finish,
    or None to keep looping after a re-prompt."""
    tool_input = dict(tool_use.input or {})
    floor = _floor_state(ctx)
    # `quick` depth (enforce_floor off) skips the gate entirely: accept the first
    # well-formed answer instead of forcing the re-search dance.
    if ctx.config.enforce_floor and not floor["satisfied"]:
        ctx.deltas.reset()
        if ctx.floor_blocks < _MAX_FLOOR_BLOCKS:
            ctx.floor_blocks += 1
            detail = prompts.floor_block_message(_floor_detail(floor))
            _append_tool_error(ctx.messages, tool_use.id, detail)
            return None
        # Stuck below the floor: never accept a floorless answer. Respond
        # to the pending tool_use, then degrade via a forced finalize.
        _append_tool_error(
            ctx.messages,
            tool_use.id,
            "Floor still unmet after repeated attempts; finalizing with "
            "what has been gathered.",
        )
        return _forced_finalize("floor_stuck", ctx)
    try:
        return _finish_answer(tool_input, ctx, degraded=False)
    except AskCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 — malformed submit input
        ctx.deltas.reset()
        if ctx.malformed_retries < _MAX_MALFORMED_RETRIES:
            ctx.malformed_retries += 1
            _append_tool_error(
                ctx.messages, tool_use.id, prompts.malformed_retry_message(str(exc))
            )
            return None
        ctx.trace.notes.append(f"submit_answer malformed twice: {exc}")
        return _fallback_answer(
            ctx,
            gap="answer formatting failed — returned a low-confidence partial",
        )


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _recon(
    question: str, substrate: SubstrateReader, config: AskConfig, trace: TraceBuilder
) -> Any:
    args = {"query": question, "k": config.recon_k}
    try:
        with trace.span("recon"):
            recon = substrate.call("survey_statements", args)
        trace.record_tool_call(
            "survey_statements", args, recon, ok=True, counts_as_op=True
        )
        return recon
    except SubstrateError as exc:
        trace.record_tool_call(
            "survey_statements", args, None, ok=False, counts_as_op=True, error=str(exc)
        )
        trace.notes.append(f"recon failed: {exc}")
        return []


def _dispatch_read(
    name: str,
    arguments: dict[str, Any],
    tool_use_id: str,
    substrate: SubstrateReader,
    trace: TraceBuilder,
    result_blocks: list[dict[str, Any]],
    evidence: Evidence,
) -> bool:
    """Execute one read; return True only if it succeeded (so the caller knows
    whether it counts toward the floor).

    The tool_result block is appended to `result_blocks`, not to `messages`
    directly: with parallel tool use a turn may hold several reads, and the API
    wants all of one turn's tool_results in the single following user message —
    so the caller collects the blocks and appends them once."""
    if not _substrate_has(substrate, name):
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error="unknown tool"
        )
        result_blocks.append(
            _tool_result_block(tool_use_id, f"unknown tool: {name}", is_error=True)
        )
        return False
    try:
        with trace.span(f"tool:{name}"):
            result = substrate.call(name, arguments)
        trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
        sent = evidence.supply(result)
        if name == "retrieve_context" and isinstance(result, dict):
            trace.combined_reads.append(
                TypeAdapter(JsonValue).validate_python(result.get("reads", []))
            )
        result_blocks.append(_tool_result_block(tool_use_id, sent, is_error=False))
        return True
    except SubstrateError as exc:
        # Absence/failure is reported, never fabricated into an empty success.
        trace.record_tool_call(
            name, arguments, None, ok=False, counts_as_op=True, error=str(exc)
        )
        result_blocks.append(
            _tool_result_block(
                tool_use_id, _serialize({"error": str(exc)}), is_error=True
            )
        )
        return False


def _forced_finalize(reason: str, ctx: _RunContext) -> Answered:
    """Force one low-confidence submit, or return a synthetic fallback.

    Cancellation still propagates; it never triggers another model call.
    """
    trace: TraceBuilder = ctx.trace
    ctx.stream.check()
    ctx.deltas.reset()
    trace.forced_finalize = reason
    trace.degraded = True
    ctx.stream.progress(
        "evidence_check", f"Finalizing with limited confidence: {reason}."
    )
    ctx.deltas = AnswerDeltas(
        ctx.stream,
        allowed=not ctx.config.enforce_floor or _floor_state(ctx)["satisfied"],
    )
    ctx.messages.append(
        {"role": "user", "content": prompts.forced_finalize_message(reason)}
    )
    try:
        with trace.span("model_turn:forced"):
            resp = _model_turn(
                ctx.client,
                ctx.config,
                ctx.messages,
                ctx.tools,
                force=True,
                deltas=ctx.deltas,
                system=ctx.system_prompt,
            )
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        tool_use = _first_tool_use(resp)
        if tool_use is not None and tool_use.name == SUBMIT_TOOL:
            return _finish_answer(dict(tool_use.input or {}), ctx, degraded=True)
        trace.notes.append("forced finalize: model did not emit submit_answer")
    except AskCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        ctx.deltas.reset()
        trace.notes.append(f"forced finalize failed: {exc}")
    return _fallback_answer(
        ctx, gap=f"forced finalize ({reason}) — core left unresolved"
    )


# --------------------------------------------------------------------------- #
# Finalizers
# --------------------------------------------------------------------------- #


def _finish_answer(
    tool_input: dict,
    ctx: _RunContext,
    *,
    degraded: bool,
) -> Answered:
    trace: TraceBuilder = ctx.trace
    parsed = AnswerInput.model_validate(tool_input)
    expanded = ctx.evidence.expand(parsed.provenance)
    tool_input = {**parsed.model_dump(), "provenance": expanded}
    if ctx.evidence.omitted:
        tool_input["gaps"] = [
            *parsed.gaps,
            "Retrieved context exceeded configured limits; some evidence or relationships were omitted.",
        ]
        if parsed.confidence == "high":
            tool_input["confidence"] = "medium"
    if not expanded:
        tool_input["confidence"] = "low"
        tool_input["gaps"] = [*tool_input["gaps"], "No statement evidence was cited."]
    trace.sub_question_ledger = []
    trace.adjacency_note = f"{_floor_state(ctx)['adjacency_research']} grounded adjacency searches completed"
    if ctx.deltas.text and ctx.deltas.text != parsed.answer:
        ctx.deltas.reset()
    if degraded:
        tool_input["gaps"] = [
            *tool_input["gaps"],
            f"Finalization was forced ({trace.forced_finalize}); evidence checks or answer completion may be incomplete.",
        ]
        trace.degraded = True
        # A degraded finalize aborted the normal loop — the answer cannot be
        # high/medium confidence (acceptance: "degrade to a low-confidence
        # partial"). Enforce it in code, not just in the prompt.
        if tool_input.get("confidence") != "low":
            tool_input = dict(tool_input)
            tool_input["confidence"] = "low"
            trace.notes.append("confidence floored to low on degraded finalize")
    trace_dict = _build_trace(ctx, "answered")
    return answered_from_tool_input(tool_input, trace_dict)


def _finish_clarification(tool_input: dict, ctx: _RunContext) -> NeedsClarification:
    trace_dict = _build_trace(ctx, "needs_clarification")
    return clarification_from_tool_input(tool_input, trace_dict)


def _fallback_answer(ctx: _RunContext, *, gap: str) -> Answered:
    trace: TraceBuilder = ctx.trace
    trace.degraded = True
    trace_dict = _build_trace(ctx, "answered")
    return Answered(
        answer=(
            "The substrate did not yield enough to resolve this with confidence. "
            "See gaps for what remained unresolved."
        ),
        confidence="low",
        interpretation=Interpretation(
            as_asked=ctx.question,
            resolved_to=ctx.question,
            reframed=False,
            reframe_reason=None,
        ),
        gaps=[gap, "core sub-questions were unresolved when the call ended"]
        + (
            ["Retrieved context was truncated; some evidence was omitted."]
            if ctx.evidence.omitted
            else []
        )
        + (["No statement evidence was supplied."] if not ctx.evidence.ids else []),
        provenance=sorted(ctx.evidence.ids),
        trace=trace_dict,
    )


def _build_trace(ctx: _RunContext, outcome: str) -> dict:
    trace: TraceBuilder = ctx.trace
    config: AskConfig = ctx.config
    latency_ms = (time.monotonic() - ctx.start) * 1000.0
    record = trace.build(
        outcome=outcome,
        latency_ms=latency_ms,
        floor=_floor_state(ctx),
        input_per_mtok=config.input_per_mtok,
        output_per_mtok=config.output_per_mtok,
    )
    record["evidence_refs"] = dict(ctx.evidence.by_ref)
    record["supplied_context_chars"] = ctx.evidence.supplied_chars
    if outcome in {"answered", "needs_clarification"}:
        ctx.stream.timings["completion_ms"] = round(
            (time.monotonic() - ctx.stream.started) * 1000, 2
        )
    record["stream_timing_ms"] = dict(ctx.stream.timings)
    tracing.emit_trace(
        trace.spans,
        kind="ask",
        label=trace.question,
        record=record,
        trace_dir=config.trace_dir,
    )
    return record


# --------------------------------------------------------------------------- #
# Floor
# --------------------------------------------------------------------------- #


def _floor_state(ctx: _RunContext) -> dict:
    targeted = len(ctx.ops_after_recon)
    adjacency = sum(check.adjacency for check in ctx.ops_after_recon)
    recon_ok = bool(ctx.trace.tool_calls and ctx.trace.tool_calls[0].ok)
    return {
        "recon": recon_ok,
        "targeted_retrievals": targeted,
        "adjacency_research": adjacency,
        "satisfied": recon_ok and targeted >= 1 and adjacency >= 1,
    }


def _floor_detail(floor: dict) -> str:
    return (
        f"So far: {floor['targeted_retrievals']} targeted retrieval(s) and "
        f"{floor['adjacency_research']} adjacency re-search(es) after recon."
    )


# --------------------------------------------------------------------------- #
# Model call + message helpers
# --------------------------------------------------------------------------- #


def _model_turn(
    client: ai.ClaudeClient | httpx.Client | None,
    config: AskConfig,
    messages: Sequence[Mapping[str, object]],
    tools: Sequence[Mapping[str, object]],
    *,
    force: bool,
    deltas: AnswerDeltas,
    system: str,
) -> ai.ModelResponse:
    return ai.turn(
        ai.ToolTask(
            system=system,
            messages=messages,
            tools=tools,
            force_tool=SUBMIT_TOOL if force else None,
            parallel_tools=not force,
            on_tool_delta=deltas.receive if deltas.stream.emit else None,
            check_cancel=deltas.stream.check,
        ),
        ai.ModelConfig(
            provider=config.provider,
            model=config.model,
            max_tokens=config.max_tokens,
            request_timeout_s=config.request_timeout_s,
            max_retries=config.max_retries,
            thinking=config.thinking,
            reasoning_effort=config.reasoning_effort,
            cache=config.cache,
        ),
        client=client,
    )


def _tool_uses(resp: ai.ModelResponse) -> list[ai.ToolUse]:
    return [block for block in resp.content if isinstance(block, ai.ToolUse)]


def _tool_result_block(
    tool_use_id: str, content: str, *, is_error: bool
) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }
