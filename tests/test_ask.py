"""Tests for the `ask` reasoning loop.

The loop is exercised with a fake Anthropic client (scripts the model's
tool-use turns) and a fake substrate — no server, no network, no real API.
Each test maps to an acceptance criterion in the spec.
"""

from __future__ import annotations

import json
import types

import pytest

from mycelium.ask import Answered, AskConfig, NeedsClarification, run_ask
from mycelium.ask.schema import Answered as AnsweredModel
from mycelium.ask.substrate import InProcessSubstrate, SubstrateError, ToolSpec


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _usage(i: int = 10, o: int = 5):
    return types.SimpleNamespace(
        input_tokens=i,
        output_tokens=o,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _text(t: str):
    return types.SimpleNamespace(type="text", text=t)


def _tool_use(name: str, inp: dict, id: str = "tu"):
    return types.SimpleNamespace(type="tool_use", id=id, name=name, input=inp)


def _message(blocks, stop="tool_use"):
    return types.SimpleNamespace(content=list(blocks), stop_reason=stop, usage=_usage())


class FakeAnthropic:
    """Scripts a sequence of model responses; records each request's kwargs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self  # so `client.messages.create(...)` lands here

    def with_options(self, **_kw):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._responses.pop(0)


_MIN_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}


class FakeSubstrate:
    """Canned read-primitive results; records calls."""

    def __init__(self, results: dict):
        self._results = results
        self.calls: list[tuple[str, dict]] = []
        self._specs = [
            ToolSpec("search_statements", "search", _MIN_SCHEMA),
            ToolSpec("survey_statements", "survey", _MIN_SCHEMA),
            ToolSpec("get_statements", "get", _MIN_SCHEMA),
        ]

    def tool_specs(self):
        return list(self._specs)

    def has(self, name):
        return name in {s.name for s in self._specs}

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        value = self._results.get(name, [])
        if isinstance(value, Exception):
            raise SubstrateError(str(value))
        if callable(value):
            return value(arguments)
        return value


def _submit_input(**over):
    data = {
        "answer": "Because the worker retries once on a transient embed failure.",
        "confidence": "high",
        "interpretation": {
            "as_asked": "the question",
            "resolved_to": "the question",
            "reframed": False,
            "reframe_reason": None,
        },
        "sub_questions": [
            {"sub_question": "what triggers retry", "status": "resolved", "note": "found"}
        ],
        "adjacency_note": "Re-searched on 'retry'/'embed' concepts; nothing new surfaced.",
        "gaps": [],
        "provenance": ["stm_1"],
    }
    data.update(over)
    return data


def _clarify_input(**over):
    data = {
        "question": "Do you mean the staging deploy or the prod deploy?",
        "candidates": [
            {"interpretation": "staging deploy", "would_pull": "staging env statements"},
            {"interpretation": "prod deploy", "would_pull": "prod env statements"},
        ],
        "known_so_far": "Recon found two distinct deploy flows.",
    }
    data.update(over)
    return data


def _run(responses, results=None, **config_over):
    client = FakeAnthropic(responses)
    substrate = FakeSubstrate(results or {"survey_statements": [{"id": "stm_1", "text": "x"}]})
    cfg = AskConfig(thinking=True, trace_log_path=None, **config_over)
    result = run_ask("why does it retry?", client=client, substrate=substrate, config=cfg)
    return result, client, substrate


# --------------------------------------------------------------------------- #
# Acceptance criteria
# --------------------------------------------------------------------------- #


def test_well_formed_question_returns_answered_with_provenance_and_confidence():
    """#1 — answered with non-empty provenance and gaps-grounded confidence."""
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "embed retry"})]),  # adjacency
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, _client, substrate = _run(responses)

    assert isinstance(result, Answered)
    assert result.outcome == "answered"
    assert result.provenance == ["stm_1"]
    assert result.confidence in {"high", "medium", "low"}
    # floor was honoured: a targeted retrieval then an adjacency re-search
    assert result.trace["floor"]["satisfied"] is True
    assert ("search_statements", {"query": "retry"}) in substrate.calls


