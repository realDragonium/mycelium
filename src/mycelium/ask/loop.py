"""The `ask` reasoning loop.

One Sonnet context drives retrieval over the substrate read primitives; this
module is the deterministic harness around it — recon, the tool-use loop, the
anti-premature-closure floor, the op-cap / wall-clock ceilings, and graceful
degradation. The model reasons; this code fetches, counts, bounds, and records.

Core-at-the-center: `_execute` depends only on a client-like object (anything
with `.messages.create(...)`) and a `SubstrateReader`. Both are injectable, so
the loop is exercisable with plain fakes — no server, no network. The framework
seam (`run_ask`) wires the real Anthropic client + in-process substrate and
writes the trace.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .. import tracing
from . import prompts
from .config import AskConfig
from .schema import Answered, AskResult, Interpretation, NeedsClarification
from .substrate import InProcessSubstrate, SubstrateError, SubstrateReader
from .tools import (
    CLARIFY_TOOL,
    SUBMIT_TOOL,
    TERMINAL_TOOLS,
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

#: Cap on a serialized tool_result fed back to the model.
_TOOL_RESULT_MAX_CHARS = 20000


def run_ask(
    question: str,
    *,
    client: Any | None = None,
    substrate: SubstrateReader | None = None,
    config: AskConfig | None = None,
) -> AskResult:
    """Resolve `question` against the substrate. Returns `Answered` or
    `NeedsClarification` — never raises for retrieval/closure reasons.

    `client` / `substrate` / `config` are injectable for tests; in production
    they default to the real Anthropic client, the in-process substrate, and
    env-derived config.
    """
    config = config or AskConfig.from_env()
    if substrate is None:
        substrate = InProcessSubstrate()
    if client is None:
        client = _default_client(config)

    with tracing.profile_to_html("ask", question):
        result = _execute(question, client, substrate, config)

    if config.trace_log_path:
        from .trace import write_record

        write_record(config.trace_log_path, result.trace)
    return result


def _default_client(config: AskConfig) -> Any:
    import anthropic  # local import: keeps the package importable without the key

    return anthropic.Anthropic(max_retries=config.max_retries)


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


def _execute(
    question: str,
    client: Any,
    substrate: SubstrateReader,
    config: AskConfig,
) -> AskResult:
    start = time.monotonic()
    trace = TraceBuilder(
        question=question,
        model=config.model,
        op_cap=config.op_cap,
        wall_clock_s=config.wall_clock_s,
    )
    tools = build_tools(substrate.tool_specs())
    collected_ids: set[str] = set()
    ops_after_recon: list[str] = []  # substrate read names after recon, for the floor

    # ---- Step 0: recon (counts toward the op cap) ----
    recon = _recon(question, substrate, config, trace)
    _collect_ids(recon, collected_ids)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompts.initial_user_message(question, recon)}
    ]

    nudged = False
    floor_blocks = 0
    clarify_retries = 0
    malformed_retries = 0
    max_turns = config.op_cap + _TURN_HEADROOM

    while True:
        # Budget gates — forced finalize bypasses the floor and degrades.
        if trace.op_count >= config.op_cap:
            return _forced_finalize(
                "op_cap", question, recon, collected_ids, client, config, tools,
                messages, trace, start, ops_after_recon,
            )
        if (time.monotonic() - start) > config.wall_clock_s:
            return _forced_finalize(
                "wall_clock", question, recon, collected_ids, client, config, tools,
                messages, trace, start, ops_after_recon,
            )
        if trace.model_turns >= max_turns:
            return _forced_finalize(
                "turn_limit", question, recon, collected_ids, client, config, tools,
                messages, trace, start, ops_after_recon,
            )

        try:
            with trace.span("model_turn"):
                resp = _model_turn(client, config, messages, tools, force=False)
        except Exception as exc:  # noqa: BLE001 — terminal API error after SDK backoff
            trace.notes.append(f"model error: {exc}")
            return _forced_finalize(
                "api_error", question, recon, collected_ids, client, config, tools,
                messages, trace, start, ops_after_recon,
            )
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = _tool_uses(resp)
        if not tool_uses:
            # Text only / end_turn with no tool call.
            if not nudged:
                nudged = True
                messages.append({"role": "user", "content": prompts.NO_TERMINAL_NUDGE})
                continue
            return _forced_finalize(
                "no_terminal", question, recon, collected_ids, client, config, tools,
                messages, trace, start, ops_after_recon,
            )

        # The model is calling a tool again — reset the no-terminal nudge so a
        # single stray text turn earlier doesn't doom a later one. The nudge
        # budget is per consecutive-text-streak, not per session.
        nudged = False

        # Execute every substrate read in this turn FIRST. With parallel tool use
        # a turn may carry several reads (and, rarely, a terminal alongside them);
        # the API needs a tool_result for each tool_use before the next turn, so
        # we answer the reads here whether or not a sibling terminal then finishes
        # or degrades the loop. All of this turn's read results go back in one
        # user message.
        read_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            if tu.name in TERMINAL_TOOLS:
                continue
            if _dispatch_read(
                tu.name, dict(tu.input or {}), tu.id, substrate, trace, read_results,
                collected_ids,
            ):
                ops_after_recon.append(tu.name)
        if read_results:
            messages.append({"role": "user", "content": read_results})

        # A terminal tool finishes (or degrades) the loop; with none, loop again
        # to keep retrieving. If the model emitted several, the first wins.
        tool_use = next((t for t in tool_uses if t.name in TERMINAL_TOOLS), None)
        if tool_use is None:
            continue
        name = tool_use.name
        tool_input = dict(tool_use.input or {})

        # ---- Terminal: request_clarification (allowed any time after recon) ----
        if name == CLARIFY_TOOL:
            candidates = tool_input.get("candidates") or []
            if len(candidates) < 2:
                if clarify_retries < _MAX_CLARIFY_RETRIES:
                    clarify_retries += 1
                    _append_tool_error(
                        messages,
                        tool_use.id,
                        "request_clarification needs at least two genuinely distinct "
                        "candidates, each naming what it would pull. If it isn't "
                        "genuinely ambiguous, retrieve and submit_answer instead.",
                    )
                    continue
                # Retry spent and still under-specified: never emit a broken
                # clarification (the contract requires >=2 candidates). Degrade
                # to a forced answer rather than handing back a useless one.
                _append_tool_error(
                    messages,
                    tool_use.id,
                    "Clarification still under-specified; finalizing with what has "
                    "been gathered.",
                )
                return _forced_finalize(
                    "clarify_stuck", question, recon, collected_ids, client, config,
                    tools, messages, trace, start, ops_after_recon,
                )
            return _finish_clarification(tool_input, trace, start, ops_after_recon, config)

        # ---- Terminal: submit_answer (gated by the floor) ----
        if name == SUBMIT_TOOL:
            floor = _floor_state(ops_after_recon)
            adjacency_note = (tool_input.get("adjacency_note") or "").strip()
            if not floor["satisfied"] or not adjacency_note:
                if floor_blocks < _MAX_FLOOR_BLOCKS:
                    floor_blocks += 1
                    if not floor["satisfied"]:
                        detail = prompts.floor_block_message(_floor_detail(floor))
                    else:
                        detail = (
                            "adjacency_note is empty — report what your concept-seeded "
                            "re-search surfaced, or 'nothing new'."
                        )
                    _append_tool_error(messages, tool_use.id, detail)
                    continue
                # Stuck below the floor: never accept a floorless answer. Respond
                # to the pending tool_use, then degrade via a forced finalize.
                _append_tool_error(
                    messages,
                    tool_use.id,
                    "Floor still unmet after repeated attempts; finalizing with "
                    "what has been gathered.",
                )
                return _forced_finalize(
                    "floor_stuck", question, recon, collected_ids, client, config,
                    tools, messages, trace, start, ops_after_recon,
                )
            try:
                return _finish_answer(
                    tool_input, trace, start, ops_after_recon, config, degraded=False
                )
            except Exception as exc:  # noqa: BLE001 — malformed submit input
                if malformed_retries < _MAX_MALFORMED_RETRIES:
                    malformed_retries += 1
                    _append_tool_error(
                        messages, tool_use.id, prompts.malformed_retry_message(str(exc))
                    )
                    continue
                trace.notes.append(f"submit_answer malformed twice: {exc}")
                return _fallback_answer(
                    question, collected_ids, trace, start, ops_after_recon, config,
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
        trace.record_tool_call("survey_statements", args, recon, ok=True, counts_as_op=True)
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
    collected_ids: set[str],
) -> bool:
    """Execute one read; return True only if it succeeded (so the caller knows
    whether it counts toward the floor).

    The tool_result block is appended to `result_blocks`, not to `messages`
    directly: with parallel tool use a turn may hold several reads, and the API
    wants all of one turn's tool_results in the single following user message —
    so the caller collects the blocks and appends them once."""
    if not _substrate_has(substrate, name):
        trace.record_tool_call(name, arguments, None, ok=False, counts_as_op=True,
                               error="unknown tool")
        result_blocks.append(_tool_result_block(tool_use_id, f"unknown tool: {name}",
                                                 is_error=True))
        return False
    try:
        with trace.span(f"tool:{name}"):
            result = substrate.call(name, arguments)
        trace.record_tool_call(name, arguments, result, ok=True, counts_as_op=True)
        _collect_ids(result, collected_ids)
        result_blocks.append(
            _tool_result_block(tool_use_id, _serialize(result), is_error=False)
        )
        return True
    except SubstrateError as exc:
        # Absence/failure is reported, never fabricated into an empty success.
        trace.record_tool_call(name, arguments, None, ok=False, counts_as_op=True,
                               error=str(exc))
        result_blocks.append(
            _tool_result_block(tool_use_id, _serialize({"error": str(exc)}),
                               is_error=True)
        )
        return False


def _forced_finalize(
    reason: str,
    question: str,
    recon: Any,
    collected_ids: set[str],
    client: Any,
    config: AskConfig,
    tools: list[dict],
    messages: list[dict[str, Any]],
    trace: TraceBuilder,
    start: float,
    ops_after_recon: list[str],
) -> Answered:
    """Last resort: force one structured submit (floor bypassed), else synthesise
    a low-confidence partial. Never throws."""
    trace.forced_finalize = reason
    trace.degraded = True
    messages.append({"role": "user", "content": prompts.forced_finalize_message(reason)})
    try:
        with trace.span("model_turn:forced"):
            resp = _model_turn(client, config, messages, tools, force=True)
        trace.model_turns += 1
        trace.add_usage(getattr(resp, "usage", None))
        tool_use = _first_tool_use(resp)
        if tool_use is not None and tool_use.name == SUBMIT_TOOL:
            return _finish_answer(
                dict(tool_use.input or {}), trace, start, ops_after_recon, config,
                degraded=True,
            )
        trace.notes.append("forced finalize: model did not emit submit_answer")
    except Exception as exc:  # noqa: BLE001
        trace.notes.append(f"forced finalize failed: {exc}")
    return _fallback_answer(
        question, collected_ids, trace, start, ops_after_recon, config,
        gap=f"forced finalize ({reason}) — core left unresolved",
    )


# --------------------------------------------------------------------------- #
# Finalizers
# --------------------------------------------------------------------------- #


def _finish_answer(
    tool_input: dict,
    trace: TraceBuilder,
    start: float,
    ops_after_recon: list[str],
    config: AskConfig,
    *,
    degraded: bool,
) -> Answered:
    trace.sub_question_ledger = list(tool_input.get("sub_questions") or [])
    trace.adjacency_note = tool_input.get("adjacency_note")
    if degraded:
        trace.degraded = True
        # A degraded finalize aborted the normal loop — the answer cannot be
        # high/medium confidence (acceptance: "degrade to a low-confidence
        # partial"). Enforce it in code, not just in the prompt.
        if tool_input.get("confidence") != "low":
            tool_input = dict(tool_input)
            tool_input["confidence"] = "low"
            trace.notes.append("confidence floored to low on degraded finalize")
    trace_dict = _build_trace(trace, "answered", start, ops_after_recon, config)
    return answered_from_tool_input(tool_input, trace_dict)


def _finish_clarification(
    tool_input: dict,
    trace: TraceBuilder,
    start: float,
    ops_after_recon: list[str],
    config: AskConfig,
) -> NeedsClarification:
    trace_dict = _build_trace(trace, "needs_clarification", start, ops_after_recon, config)
    return clarification_from_tool_input(tool_input, trace_dict)


def _fallback_answer(
    question: str,
    collected_ids: set[str],
    trace: TraceBuilder,
    start: float,
    ops_after_recon: list[str],
    config: AskConfig,
    *,
    gap: str,
) -> Answered:
    trace.degraded = True
    trace_dict = _build_trace(trace, "answered", start, ops_after_recon, config)
    return Answered(
        answer=(
            "The substrate did not yield enough to resolve this with confidence. "
            "See gaps for what remained unresolved."
        ),
        confidence="low",
        interpretation=Interpretation(
            as_asked=question, resolved_to=question, reframed=False, reframe_reason=None
        ),
        gaps=[gap, "core sub-questions were unresolved when the call ended"],
        provenance=sorted(collected_ids),
        trace=trace_dict,
    )


def _build_trace(
    trace: TraceBuilder,
    outcome: str,
    start: float,
    ops_after_recon: list[str],
    config: AskConfig,
) -> dict:
    latency_ms = (time.monotonic() - start) * 1000.0
    record = trace.build(
        outcome=outcome,
        latency_ms=latency_ms,
        floor=_floor_state(ops_after_recon),
        input_per_mtok=config.input_per_mtok,
        output_per_mtok=config.output_per_mtok,
    )
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


def _floor_state(ops_after_recon: list[str]) -> dict:
    """The structural anti-premature-closure floor.

    Satisfied requires: recon ran (always, by construction), at least one
    targeted post-recon retrieval, and at least one semantic-adjacency
    re-search that is NOT the first post-recon move (i.e. the model retrieved,
    then came back and re-searched on gathered concepts).
    """
    targeted = len(ops_after_recon)
    adjacency = sum(
        1 for i in range(1, len(ops_after_recon)) if ops_after_recon[i] in _SEARCH_TOOLS
    )
    return {
        "recon": True,
        "targeted_retrievals": targeted,
        "adjacency_research": adjacency,
        "satisfied": targeted >= 1 and adjacency >= 1,
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
    client: Any,
    config: AskConfig,
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
    turn_messages = _strip_thinking(messages) if force else messages
    if config.cache:
        turn_messages = _with_rolling_cache(turn_messages)
    kwargs: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": _system_blocks(config),
        "messages": turn_messages,
        "tools": tools,
    }
    if force:
        # Forcing a specific tool is incompatible with extended thinking, so we
        # leave thinking off on the emergency finalize turn — and strip the
        # thinking blocks the adaptive turns left in history (done above), which
        # a thinking-disabled request shouldn't carry. A forced single-tool turn
        # has no sibling reads, so parallel tool use is moot here.
        kwargs["tool_choice"] = {
            "type": "tool",
            "name": SUBMIT_TOOL,
            "disable_parallel_tool_use": True,
        }
    else:
        # Parallel tool use lets the model batch independent reads (e.g. several
        # get_entity / get_statements) into one turn, collapsing serial round
        # trips. The loop answers every tool_use block in the response (see
        # `_execute`), which the API requires before the next turn.
        kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": False}
        if config.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
    return c.messages.create(**kwargs)


_CACHE_CONTROL = {"type": "ephemeral"}


def _system_blocks(config: AskConfig) -> Any:
    """The system prompt, as a cache-marked block when caching is on.

    The cache prefix is `tools -> system -> messages`, so a single breakpoint on
    the system block caches the whole static head (tool schemas + system prompt)
    — re-read instead of re-ingested on every turn after the first."""
    if not config.cache:
        return prompts.SYSTEM_PROMPT
    return [
        {"type": "text", "text": prompts.SYSTEM_PROMPT, "cache_control": _CACHE_CONTROL}
    ]


def _with_rolling_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return `messages` with a cache breakpoint on the final block.

    Each turn this marks the end of the conversation-so-far; because the loop
    only ever appends after it, that prefix is unchanged next turn and is read
    from cache. We copy rather than mutate the persistent history so the
    breakpoint doesn't accumulate across turns (the request carries exactly one
    rolling breakpoint, alongside the static system one)."""
    if not messages:
        return messages
    out = list(messages)
    last = dict(out[-1])
    content = last.get("content")
    if isinstance(content, list) and content and isinstance(content[-1], dict):
        blocks = list(content)
        blocks[-1] = {**blocks[-1], "cache_control": _CACHE_CONTROL}
        last["content"] = blocks
        out[-1] = last
    elif isinstance(content, str) and content:
        last["content"] = [
            {"type": "text", "text": content, "cache_control": _CACHE_CONTROL}
        ]
        out[-1] = last
    return out


