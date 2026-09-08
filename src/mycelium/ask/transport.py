"""Opt-in SSE and completed JSON transport for the same Ask execution."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Request
from pydantic import JsonValue, TypeAdapter
from starlette.responses import JSONResponse, StreamingResponse

from .events import AskCancelled, AskEvent, AskStream, current_stream

_LOG = logging.getLogger(__name__)


async def respond(
    request: Request,
    run: Callable[[], Awaitable[object]],
    *,
    grace: float,
    heartbeat: float,
    delivery_timeout: float = 30,
) -> JSONResponse | StreamingResponse:
    sse = "text/event-stream" in request.headers.get("accept", "")
    events: queue.Queue[AskEvent] = queue.Queue(maxsize=64)
    stream = AskStream()

    def emit(event: AskEvent) -> None:
        # The tool applies the caller's verbosity after the loop completes.
        # Send that returned result, rather than the loop's internal full result.
        if event.type == "complete":
            return
        deadline = time.monotonic() + delivery_timeout
        while True:
            stream.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stream.cancelled.set()
                stream.check()
            try:
                events.put(event, timeout=min(0.1, remaining))
                return
            except queue.Full:
                continue

    if sse:
        stream.emit = emit

    async def work() -> object:
        token = current_stream.set(stream)
        try:
            return await run()
        finally:
            current_stream.reset(token)

    task = asyncio.create_task(work())
    # A disconnected consumer stops waiting; retrieve a later worker exception.
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    if not sse:
        try:
            done, _ = await asyncio.wait({task}, timeout=grace)
            if task in done:
                return JSONResponse(task.result())
        except BaseException:
            stream.cancelled.set()
            task.cancel()
            raise

    return StreamingResponse(
        _body(request, task, stream, events, sse=sse, heartbeat=heartbeat),
        media_type="text/event-stream" if sse else "application/json",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _body(
    request: Request,
    task: asyncio.Task[object],
    stream: AskStream,
    events: queue.Queue[AskEvent],
    *,
    sse: bool,
    heartbeat: float,
) -> AsyncIterator[bytes]:
    terminal = False
    next_heartbeat = asyncio.get_running_loop().time() + heartbeat
    try:
        while not task.done() or not events.empty():
            if await request.is_disconnected():
                return
            try:
                event = events.get_nowait()
            except queue.Empty:
                if asyncio.get_running_loop().time() >= next_heartbeat:
                    yield b": keepalive\n\n" if sse else b" "
                    next_heartbeat = asyncio.get_running_loop().time() + heartbeat
                await asyncio.sleep(0.02)
            else:
                terminal = event.type in {"complete", "error", "cancelled"}
                yield _encode(event)
        result = task.result()
        if not sse:
            yield json.dumps(result).encode()
        elif not terminal:
            yield _encode(
                AskEvent(
                    type="complete",
                    result=TypeAdapter(dict[str, JsonValue]).validate_python(result),
                )
            )
    except AskCancelled:
        if sse:
            yield _encode(AskEvent(type="cancelled", message="Ask cancelled."))
    except Exception:
        _LOG.exception("Ask transport failed")
        message = "Ask failed before a complete result was available."
        yield (
            _encode(AskEvent(type="error", message=message))
            if sse
            else json.dumps({"detail": message}).encode()
        )
    finally:
        stream.cancelled.set()
        if not task.done():
            task.cancel()


def _encode(event: AskEvent) -> bytes:
    return f"event: {event.type}\ndata: {event.model_dump_json(exclude_none=True)}\n\n".encode()
