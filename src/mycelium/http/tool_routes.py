"""The REST mirror: one generated route for every registered tool.

Every function in `server.TOOLS` (everything decorated with `@tool`) gets an
endpoint here, including the tools `server.MCP_TOOLS` keeps off the MCP
surface. The path is the kebab-case tool name; the method is GET when a read
tool takes no args, POST otherwise, and the request body's Pydantic schema is
derived from the function signature.

Add a tool to a module in `mycelium/server/` with `@tool`, list it in
`mycelium.server.__all__` (its position there is its place in every listing),
and you'll find it here too at `/<kebab-case-name>` after a server restart —
no edits needed in this file.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio.to_thread
from fastapi import APIRouter, Request
from pydantic import BaseModel, create_model

from .. import auth, server, tracing
from .access import _enforce_role

router = APIRouter()


def _path_for(func_name: str) -> str:
    return "/" + func_name.replace("_", "-")


def _model_name_for(func_name: str) -> str:
    return func_name.title().replace("_", "") + "Body"


def _make_post_handler(
    func: Callable[..., Any], BodyModel: type[BaseModel], required_role: str
) -> Callable[..., Any]:
    def handler(body: BaseModel, request: Request) -> object:
        _enforce_role(
            request, required_role, getattr(func, "_mycelium_real_role", False)
        )
        return func(**body.model_dump())

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"body": BodyModel, "request": Request}
    return handler


# Tools whose answer can take longer than an idle connection is allowed to live.
# The path in front of us is Cloudflare -> ALB -> task; the ALB drops a
# connection after 60s of *no bytes flowing* (its default idle timeout), and a
# single multi-turn `ask` can exceed that. The fix is to keep bytes moving: the
# JSON path drips whitespace while the blocking tool runs, then emits the
# normal JSON body last. Accept: text/event-stream opts into factual Ask events. Leading whitespace is ignored by `JSON.parse`, so the
# browser (and any `res.json()` caller) parses the result unchanged — no client
# edit needed.
_STREAMING_TOOLS = {"ask"}
# Finish-fast window: if the tool returns (or raises) within this, respond
# normally so success and 4xx/5xx keep their real HTTP status — identical to
# every other endpoint. Only genuinely slow calls fall through to streaming.
_STREAM_GRACE_SECONDS = 5.0
# Heartbeat cadence — comfortably under the ALB's 60s idle timeout.
_STREAM_HEARTBEAT_SECONDS = 15.0


def _offload(func: Callable[..., Any], kwargs: dict[str, Any]) -> Awaitable[Any]:
    """Run a blocking tool in a worker thread under whatever bound it declares.

    `server.limiter_for` is the single source of that bound. Going through it
    here is what stops the REST mirror from being a way around it: these
    handlers are built from the raw sync wrapper in `server.TOOLS`, not from the
    offloading shim the MCP transport gets, so without this a caller could
    exceed the model-loop bound just by posting to `/ask` instead.

    anyio (not asyncio.to_thread) for two reasons: it takes the limiter, and it
    shares the same worker pool FastAPI already dispatches sync endpoints to.
    Contextvars — including the resolved principal — propagate either way.
    """
    return anyio.to_thread.run_sync(
        functools.partial(func, **kwargs), limiter=server.limiter_for(func.__name__)
    )


def _make_offloaded_post_handler(
    func: Callable[..., Any], BodyModel: type[BaseModel], required_role: str
) -> Callable[..., Any]:
    """For bounded tools that aren't streamed. A plain sync handler would take a
    worker thread and hold it while waiting on the bound; this waits on the
    limiter first and only then occupies a thread."""

    async def handler(body: BaseModel, request: Request) -> object:
        _enforce_role(
            request, required_role, getattr(func, "_mycelium_real_role", False)
        )
        return await _offload(func, body.model_dump())

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"body": BodyModel, "request": Request}
    return handler


def _make_streaming_post_handler(
    func: Callable[..., Any], BodyModel: type[BaseModel], required_role: str
) -> Callable[..., Any]:
    async def handler(body: BaseModel, request: Request) -> object:
        _enforce_role(
            request, required_role, getattr(func, "_mycelium_real_role", False)
        )
        from ..ask.transport import respond

        return await respond(
            request,
            lambda: _offload(func, body.model_dump()),
            grace=_STREAM_GRACE_SECONDS,
            heartbeat=_STREAM_HEARTBEAT_SECONDS,
        )

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"body": BodyModel, "request": Request}
    return handler


# Read primitives slow enough to be worth a timing trace when called
# as a top-level op. Traced HERE, at the HTTP edge — NOT on the function — so the
# ask/ingest loops, which call these same functions in-process via the substrate
# seam, don't each spawn a duplicate find trace (the loop already times them).
# The `trace_span("embed")`/`("vector_search")` markers inside the functions then
# light up only for these top-level calls, via the ambient recorder set below.
_TRACED_TOOLS = {"search_statements", "grep_statements"}


def _make_traced_post_handler(
    func: Callable[..., Any], BodyModel: type[BaseModel], required_role: str
) -> Callable[..., Any]:
    def handler(body: BaseModel, request: Request) -> object:
        _enforce_role(
            request, required_role, getattr(func, "_mycelium_real_role", False)
        )
        kwargs = body.model_dump()
        if not tracing.tracing_enabled():
            return func(**kwargs)  # tracing off: zero overhead on the hot path
        label = kwargs.get("query") or func.__name__
        recorder = tracing.SpanRecorder()
        started = time.monotonic()
        with tracing.profile_to_html("find", label):
            with tracing.use_recorder(recorder):
                try:
                    with recorder.span(func.__name__):
                        return func(**kwargs)
                finally:
                    tracing.emit_trace(
                        recorder,
                        kind="find",
                        label=label,
                        record={
                            "outcome": "ok",
                            "latency_ms": (time.monotonic() - started) * 1000.0,
                        },
                    )

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"body": BodyModel, "request": Request}
    return handler


def _make_get_handler(
    func: Callable[..., Any], required_role: str
) -> Callable[..., Any]:
    def handler(request: Request) -> object:
        _enforce_role(
            request, required_role, getattr(func, "_mycelium_real_role", False)
        )
        return func()

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"request": Request}
    return handler


def _register(func: Callable[..., Any]) -> None:
    sig = inspect.signature(func)
    hints = inspect.get_annotations(func, eval_str=True)
    path = _path_for(func.__name__)
    # Honor an explicit per-tool override stamped by `server.tool(role=...)`,
    # otherwise fall back to prefix-derivation. Keeps the REST mirror's
    # role gate aligned with the MCP `tools/list` filter — both look at
    # the same attribute.
    required = getattr(func, "_mycelium_required_role", None) or auth.required_role_for(
        func.__name__
    )

    # GET only for reads: a browser sends GET with the session cookie from
    # any site that links or embeds the URL.
    readable = required in ("asker", "reader")
    if readable and not sig.parameters:
        router.get(path, name=func.__name__)(_make_get_handler(func, required))
        return

    if (
        readable
        and len(sig.parameters) == 1
        and "draft_id" in sig.parameters
        and sig.parameters["draft_id"].default is None
    ):
        router.get(path, name=func.__name__)(_make_get_handler(func, required))

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        annotation = hints.get(name, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    # pydantic's overloads can't tell **fields apart from its __config__-style
    # keywords, so no overload matches a plain field mapping.
    BodyModel = create_model(_model_name_for(func.__name__), **fields)  # type: ignore[call-overload]
    if func.__name__ in _STREAMING_TOOLS:
        make = _make_streaming_post_handler
    elif server.limiter_for(func.__name__) is not None:
        make = _make_offloaded_post_handler
    elif func.__name__ in _TRACED_TOOLS:
        make = _make_traced_post_handler
    else:
        make = _make_post_handler
    router.post(path, name=func.__name__)(make(func, BodyModel, required))


for _func in server.TOOLS:
    _register(_func)