def _block_type(block: Any) -> Any:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _strip_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop thinking / redacted_thinking blocks from assistant turns.

    Used only for the thinking-disabled forced-finalize request: a request
    without thinking enabled should not carry thinking blocks. If filtering
    would empty a message's content, the original is kept (an empty content
    list is itself invalid).
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            filtered = [
                b for b in content
                if _block_type(b) not in ("thinking", "redacted_thinking")
            ]
            out.append({**message, "content": filtered or content})
        else:
            out.append(message)
    return out


def _first_tool_use(resp: Any) -> Any | None:
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return block
    return None


def _tool_uses(resp: Any) -> list[Any]:
    """Every tool_use block in the response, in order. With parallel tool use a
    single turn can carry more than one."""
    return [
        block
        for block in getattr(resp, "content", None) or []
        if getattr(block, "type", None) == "tool_use"
    ]


def _tool_result_block(tool_use_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _append_tool_error(
    messages: list[dict[str, Any]], tool_use_id: str, message: str
) -> None:
    """Answer a single (terminal) tool_use with an error, as its own user
    message. Reads are batched by the caller; terminals are handled one at a
    time, so a per-message append is correct here."""
    messages.append(
        {"role": "user", "content": [_tool_result_block(tool_use_id, message, is_error=True)]}
    )


def _serialize(result: Any) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(result)
    if len(text) > _TOOL_RESULT_MAX_CHARS:
        text = text[:_TOOL_RESULT_MAX_CHARS] + "\n…[truncated]"
    return text


def _substrate_has(substrate: SubstrateReader, name: str) -> bool:
    has = getattr(substrate, "has", None)
    if callable(has):
        return bool(has(name))
    return any(spec.name == name for spec in substrate.tool_specs())


def _collect_ids(obj: Any, acc: set[str]) -> None:
    """Recursively gather statement ids (stm_…) for fallback provenance."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "id" and isinstance(value, str) and value.startswith("stm_"):
                acc.add(value)
            else:
                _collect_ids(value, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_ids(item, acc)
