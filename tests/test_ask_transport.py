"""Transport compatibility, errors and disconnect cleanup without a live service."""

from __future__ import annotations

import asyncio
import json
import threading

import anyio
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from mycelium.ask.events import AskCancelled, AskEvent, current_stream, run_cancellable
from mycelium.ask.transport import respond

RESULT = {
    "outcome": "answered",
    "answer": "A complete answer",
    "confidence": "high",
    "interpretation": {
        "as_asked": "Q",
        "resolved_to": "Q",
        "reframed": False,
        "reframe_reason": None,
    },
    "gaps": [],
    "provenance": ["stm_1"],
    "trace": {},
}


def client_for(run, grace=0):
    app = FastAPI()

    @app.post("/ask")
    async def ask(request: Request):
        return await respond(request, run, grace=grace, heartbeat=0.001)

    return TestClient(app)


def frames(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.parametrize("sse", [False, True])
def test_completed_json_and_opt_in_stream_share_result(sse):
    async def run():
        stream = current_stream.get()
        stream.progress("retrieval", "Retrieved synthetic evidence.")
        stream.send(AskEvent(type="answer_delta", text=RESULT["answer"]))
        stream.send(AskEvent(type="complete", result=RESULT))
        return RESULT

    with client_for(run) as client:
        response = client.post(
            "/ask",
            headers={"accept": "text/event-stream" if sse else "application/json"},
        )
    assert response.status_code == 200
    if sse:
        events = frames(response)
        assert [e["type"] for e in events] == ["progress", "answer_delta", "complete"]
        assert events[-1]["result"] == RESULT
        assert response.headers["content-type"].startswith("text/event-stream")
    else:
        assert response.json() == RESULT


def test_legacy_fast_errors_keep_http_error_status():
    from fastapi import HTTPException

    async def run():
        raise HTTPException(status_code=400, detail="Invalid question")

    with client_for(run, grace=1) as client:
        response = client.post("/ask")
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid question"}


@pytest.mark.parametrize("sse", [False, True])
def test_late_errors_are_explicit_and_never_return_partial_success(sse):
    async def run():
        await asyncio.sleep(0.01)
        raise RuntimeError("private server exception")

    with client_for(run) as client:
        response = client.post(
            "/ask",
            headers={"accept": "text/event-stream" if sse else "application/json"},
        )
    assert "private server exception" not in response.text
    if sse:
        assert frames(response)[-1]["type"] == "error"
        assert not any(e["type"] == "complete" for e in frames(response))
    else:
        assert "detail" in response.json()
        assert "outcome" not in response.json()


def test_cancelled_run_emits_cancelled_terminal():
    async def run():
        raise AskCancelled("Cancelled")

    with client_for(run) as client:
        response = client.post("/ask", headers={"accept": "text/event-stream"})
    assert [event["type"] for event in frames(response)] == ["cancelled"]


def test_disconnected_consumer_stops_worker_and_releases_queue():
    async def scenario():
        disconnected = False
        stopped = threading.Event()
        started = threading.Event()
        captured = []

        async def receive():
            return {
                "type": "http.disconnect" if disconnected else "http.request",
                "body": b"",
            }

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ask",
                "headers": [(b"accept", b"text/event-stream")],
            },
            receive,
        )

        def worker():
            stream = current_stream.get()
            captured.append(stream)
            started.set()
            try:
                # More than the bounded queue capacity; disconnect must unblock it.
                for _ in range(1000):
                    stream.progress("retrieval", "Synthetic read")
            except AskCancelled:
                stopped.set()
                raise

        response = await respond(
            request, lambda: asyncio.to_thread(worker), grace=0, heartbeat=1
        )
        assert isinstance(response, StreamingResponse)
        iterator = response.body_iterator
        await anext(iterator)
        assert started.is_set()
        disconnected = True
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        assert captured[0].cancelled.is_set()
        assert await asyncio.to_thread(stopped.wait, 1)

    asyncio.run(scenario())


def test_mcp_cancellation_marks_the_worker_context():
    async def scenario():
        ready = asyncio.Event()
        captured = []

        async def work():
            captured.append(current_stream.get())
            ready.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(run_cancellable(work))
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert captured[0].cancelled.is_set()
        assert current_stream.get() is None

    asyncio.run(scenario())


def test_stalled_connected_consumer_cancels_worker_and_releases_slot():
    async def scenario():
        finished = asyncio.Event()
        limiter = anyio.CapacityLimiter(1)
        captured = []

        async def receive():
            return {"type": "http.request", "body": b""}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/ask",
                "headers": [(b"accept", b"text/event-stream")],
            },
            receive,
        )

        def worker():
            stream = current_stream.get()
            captured.append(stream)
            for _ in range(1000):
                stream.progress("retrieval", "Synthetic read")
            pytest.fail("A stalled consumer must cancel before all events are sent")

        async def run():
            try:
                await anyio.to_thread.run_sync(worker, limiter=limiter)
            finally:
                finished.set()

        response = await respond(
            request, run, grace=0, heartbeat=1, delivery_timeout=0.01
        )
        # Keep the socket connected without consuming the response body.
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert captured[0].cancelled.is_set()
        assert limiter.borrowed_tokens == 0
        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"event: cancelled" in chunks[-1]
        assert not any(b"event: complete" in chunk for chunk in chunks)

    asyncio.run(scenario())


def test_http_handler_passes_context_without_changing_body_schema(monkeypatch):
    from mycelium import http

    class Body(BaseModel):
        question: str

    def ask(question):
        assert current_stream.get() is not None
        return RESULT

    monkeypatch.setattr(http, "_enforce_role", lambda *args: None)
    monkeypatch.setattr(http.server, "limiter_for", lambda name: None)
    app = FastAPI()
    app.post("/ask")(http._make_streaming_post_handler(ask, Body, "asker"))
    with TestClient(app) as client:
        response = client.post(
            "/ask", json={"question": "Q"}, headers={"accept": "text/event-stream"}
        )
    assert frames(response)[-1]["result"] == RESULT