def test_misframed_but_resolvable_returns_reframed_answer():
    """#2 — answered with interpretation.reframed True and a reason."""
    reframed_interp = {
        "as_asked": "how do I disable the cache?",
        "resolved_to": "how the cache invalidates (there is no disable switch)",
        "reframed": True,
        "reframe_reason": "no disable capability exists; the real goal is invalidation",
    }
    responses = [
        _message([_tool_use("search_statements", {"query": "cache"})]),
        _message([_tool_use("survey_statements", {"query": "cache invalidate"})]),
        _message([_tool_use("submit_answer", _submit_input(interpretation=reframed_interp))]),
    ]
    result, _client, _sub = _run(responses)

    assert isinstance(result, Answered)
    assert result.interpretation.reframed is True
    assert result.interpretation.reframe_reason


def test_genuinely_ambiguous_returns_needs_clarification_no_answer():
    """#3 — needs_clarification with >=2 candidates and no committed answer."""
    responses = [_message([_tool_use("request_clarification", _clarify_input())])]
    result, _client, _sub = _run(responses)

    assert isinstance(result, NeedsClarification)
    assert result.outcome == "needs_clarification"
    assert len(result.candidates) >= 2
    assert all("would_pull" in c for c in result.candidates)
    assert not hasattr(result, "answer")


