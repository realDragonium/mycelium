"""Ask streaming uses mocked provider bytes and synthetic evidence only."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest

from mycelium import ai
from mycelium.ask import AskConfig, run_ask
from mycelium.ask.events import AnswerDeltas, AskCancelled, AskEvent, AskStream
from test_ask import FakeSubstrate, _submit_input


def provider_events(provider, arguments, *, incomplete=False):
    chunks = [arguments[i : i + 7] for i in range(0, len(arguments), 7)]
    if provider == "openai":
        item = {
            "id": "fc1",
            "type": "function_call",
            "call_id": "tu1",
            "name": "submit_answer",
            "arguments": "",
        }
        yield {"type": "response.output_item.added", "output_index": 0, "item": item}
        yield {"type": "response.reasoning_text.delta", "delta": "PRIVATE REASONING"}
        for chunk in chunks:
            yield {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc1",
                "delta": chunk,
            }
        if not incomplete:
            yield {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [{**item, "arguments": arguments}],
                    "usage": {"output_tokens": 30},
                },
            }
    else:
        yield {
            "type": "message_start",
            "message": {
                "id": "msg1",
                "type": "message",
                "role": "assistant",
                "model": "mock",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
        yield {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        }
        yield {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "PRIVATE REASONING"},
        }
        yield {"type": "content_block_stop", "index": 0}
        yield {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "tu1",
                "name": "submit_answer",
                "input": {},
            },
        }
        for chunk in chunks:
            yield {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": chunk},
            }
        yield {"type": "content_block_stop", "index": 1}
        yield {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 30},
        }
        if not incomplete:
            yield {"type": "message_stop"}


class ProviderBytes(httpx.SyncByteStream):
    def __init__(self, events, before_end=lambda: None):
        self.events = list(events)
        self.before_end = before_end
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for event in self.events:
            if event["type"] in {"response.completed", "message_stop"}:
                self.before_end()
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

    def close(self):
        self.closed = True


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_real_provider_stream_delivers_answer_before_completion(provider, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    events: list[AskEvent] = []
    answer = _submit_input(answer='The "worker" retries.\nConditions: café 🧪.')
    stream = ProviderBytes(
        provider_events(provider, json.dumps(answer)), lambda: assert_first_text(events)
    )
    requests = []

    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = run_ask(
            "Why?",
            client=client,
            substrate=FakeSubstrate(
                {"survey_statements": [{"id": "stm_1", "text": "The worker retries."}]}
            ),
            config=AskConfig(provider=provider, enforce_floor=False, trace_dir=""),
            stream=AskStream(emit=events.append),
        )
    assert result.answer == answer["answer"]
    assert result.provenance == ["stm_1"]
    assert result.interpretation.as_asked == "Why?"
    assert result.interpretation.resolved_to == "Why?"
    assert (
        "".join(event.text for event in events if event.type == "answer_delta")
        == result.answer
    )
    assert events[-1].type == "complete"
    assert events[-1].result == result.model_dump()
    assert "PRIVATE REASONING" not in json.dumps([e.model_dump() for e in events])
    timing = result.trace["stream_timing_ms"]
    assert (
        timing["first_progress_ms"]
        <= timing["first_answer_text_ms"]
        <= timing["completion_ms"]
    )
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert stream.closed


def assert_first_text(events):
    assert any(event.type == "answer_delta" for event in events)
    assert not any(event.type == "complete" for event in events)


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_provider_eof_is_not_a_complete_result(provider, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    from mycelium.ask.tools import build_tools

    received = []
    stream = ProviderBytes(
        provider_events(provider, json.dumps(_submit_input()), incomplete=True)
    )
    task = ai.ToolTask(
        "Answer",
        [{"role": "user", "content": "Question"}],
        build_tools([]),
        on_tool_delta=lambda *args: received.append(args),
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(ai.ModelError, match="without a completed response"):
            ai.turn(task, ai.ModelConfig(provider, "mock", 1000, 10), client=client)
    assert received
    assert stream.closed


def scripted_turns(monkeypatch, calls):
    remaining = iter(calls)
    requests = []

    def turn(task, config, *, client=None):
        requests.append(task)
        blocks = next(remaining)
        if isinstance(blocks, Exception):
            if task.on_tool_delta:
                task.on_tool_delta(
                    "bad", "submit_answer", '{"answer":"incomplete draft'
                )
            raise blocks
        for block in blocks:
            if task.on_tool_delta:
                task.on_tool_delta(block.id, block.name, json.dumps(block.input))
        return ai.ModelResponse(
            content=blocks, usage=ai.Usage(), stop_reason="tool_use"
        )

    monkeypatch.setattr(ai, "turn", turn)
    return requests


def call(name, arguments, identity="tu"):
    return ai.ToolUse(id=identity, name=name, input=arguments)


def execute(monkeypatch, turns, *, standard=False, sink=None):
    requests = scripted_turns(monkeypatch, turns)
    events = []
    stream = AskStream(emit=sink or events.append)
    result = run_ask(
        "Why retry?",
        substrate=FakeSubstrate(
            {
                "survey_statements": [{"id": "stm_1", "text": "The retry worker."}],
                "get_statements": {
                    "statements": [
                        {"id": "stm_2", "text": "Transient failures trigger retries."}
                    ]
                },
            }
        ),
        config=AskConfig(enforce_floor=standard, trace_dir=""),
        stream=stream,
    )
    return result, events, requests


def test_stream_is_gated_and_same_turn_search_cannot_satisfy_adjacency(monkeypatch):
    answer = call("submit_answer", _submit_input())
    result, events, requests = execute(
        monkeypatch,
        [
            [answer],
            [
                call("get_statements", {"ids": ["stm_2"]}, "get"),
                call(
                    "survey_statements",
                    {"query": "worker failures", "adjacency_sources": ["s1"]},
                    "search",
                ),
            ],
            [answer],
            [
                call(
                    "survey_statements",
                    {
                        "query": "transient retry conditions",
                        "adjacency_sources": ["s2"],
                    },
                )
            ],
            [answer],
        ],
        standard=True,
    )
    assert result.trace["floor"]["satisfied"]
    assert [check["adjacency"] for check in result.trace["evidence_checks"]] == [
        False,
        False,
        True,
    ]
    assert len(requests) == 5
    assert len([event for event in events if event.type == "answer_delta"]) == 1


@pytest.mark.parametrize("invalid", ["s99", "ent_1", "stm_unread"])
def test_unknown_provenance_resets_the_draft_and_retries(monkeypatch, invalid):
    result, events, requests = execute(
        monkeypatch,
        [
            [call("submit_answer", _submit_input(provenance=[invalid]))],
            [call("submit_answer", _submit_input())],
        ],
    )
    assert result.provenance == ["stm_1"]
    assert len(requests) == 2
    assert [e.type for e in events].count("answer_reset") == 1
    assert events[-1].type == "complete"


def test_incomplete_model_output_resets_and_degrades_explicitly(monkeypatch):
    result, events, _ = execute(
        monkeypatch,
        [ai.ModelError("stream incomplete"), [call("submit_answer", _submit_input())]],
    )
    assert result.confidence == "low"
    assert result.trace["forced_finalize"] == "api_error"
    assert any("forced" in gap for gap in result.gaps)
    assert any(event.type == "answer_reset" for event in events)
    assert events[-1].type == "complete"


def test_clarification_has_no_answer_deltas(monkeypatch):
    from test_ask import _clarify_input

    result, events, _ = execute(
        monkeypatch, [[call("request_clarification", _clarify_input())]], standard=True
    )
    assert result.outcome == "needs_clarification"
    assert not any(event.type == "answer_delta" for event in events)
    assert events[-1].result["outcome"] == "needs_clarification"


def test_cancel_after_answer_delta_never_forces_another_model_call(monkeypatch):
    requests = scripted_turns(monkeypatch, [[call("submit_answer", _submit_input())]])
    stream = AskStream()
    stream.emit = lambda event: (
        stream.cancelled.set() if event.type == "answer_delta" else None
    )
    with pytest.raises(AskCancelled):
        run_ask(
            "Why?",
            substrate=FakeSubstrate(
                {"survey_statements": [{"id": "stm_1", "text": "retry"}]}
            ),
            config=AskConfig(enforce_floor=False, trace_dir=""),
            stream=stream,
        )
    assert len(requests) == 1


def test_cancel_before_start_does_no_retrieval():
    substrate = FakeSubstrate({})
    stream = AskStream()
    stream.cancelled.set()
    with pytest.raises(AskCancelled):
        run_ask(
            "Why?", substrate=substrate, config=AskConfig(trace_dir=""), stream=stream
        )
    assert substrate.calls == []


def test_answer_parser_ignores_other_fields_and_partial_escapes():
    events = []
    deltas = AnswerDeltas(AskStream(emit=events.append), allowed=True)
    raw = json.dumps(
        {"gaps": ['secret field with "answer": "fake"'], "answer": 'A "quote"\n🧪'}
    )
    for char in raw:
        deltas.receive("one", "submit_answer", char)
    assert (
        "".join(event.text for event in events if event.type == "answer_delta")
        == 'A "quote"\n🧪'
    )
    assert "secret" not in str(events)


def test_openai_stream_retries_only_before_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr("mycelium.ai.openai.time.sleep", lambda _: None)
    from mycelium.ask.tools import build_tools

    requests = []
    body = ProviderBytes(provider_events("openai", json.dumps(_submit_input())))

    def reply(request):
        requests.append(request)
        return (
            httpx.Response(429)
            if len(requests) == 1
            else httpx.Response(200, stream=body)
        )

    task = ai.ToolTask(
        "Answer",
        [{"role": "user", "content": "Question"}],
        build_tools([]),
        on_tool_delta=lambda *args: None,
    )
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = ai.turn(
            task,
            ai.ModelConfig("openai", "mock", 1000, 10, max_retries=1),
            client=client,
        )
    assert result.stop_reason == "tool_use"
    assert len(requests) == 2


def test_recon_only_reference_cannot_satisfy_adjacency(monkeypatch):
    turns = [
        [call("get_statements", {"ids": ["stm_missing"]})],
        [
            call(
                "survey_statements",
                {"query": "related conditions", "adjacency_sources": ["s1"]},
            )
        ],
        [call("submit_answer", _submit_input())],
    ]
    scripted_turns(monkeypatch, turns)
    result = run_ask(
        "Why?",
        substrate=FakeSubstrate(
            {
                "survey_statements": [{"id": "stm_1", "text": "recon only"}],
                "get_statements": {"statements": [], "missing": ["stm_missing"]},
            }
        ),
        config=AskConfig(trace_dir=""),
    )
    assert result.trace["floor"]["satisfied"] is False
    assert result.confidence == "low"
    check = result.trace["evidence_checks"][-1]
    assert check["ok"] is False
    assert "earlier turn" in check["error"]


def test_forced_finalize_keeps_deterministic_coverage_gaps(monkeypatch):
    scripted_turns(monkeypatch, [[call("submit_answer", _submit_input(provenance=[]))]])
    result = run_ask(
        "Why?",
        substrate=FakeSubstrate(
            {"survey_statements": [{"id": "stm_1", "text": "x" * 25_000}]}
        ),
        config=AskConfig(op_cap=1, trace_dir=""),
    )
    assert result.confidence == "low"
    assert any("omitted" in gap for gap in result.gaps)
    assert any("No statement evidence" in gap for gap in result.gaps)
    assert any("forced" in gap for gap in result.gaps)


def test_cancelled_trace_has_first_text_but_no_completion(monkeypatch, tmp_path):
    scripted_turns(monkeypatch, [[call("submit_answer", _submit_input())]])
    path = tmp_path / "trace.jsonl"
    stream = AskStream()
    stream.emit = lambda event: (
        stream.cancelled.set() if event.type == "answer_delta" else None
    )
    with pytest.raises(AskCancelled):
        run_ask(
            "Why?",
            substrate=FakeSubstrate(
                {"survey_statements": [{"id": "stm_1", "text": "retry"}]}
            ),
            config=AskConfig(
                enforce_floor=False, trace_dir="", trace_log_path=str(path)
            ),
            stream=stream,
        )
    trace = json.loads(path.read_text())
    assert trace["outcome"] == "cancelled"
    assert trace["stream_timing_ms"]["first_answer_text_ms"] >= 0
    assert "completion_ms" not in trace["stream_timing_ms"]


def test_malformed_clarification_retries_without_committing(monkeypatch):
    from test_ask import _clarify_input

    result, events, requests = execute(
        monkeypatch,
        [
            [call("request_clarification", _clarify_input(candidates=[{}, {}]))],
            [call("request_clarification", _clarify_input())],
        ],
        standard=True,
    )
    assert result.outcome == "needs_clarification"
    assert len(requests) == 2
    assert [e.type for e in events].count("complete") == 1


def test_cancellation_during_recon_records_incomplete_trace(tmp_path):
    stream = AskStream(emit=lambda event: None)

    def recon(arguments):
        stream.cancelled.set()
        return [{"id": "stm_1", "text": "recon completed after cancellation"}]

    path = tmp_path / "trace.jsonl"
    with pytest.raises(AskCancelled):
        run_ask(
            "Why?",
            substrate=FakeSubstrate({"survey_statements": recon}),
            config=AskConfig(trace_dir="", trace_log_path=str(path)),
            stream=stream,
        )
    trace = json.loads(path.read_text())
    assert trace["outcome"] == "cancelled"
    assert trace["model_turns"] == 0
    assert "completion_ms" not in trace["stream_timing_ms"]
