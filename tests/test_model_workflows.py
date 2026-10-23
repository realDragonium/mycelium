"""The question and knowledge workflows run unchanged over OpenAI tool calls."""

import json
from collections.abc import Sequence

import httpx
from pydantic import JsonValue, TypeAdapter

import test_ask as ask_fixtures
import test_ingest as ingest_fixtures
from mycelium import ai
from mycelium.ask import run_ask
from mycelium.ask.config import AskConfig
from mycelium.ask.schema import Answered
from mycelium.ingest import run_ingest
from mycelium.ingest.config import IngestConfig
from mycelium.ingest.schema import DraftCreated


def _transport(
    responses: Sequence[object], requests: list[dict[str, JsonValue]]
) -> httpx.MockTransport:
    scripted = iter(responses)

    def reply(request: httpx.Request) -> httpx.Response:
        requests.append(
            TypeAdapter(dict[str, JsonValue]).validate_json(request.content)
        )
        response = next(scripted)
        calls = [ai.ToolUse.model_validate(block) for block in response.content]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": f"call_{len(requests)}_{index}",
                        "name": call.name,
                        "arguments": json.dumps(call.input),
                    }
                    for index, call in enumerate(calls)
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )

    return httpx.MockTransport(reply)


def test_openai_question_batches_reads_and_retains_grounded_answer(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    responses = [
        ask_fixtures._message(
            [
                ask_fixtures._tool_use("search_statements", {"query": "retry"}, "one"),
                ask_fixtures._tool_use(
                    "survey_statements", {"query": "embed retry"}, "two"
                ),
            ]
        ),
        ask_fixtures._message(
            [
                ask_fixtures._tool_use(
                    "survey_statements",
                    {"query": "retry conditions", "adjacency_sources": ["s1"]},
                    "adj",
                )
            ]
        ),
        ask_fixtures._message(
            [ask_fixtures._tool_use("submit_answer", ask_fixtures._submit_input())]
        ),
    ]
    requests: list[dict[str, JsonValue]] = []
    with httpx.Client(transport=_transport(responses, requests)) as client:
        result = run_ask(
            "why does it retry?",
            client=client,
            substrate=ask_fixtures.FakeSubstrate(
                {
                    "survey_statements": [{"id": "stm_1", "text": "retry"}],
                    "search_statements": [{"id": "stm_1", "text": "retry"}],
                }
            ),
            config=AskConfig(provider="openai", model="question-model", trace_dir=""),
        )
    assert isinstance(result, Answered)
    assert result.trace["floor"]["satisfied"] is True
    assert result.trace["provider"] == "openai"
    assert result.trace["cost_usd"] is None
    assert all(request["model"] == "question-model" for request in requests)
    assert requests[0]["parallel_tool_calls"] is True
    history = TypeAdapter(list[dict[str, JsonValue]]).validate_python(
        requests[1]["input"]
    )
    assert (
        len([item for item in history if item.get("type") == "function_call_output"])
        == 2
    )


def test_openai_ingest_reconciles_and_only_emits_a_draft(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    responses = ingest_fixtures._reconcile_then_adjacency() + [
        ingest_fixtures._message(
            [
                ingest_fixtures._tool_use(
                    "emit_draft", ingest_fixtures._good_new_op_emit()
                )
            ]
        )
    ]
    requests: list[dict[str, JsonValue]] = []
    emitter = ingest_fixtures.FakeEmitter()
    with httpx.Client(transport=_transport(responses, requests)) as client:
        result = run_ingest(
            "An invite is submitted.",
            client=client,
            substrate=ingest_fixtures.FakeSubstrate(),
            emitter=emitter,
            config=IngestConfig(
                provider="openai", model="ingestion-model", trace_dir=""
            ),
        )
    assert isinstance(result, DraftCreated)
    assert len(emitter.queued) == 1
    assert result.trace["floor"]["satisfied"] is True
    assert result.trace["provider"] == "openai"
    assert all(request["model"] == "ingestion-model" for request in requests)
    assert all(request["parallel_tool_calls"] is True for request in requests)