def test_clarification_with_too_few_candidates_is_reprompted():
    """A one-candidate clarification is rejected once, then the model proceeds."""
    responses = [
        _message([_tool_use("request_clarification", _clarify_input(candidates=[
            {"interpretation": "only one", "would_pull": "x"}
        ]))]),
        # after the re-prompt, the model retrieves and answers instead
        _message([_tool_use("search_statements", {"query": "x"})]),
        _message([_tool_use("survey_statements", {"query": "x adj"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, client, _sub = _run(responses)
    assert isinstance(result, Answered)
    assert len(client.calls) == 4  # the bad clarify did not terminate


def test_absent_subject_returns_low_confidence_with_absence_gap_no_fabrication():
    """#4 — absent-from-substrate -> low confidence, absence in gaps, no fabrication."""
    results = {"survey_statements": [], "search_statements": []}
    submit = _submit_input(
        confidence="low",
        provenance=[],
        gaps=["'kafka' returned zero results — not found in the substrate"],
        adjacency_note="Re-searched gathered concepts; still nothing.",
    )
    responses = [
        _message([_tool_use("search_statements", {"query": "kafka"})]),
        _message([_tool_use("survey_statements", {"query": "kafka queue"})]),
        _message([_tool_use("submit_answer", submit)]),
    ]
    result, _client, _sub = _run(responses, results=results)

    assert isinstance(result, Answered)
    assert result.confidence == "low"
    assert any("zero results" in g or "not found" in g for g in result.gaps)


def test_floor_prevents_premature_conclusion():
    """#5 — a forced early submit is blocked by the floor; the loop continues."""
    responses = [
        # premature: no retrieval yet -> floor must block this
        _message([_tool_use("submit_answer", _submit_input(), id="early")]),
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("submit_answer", _submit_input(), id="real")]),
    ]
    result, client, substrate = _run(responses)

    assert isinstance(result, Answered)
    # the premature submit did NOT terminate — the model was driven to retrieve
    assert ("search_statements", {"query": "retry"}) in substrate.calls
    assert ("survey_statements", {"query": "retry adj"}) in substrate.calls
    assert len(client.calls) == 4
    assert result.trace["floor"]["satisfied"] is True


def test_quick_depth_accepts_first_submit_without_the_floor():
    """`quick` (enforce_floor off) takes the first well-formed submit_answer —
    the very premature submit that `standard` blocks — with no forced retrieval
    or adjacency re-search, and without degrading."""
    responses = [
        # premature under standard; accepted immediately under quick
        _message([_tool_use("submit_answer", _submit_input(), id="early")]),
    ]
    result, client, substrate = _run(responses, enforce_floor=False)

    assert isinstance(result, Answered)
    assert result.confidence == "high"  # a real answer, not a degraded partial
    assert result.trace["degraded"] is False
    assert result.trace["forced_finalize"] is None
    # recon ran, but the loop was NOT driven to retrieve or re-search
    assert len(client.calls) == 1
    assert result.trace["floor"]["satisfied"] is False
    assert ("search_statements", {"query": "retry"}) not in substrate.calls


def test_quick_depth_tool_defs_drop_the_adjacency_requirement():
    """The submit tool the model sees in quick mode must not claim the adjacency
    re-search is required/gating — otherwise the model does the expensive work
    anyway and the latency win evaporates. Floor-on text is left untouched."""
    from mycelium.ask.tools import terminal_tool_defs

    floor = next(t for t in terminal_tool_defs(enforce_floor=True) if t["name"] == "submit_answer")
    quick = next(t for t in terminal_tool_defs(enforce_floor=False) if t["name"] == "submit_answer")

    # floor-on: unchanged — still demands the re-search in both the tool
    # description and the adjacency_note field.
    assert "adjacency re-search" in floor["description"]
    assert "loop will" in floor["input_schema"]["properties"]["adjacency_note"]["description"]

    # quick: neither the description nor the field claims it's required/gating.
    quick_note = quick["input_schema"]["properties"]["adjacency_note"]["description"]
    assert "no adjacency re-search is required in quick mode" in quick["description"]
    assert "OPTIONAL in quick mode" in quick_note
    assert "loop will" not in quick_note
    # still a required schema field in both modes (model must fill it)
    assert "adjacency_note" in quick["input_schema"]["required"]


def test_quick_depth_config_drops_floor_and_tightens_caps():
    """`for_depth(cfg, 'quick')` turns the floor off and lowers the caps to
    ceilings; `standard` is a no-op."""
    from mycelium.ask.config import (
        QUICK_OP_CAP,
        QUICK_REQUEST_TIMEOUT_S,
        QUICK_WALL_CLOCK_S,
        for_depth,
    )

    base = AskConfig()  # defaults: floor on, op_cap 25, wall_clock 45
    assert for_depth(base, "standard") is base  # unchanged

    quick = for_depth(base, "quick")
    assert quick.enforce_floor is False
    assert quick.op_cap == min(base.op_cap, QUICK_OP_CAP)
    assert quick.wall_clock_s == min(base.wall_clock_s, QUICK_WALL_CLOCK_S)
    assert quick.request_timeout_s == min(base.request_timeout_s, QUICK_REQUEST_TIMEOUT_S)
    # ceilings only: an already-tighter budget still wins
    tight = AskConfig(op_cap=3, wall_clock_s=10.0)
    assert for_depth(tight, "quick").op_cap == 3
    assert for_depth(tight, "quick").wall_clock_s == 10.0


def test_floor_stuck_eventually_force_finalizes_rather_than_looping():
    """A model that only ever tries to submit prematurely is force-finalized,
    and the forced model turn actually produces the structured answer."""
    # 4 premature submits get blocked / trigger the stuck branch, then the
    # forced finalize turn returns a distinctive structured answer.
    responses = [
        _message([_tool_use("submit_answer", _submit_input(), id=f"p{i}")]) for i in range(4)
    ]
    responses.append(
        _message([_tool_use("submit_answer", _submit_input(
            answer="forced structured answer", confidence="high"))])
    )
    result, _client, _sub = _run(responses)

    assert isinstance(result, Answered)
    assert result.trace["degraded"] is True
    assert result.trace["forced_finalize"] == "floor_stuck"
    # the forced model turn's answer was used (not the synthetic fallback) ...
    assert result.answer == "forced structured answer"
    # ... but its model-declared "high" was floored to low on the degrade path.
    assert result.confidence == "low"


def test_op_cap_exhaustion_degrades_to_partial_low_confidence_never_raises():
    """#6 — hitting the op cap degrades to a forced low-confidence answer."""
    # op_cap=2: recon(1) + one read(2) hits the cap; next iteration forces finalize.
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        # forced finalize turn returns the structured submit
        _message([_tool_use("submit_answer", _submit_input(confidence="low"))]),
    ]
    result, client, _sub = _run(responses, op_cap=2)

    assert isinstance(result, Answered)
    assert result.trace["forced_finalize"] == "op_cap"
    assert result.trace["degraded"] is True
    # the forced turn used a forced tool_choice and dropped thinking
    forced_call = client.calls[-1]
    assert forced_call["tool_choice"]["type"] == "tool"
    assert forced_call["tool_choice"]["name"] == "submit_answer"
    assert "thinking" not in forced_call


def test_op_cap_with_unresponsive_model_still_returns_answer():
    """Cap hit AND the forced finalize fails -> synthetic low-confidence answer."""
    # Only one response (the read); the forced finalize call finds no script and
    # raises inside the loop, which must fall back, not propagate.
    responses = [_message([_tool_use("search_statements", {"query": "retry"})])]
    result, _client, _sub = _run(responses, op_cap=2)
    assert isinstance(result, Answered)
    assert result.confidence == "low"
    assert result.trace["degraded"] is True


def test_trace_record_is_complete():
    """#7 — every run emits one complete machine-readable trace."""
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, _client, _sub = _run(responses)
    trace = result.trace
    for key in (
        "question", "model", "outcome", "op_count", "op_cap", "wall_clock_s_limit",
        "latency_ms", "model_turns", "tool_calls", "sub_question_ledger",
        "adjacency_note", "floor", "tokens", "cost_usd", "forced_finalize", "degraded",
        "notes",
    ):
        assert key in trace, f"trace missing {key}"
    # recon is the first recorded tool call and counts as an op
    assert trace["tool_calls"][0]["name"] == "survey_statements"
    assert trace["tool_calls"][0]["counts_as_op"] is True
    assert trace["op_count"] >= 3  # recon + search + survey
    assert trace["tokens"]["total"] > 0
    assert trace["sub_question_ledger"]  # ledger captured from the submit
    # trace must be JSON-serialisable (it's the eval-harness record)
    json.dumps(trace)


def test_trace_written_to_jsonl_file(tmp_path):
    """The trace is appended as a single JSONL line when a sink is configured."""
    log = tmp_path / "ask_trace.jsonl"
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    client = FakeAnthropic(responses)
    substrate = FakeSubstrate({"survey_statements": [{"id": "stm_1", "text": "x"}]})
    cfg = AskConfig(trace_log_path=str(log))
    run_ask("why?", client=client, substrate=substrate, config=cfg)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "answered"


def test_malformed_submit_is_reprompted_then_degrades():
    """A submit that fails validation is re-prompted once, then degrades."""
    bad = _submit_input(confidence="excellent")  # not in the enum
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("submit_answer", bad)]),
        _message([_tool_use("submit_answer", bad)]),  # still bad after re-prompt
    ]
    result, _client, _sub = _run(responses)
    assert isinstance(result, Answered)
    assert result.confidence == "low"
    assert any("formatting" in g for g in result.gaps)


