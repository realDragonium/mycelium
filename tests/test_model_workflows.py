"""The question and knowledge workflows run unchanged over OpenAI tool calls."""

import json
from collections.abc import Sequence

import httpx
from pydantic import JsonValue, TypeAdapter

import test_ask as ask_fixtures
import test_ingest as ingest_fixtures
import test_research as research_fixtures
from mycelium import ai, research, research_runs
from mycelium.ask import run_ask
from mycelium.ask.config import AskConfig
from mycelium.ask.schema import Answered
from mycelium.ingest import run_ingest
from mycelium.ingest.config import IngestConfig
from mycelium.ingest.draft import DraftEmitter
from mycelium.ingest.schema import DraftCreated
from mycelium.research import run_research
from mycelium.research.config import ResearchConfig
from mycelium.research.schema import NothingFound, ResearchDraftCreated
from mycelium.research.sources import Source


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
            [ask_fixtures._tool_use("submit_answer", ask_fixtures._submit_input())]
        ),
    ]
    requests: list[dict[str, JsonValue]] = []
    with httpx.Client(transport=_transport(responses, requests)) as client:
        result = run_ask(
            "why does it retry?",
            client=client,
            substrate=ask_fixtures.FakeSubstrate(
                {"survey_statements": [{"id": "stm_1", "text": "retry"}]}
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
    assert all(request["parallel_tool_calls"] is False for request in requests)


def test_openai_research_explores_and_reconciles_before_emitting(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    requests: list[dict[str, JsonValue]] = []
    emitter = research_fixtures.FakeEmitter()
    with httpx.Client(
        transport=_transport(research_fixtures._full_run_turns(), requests)
    ) as client:
        result = run_research(
            "how invites work",
            Source(name="acme", owner="acme", repo="api"),
            client=client,
            substrate=research_fixtures.FakeSubstrate(),
            workspace=research_fixtures.FakeWorkspace(),
            emitter=emitter,
            config=ResearchConfig(
                provider="openai", model="research-model", trace_dir=""
            ),
        )
    assert isinstance(result, ResearchDraftCreated)
    assert [kind for _, kind, _ in emitter.queued] == ["upsert_statement"]
    assert result.trace["floor"]["explored"] is True
    assert result.trace["floor"]["reconciled"] is True
    assert result.trace["provider"] == "openai"
    assert all(request["model"] == "research-model" for request in requests)


def test_research_worker_keeps_model_selected_at_admission(monkeypatch, tmp_path):
    monkeypatch.setenv("MYCELIUM_RESEARCH_PROVIDER", "openai")
    monkeypatch.setenv("MYCELIUM_RESEARCH_OPENAI_MODEL", "admitted-model")
    observed: list[ResearchConfig] = []

    def run(
        topic: str, source: str | None, *, config: ResearchConfig, emitter: DraftEmitter
    ) -> NothingFound:
        observed.append(config)
        return NothingFound(reason="fixture", topic=topic)

    monkeypatch.setattr(research, "run_research", run)
    runner = research_runs._default_runner(str(tmp_path))
    monkeypatch.setenv("MYCELIUM_RESEARCH_OPENAI_MODEL", "changed-model")
    runner("topic", source="fixture")
    assert observed[0].provider == "openai"
    assert observed[0].model == "admitted-model"
