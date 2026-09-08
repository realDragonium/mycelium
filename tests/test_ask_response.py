"""The public Ask tool keeps diagnostics opt-in across JSON and SSE."""

import asyncio
import json

import pytest
from starlette.requests import Request

from mycelium import ask, server
from mycelium.ask.events import AskEvent, current_stream
from mycelium.ask.schema import Interpretation
from mycelium.ask.transport import respond


@pytest.fixture(params=["answered", "needs_clarification"])
def result(request):
    if request.param == "answered":
        return ask.Answered(
            answer="A match score measures fit. The exact formula is unknown.",
            confidence="medium",
            interpretation=Interpretation(
                as_asked="What is a match score?",
                resolved_to="What is a match score?",
                reframed=False,
            ),
            gaps=["Formula unknown"],
            provenance=["stm_1"],
            trace={"latency_ms": 15000},
        )
    return ask.NeedsClarification(
        question="Overall or per construct?",
        candidates=[{"interpretation": "Overall"}, {"interpretation": "Construct"}],
        known_so_far="Two scores exist.",
        trace={"latency_ms": 15000},
    )


@pytest.mark.parametrize("verbose", [False, True])
def test_tool_response(monkeypatch, result, verbose):
    monkeypatch.setattr(
        ask.AskConfig, "from_env", lambda: ask.AskConfig(trace_log_path="unused")
    )
    monkeypatch.setattr(ask, "run_ask", lambda question, *, config: result)
    arguments = {"verbose": True} if verbose else {}
    response = server.ask.__wrapped__("What is a match score?", **arguments)
    expected = result.model_dump()
    if not verbose:
        fields = (
            {"outcome", "answer", "confidence"}
            if result.outcome == "answered"
            else {"outcome", "question"}
        )
        expected = {key: value for key, value in expected.items() if key in fields}
    assert response == expected


def test_sse_uses_public_result_instead_of_internal_completion():
    compact = {"outcome": "answered", "answer": "Fit", "confidence": "high"}

    async def run():
        stream = current_stream.get()
        assert stream is not None
        stream.send(
            AskEvent(type="complete", result={**compact, "trace": {"secret": 1}})
        )
        return compact

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def exercise():
        request = Request(
            {"type": "http", "headers": [(b"accept", b"text/event-stream")]},
            receive,
        )
        response = await respond(request, run, grace=0, heartbeat=1)
        return b"".join([chunk async for chunk in response.body_iterator]).decode()

    body = asyncio.run(exercise())
    assert body.count("event: complete") == 1
    payload = json.loads(body.split("data: ", 1)[1])
    assert payload["result"] == compact