def test_no_terminal_tool_is_nudged_then_forced():
    """Text-only turns are nudged once, then force-finalized."""
    responses = [
        _message([_text("I think the answer is...")], stop="end_turn"),
        _message([_text("Still just talking.")], stop="end_turn"),
        _message([_tool_use("submit_answer", _submit_input(confidence="medium"))]),
    ]
    result, _client, _sub = _run(responses)
    assert isinstance(result, Answered)
    assert result.trace["forced_finalize"] == "no_terminal"
    assert result.confidence == "low"  # model said "medium"; degrade floors it


def test_interleaved_text_turn_does_not_prematurely_degrade():
    """A stray text turn early must not doom a later one once the model is back
    to calling tools — the nudge budget is per text-streak, not per session."""
    responses = [
        _message([_text("let me think")], stop="end_turn"),          # nudge #1
        _message([_tool_use("search_statements", {"query": "retry"})]),  # back to tools
        _message([_text("hmm, one more thought")], stop="end_turn"),  # nudge again, not doom
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, _client, _sub = _run(responses)
    assert isinstance(result, Answered)
    assert result.trace["forced_finalize"] is None
    assert result.trace["degraded"] is False
    assert result.confidence == "high"  # a clean, non-degraded answer


def test_persistent_underspecified_clarification_degrades_not_broken():
    """A model that twice returns <2 candidates is degraded to a forced answer —
    never a NeedsClarification that violates the >=2-candidate contract."""
    one = _clarify_input(candidates=[{"interpretation": "only one", "would_pull": "x"}])
    responses = [
        _message([_tool_use("request_clarification", one)]),
        _message([_tool_use("request_clarification", one)]),
        _message([_tool_use("submit_answer", _submit_input(confidence="high"))]),
    ]
    result, _client, _sub = _run(responses)
    assert isinstance(result, Answered)  # NOT a broken NeedsClarification
    assert result.trace["forced_finalize"] == "clarify_stuck"
    assert result.confidence == "low"


def test_substrate_read_failure_is_surfaced_not_fabricated():
    """A read that fails twice is recorded as an error op, loop still concludes."""
    results = {
        "survey_statements": [{"id": "stm_1", "text": "x"}],
        "search_statements": SubstrateError("index timeout"),
    }
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),  # fails
        _message([_tool_use("survey_statements", {"query": "retry adj"})]),
        _message([_tool_use("survey_statements", {"query": "more adj"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, _client, _sub = _run(responses, results=results)
    assert isinstance(result, Answered)
    failed = [tc for tc in result.trace["tool_calls"] if tc["name"] == "search_statements"]
    assert failed and failed[0]["ok"] is False and failed[0]["error"]


# --------------------------------------------------------------------------- #
# Substrate seam: discovery + retry (criterion #8)
# --------------------------------------------------------------------------- #


def _reader(name):
    def fn(**kwargs):
        return {"ok": name}
    fn.__name__ = name
    fn._mycelium_required_role = "reader"
    return fn


def _writer(name):
    def fn(**kwargs):
        return {}
    fn.__name__ = name
    fn._mycelium_required_role = "writer"
    return fn


def test_discovery_auto_includes_new_read_primitive_excludes_writes():
    """#8 — discovery is denylist-based: a new reader tool appears with no code
    change; writers and the denylist are excluded."""
    stub = types.SimpleNamespace(
        TOOLS=[
            _reader("search_widgets"),       # a hypothetical FUTURE read primitive
            _reader("report_knowledge_gap"),  # denylisted (reader-role write)
            _reader("ask"),                   # denylisted (self)
            _writer("upsert_widget"),         # a write — excluded by role
        ]
    )
    sub = InProcessSubstrate(stub)
    names = {s.name for s in sub.tool_specs()}
    assert "search_widgets" in names          # auto-discovered, no edit needed
    assert "report_knowledge_gap" not in names
    assert "ask" not in names
    assert "upsert_widget" not in names


def test_strip_thinking_sanitizes_forced_turn_history():
    """The forced (thinking-disabled) turn must not carry thinking blocks, but
    keeps tool_use / tool_result / text and never empties a message."""
    from mycelium.ask.loop import _strip_thinking

    th = types.SimpleNamespace(type="thinking", thinking="...")
    tu = types.SimpleNamespace(type="tool_use", id="x", name="search_statements", input={})
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [th, tu]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "r", "is_error": False}
        ]},
        {"role": "assistant", "content": [th]},  # thinking-only: must not be emptied
    ]
    out = _strip_thinking(msgs)
    assert [b.type for b in out[1]["content"]] == ["tool_use"]  # thinking dropped
    assert out[2]["content"][0]["type"] == "tool_result"        # tool_result kept
    assert out[0]["content"] == "q"                             # string content untouched
    assert out[3]["content"] == [th]                            # not emptied


def test_substrate_retries_once_then_raises():
    """The substrate seam retries a transient failure once, then surfaces it."""
    state = {"n": 0}

    def flaky(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    flaky.__name__ = "search_flaky"
    flaky._mycelium_required_role = "reader"

    always_fail = lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))
    always_fail.__name__ = "search_dead"
    always_fail._mycelium_required_role = "reader"

    stub = types.SimpleNamespace(TOOLS=[flaky, always_fail])
    sub = InProcessSubstrate(stub)

    assert sub.call("search_flaky", {}) == {"ok": True}
    assert state["n"] == 2  # one retry, then success
    with pytest.raises(SubstrateError):
        sub.call("search_dead", {})


def test_existing_read_primitives_and_writes_untouched():
    """#8 — the real server still exposes its read surface; ask is registered as
    a reader and excluded from the inner tool set."""
    from mycelium import server

    names = {getattr(t, "__name__", "") for t in server.TOOLS}
    assert "ask" in names
    assert {"search_statements", "survey_statements", "get_statements"} <= names
    # ask is reader-role and not offered back to the inner model
    sub = InProcessSubstrate(server)
    inner = {s.name for s in sub.tool_specs()}
    assert "ask" not in inner
    assert "upsert_statement" not in inner
    assert "report_knowledge_gap" not in inner


# --------------------------------------------------------------------------- #
# Caching + parallel tool use (latency wins)
# --------------------------------------------------------------------------- #


def _last_block(message: dict):
    content = message["content"]
    return content[-1] if isinstance(content, list) else content


def test_caching_marks_static_and_rolling_breakpoints():
    """With cache on, every request caches the system head and a rolling
    breakpoint on the end of the conversation so turns 2..N read from cache."""
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "embed retry"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    _result, client, _sub = _run(responses, cache=True)

    for call in client.calls:
        # system is a cache-marked block, not a bare string.
        assert isinstance(call["system"], list)
        assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
        # the last conversation block carries the rolling breakpoint.
        last = _last_block(call["messages"][-1])
        assert isinstance(last, dict)
        assert last["cache_control"] == {"type": "ephemeral"}


def test_caching_off_sends_plain_system_and_no_breakpoints():
    responses = [_message([_tool_use("submit_answer", _submit_input())])]
    _result, client, _sub = _run(responses, cache=False)

    call = client.calls[0]
    assert call["system"] == __import__(
        "mycelium.ask.prompts", fromlist=["SYSTEM_PROMPT"]
    ).SYSTEM_PROMPT
    last = _last_block(call["messages"][-1])
    if isinstance(last, dict):
        assert "cache_control" not in last


def test_trace_records_per_phase_and_per_turn_timings():
    """The trace persists where the wall-clock went — collapsed phase totals
    plus each model turn's own latency — so inference cost is visible without
    the flamegraph."""
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "embed retry"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, _client, _sub = _run(responses)

    trace = result.trace
    assert "phase_ms" in trace and "model_turn_ms" in trace
    # one timing per adaptive model turn (3 here), plus recon/tool phases present
    assert len(trace["model_turn_ms"]) == 3
    assert "recon" in trace["phase_ms"]
    assert trace["phase_ms"]["model_turn"] >= 0


def test_adaptive_turns_allow_parallel_tool_use():
    """The retrieval turns enable parallel tool use; only the forced finalize
    (which forces a single tool) disables it."""
    responses = [
        _message([_tool_use("search_statements", {"query": "retry"})]),
        _message([_tool_use("survey_statements", {"query": "embed retry"})]),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    _result, client, _sub = _run(responses)

    for call in client.calls:
        assert call["tool_choice"]["disable_parallel_tool_use"] is False


def test_parallel_reads_in_one_turn_all_get_results():
    """A single turn carrying several read tool_use blocks executes all of them
    and answers each — collapsing serial round trips."""
    results = {
        "survey_statements": [{"id": "stm_1", "text": "x"}],
        "search_statements": [{"id": "stm_2", "text": "y"}],
        "get_statements": {"statements": [{"id": "stm_3", "text": "z"}]},
    }
    responses = [
        # one turn, three independent reads at once
        _message(
            [
                _tool_use("search_statements", {"query": "retry"}, id="a"),
                _tool_use("get_statements", {"ids": ["stm_3"]}, id="b"),
                _tool_use("survey_statements", {"query": "embed retry"}, id="c"),
            ]
        ),
        _message([_tool_use("submit_answer", _submit_input())]),
    ]
    result, client, substrate = _run(responses, results=results)

    assert isinstance(result, Answered)
    # all three reads ran in the single turn
    names = [n for n, _ in substrate.calls]
    assert names.count("search_statements") == 1
    assert names.count("get_statements") == 1
    # the turn's three tool_results are batched into ONE user message (the API
    # wants all of a turn's results in the single following user turn).
    second_request_msgs = client.calls[1]["messages"]
    result_msgs = [
        msg
        for msg in second_request_msgs
        if isinstance(msg["content"], list)
        and any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in msg["content"]
        )
    ]
    assert len(result_msgs) == 1
    answered_ids = {
        b["tool_use_id"]
        for b in result_msgs[0]["content"]
        if b.get("type") == "tool_result"
    }
    assert answered_ids == {"a", "b", "c"}
