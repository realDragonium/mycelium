"""Where a request's time went: waiting for a worker thread, running in one,
and inside that, embedding, SQLite, the write lock and model calls.

Each HTTP request (and each background unit of work that opts in with
`track`) carries one `Timing` in a context variable. The instrumented seams —
the worker-thread hop, `embed.embed`, the SQLite connections, the write lock and
the model calls — add their elapsed time to it through `phase`, which costs two
clock reads when a timing is active and one context-variable read when not.
Context variables follow a call into its worker thread, so a phase measured
there lands on the request that started it.

`first_byte` is when the response started, not a share of the time: a
streamed response (an MCP call past the SDK's 15 s deferral, an Ask stream)
starts long before it ends.

Phases overlap by design: `thread_run` contains whatever else ran in the
thread, and SQLite time spent holding the write lock counts in both. Calls a
request runs in parallel threads can add up to more than its wall time.

A finished timing is kept in a bounded in-memory window (`summary` reports
p50/p95/max per route over it) and, past `MYCELIUM_SLOW_REQUEST_MS` or when it
failed or its client left, logged as one `MYCELIUM_SLOW_REQUEST` line.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import math
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, ParamSpec, TypeVar

import anyio.to_thread
from fastapi.routing import APIRoute
from starlette.routing import Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

P = ParamSpec("P")
R = TypeVar("R")

Phase = Literal[
    "first_byte",
    "thread_wait",
    "thread_run",
    "lock_wait",
    "lock_held",
    "embed",
    "sqlite",
    "model",
]
PHASES: tuple[Phase, ...] = (
    "first_byte",
    "thread_wait",
    "thread_run",
    "lock_wait",
    "lock_held",
    "embed",
    "sqlite",
    "model",
)

#: The token every slow-request line starts with, for a log-metric filter.
SLOW_TOKEN = "MYCELIUM_SLOW_REQUEST"

_LOG = logging.getLogger("mycelium.performance")
if not _LOG.handlers:
    _LOG.addHandler(logging.StreamHandler(sys.stderr))
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False


def slow_threshold_ms() -> float:
    raw = (os.environ.get("MYCELIUM_SLOW_REQUEST_MS") or "").strip()
    return float(raw) if raw else 2000.0


@dataclass(slots=True)
class Timing:
    label: str
    started: float = field(default_factory=time.perf_counter)
    phases: dict[Phase, float] = field(default_factory=dict)
    failed: bool = False
    disconnected: bool = False

    def add(self, name: Phase, seconds: float) -> None:
        self.phases[name] = self.phases.get(name, 0.0) + seconds


_current: ContextVar[Timing | None] = ContextVar(
    "mycelium_request_timing", default=None
)


def current() -> Timing | None:
    return _current.get()


@contextmanager
def phase(name: Phase) -> Iterator[None]:
    timing = _current.get()
    if timing is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        timing.add(name, time.perf_counter() - started)


@contextmanager
def track(label: str) -> Iterator[Timing]:
    """Time one unit of work under `label` and record it when it ends."""
    timing = Timing(label)
    token = _current.set(timing)
    try:
        yield timing
    except BaseException:
        timing.failed = True
        raise
    finally:
        _current.reset(token)
        _finish(timing)


def tracked(label: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a background unit of work so each call is timed like a
    request under `label`."""

    def decorate(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def timed(*args: P.args, **kwargs: P.kwargs) -> R:
            with track(label):
                return func(*args, **kwargs)

        return timed

    return decorate


def _finish(timing: Timing) -> None:
    total = time.perf_counter() - timing.started
    sample = Sample(
        label=timing.label,
        at=time.monotonic(),
        total=total,
        phases=dict(timing.phases),
        failed=timing.failed,
        disconnected=timing.disconnected,
    )
    recorder.add(sample)
    if total * 1000 >= slow_threshold_ms() or timing.failed or timing.disconnected:
        _LOG.warning("%s %s", SLOW_TOKEN, sample.log_fields())


async def run_sync(
    func: Callable[[], R],
    *,
    limiter: anyio.CapacityLimiter | None = None,
    abandon_on_cancel: bool = False,
) -> R:
    """`anyio.to_thread.run_sync`, recording how long the call waited for a
    worker thread and how long it ran in one."""
    timing = _current.get()
    if timing is None:
        return await anyio.to_thread.run_sync(
            func, limiter=limiter, abandon_on_cancel=abandon_on_cancel
        )
    submitted = time.perf_counter()

    def timed() -> R:
        started = time.perf_counter()
        timing.add("thread_wait", started - submitted)
        try:
            return func()
        finally:
            timing.add("thread_run", time.perf_counter() - started)

    return await anyio.to_thread.run_sync(
        timed, limiter=limiter, abandon_on_cancel=abandon_on_cancel
    )


# --- the write lock ---------------------------------------------------------


class TimedLock:
    """A reentrant lock that charges the wait to `lock_wait` and the outermost
    hold to `lock_held`."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._local = threading.local()

    @contextmanager
    def held(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            with phase("lock_wait"):
                self._lock.acquire()
        depth: int = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        started = time.perf_counter() if depth == 0 else 0.0
        try:
            yield
        finally:
            self._local.depth = depth
            if depth == 0:
                timing = _current.get()
                if timing is not None:
                    timing.add("lock_held", time.perf_counter() - started)
            self._lock.release()


# --- SQLite -----------------------------------------------------------------


def _charged(name: Phase, call: Callable[[], R]) -> R:
    """`phase` without the context-manager machinery, for per-row paths."""
    timing = _current.get()
    if timing is None:
        return call()
    started = time.perf_counter()
    try:
        return call()
    finally:
        timing.add(name, time.perf_counter() - started)


class TimedCursor(sqlite3.Cursor):
    """Charges statement execution and row fetching to `sqlite`: a SELECT does
    most of its work while its rows are fetched, not in `execute`."""

    def execute(self, sql: str, parameters: Any = (), /) -> TimedCursor:
        _charged("sqlite", lambda: super(TimedCursor, self).execute(sql, parameters))
        return self

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> TimedCursor:
        _charged(
            "sqlite",
            lambda: super(TimedCursor, self).executemany(sql, seq_of_parameters),
        )
        return self

    def fetchone(self) -> Any:
        return _charged("sqlite", super().fetchone)

    def fetchmany(self, size: int | None = 1) -> list[Any]:
        batch = self.arraysize if size is None else size
        return _charged("sqlite", lambda: super(TimedCursor, self).fetchmany(batch))

    def fetchall(self) -> list[Any]:
        return _charged("sqlite", super().fetchall)

    def __next__(self) -> Any:
        return _charged("sqlite", super().__next__)


class TimedConnection(sqlite3.Connection):
    """The `factory` every store opens its connections with."""

    def cursor(self, factory: Any = TimedCursor) -> Any:
        return super().cursor(factory)

    def execute(self, sql: str, parameters: Any = (), /) -> TimedCursor:
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql: str, parameters: Any, /) -> TimedCursor:
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        return _charged(
            "sqlite", lambda: super(TimedConnection, self).executescript(sql_script)
        )

    def commit(self) -> None:
        _charged("sqlite", super().commit)


# --- the recent window ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sample:
    label: str
    at: float
    total: float
    phases: dict[Phase, float]
    failed: bool
    disconnected: bool = False

    def log_fields(self) -> str:
        parts = [
            f"route={self.label.replace(' ', '_')}",
            f"failed={self.failed}",
            f"disconnected={self.disconnected}",
        ]
        parts.append(f"total_ms={self.total * 1000:.0f}")
        parts.extend(
            f"{name}_ms={self.phases[name] * 1000:.0f}"
            for name in PHASES
            if name in self.phases
        )
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class Spread:
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class RouteSummary:
    label: str
    count: int
    errors: int
    disconnects: int
    total: Spread
    phases: dict[Phase, Spread]


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    # Nearest-rank: the reported value is one that was actually observed.
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _spread(values: list[float]) -> Spread:
    ordered = sorted(values)
    return Spread(
        p50_ms=round(_percentile(ordered, 0.5) * 1000, 1),
        p95_ms=round(_percentile(ordered, 0.95) * 1000, 1),
        max_ms=round(ordered[-1] * 1000, 1),
    )


class Recorder:
    def __init__(self, *, window_s: float, max_samples: int) -> None:
        self.window_s = window_s
        self._samples: deque[Sample] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def add(self, sample: Sample) -> None:
        with self._lock:
            self._samples.append(sample)

    def summary(self, now: float | None = None) -> list[RouteSummary]:
        """Per route over the window, slowest p95 first. A phase's spread
        counts only the requests that spent time in it."""
        cutoff = (time.monotonic() if now is None else now) - self.window_s
        with self._lock:
            recent = [s for s in self._samples if s.at >= cutoff]
        by_label: dict[str, list[Sample]] = {}
        for sample in recent:
            by_label.setdefault(sample.label, []).append(sample)
        routes = [
            RouteSummary(
                label=label,
                count=len(samples),
                errors=sum(s.failed for s in samples),
                disconnects=sum(s.disconnected for s in samples),
                total=_spread([s.total for s in samples]),
                phases={
                    name: _spread(values)
                    for name in PHASES
                    if (values := [s.phases[name] for s in samples if name in s.phases])
                },
            )
            for label, samples in by_label.items()
        ]
        routes.sort(key=lambda route: route.total.p95_ms, reverse=True)
        return routes


#: Fifteen minutes is long enough to still hold a slowdown someone noticed and
#: went to look at; the sample cap bounds memory under a burst.
recorder = Recorder(window_s=15 * 60, max_samples=20_000)


# --- the HTTP edge ----------------------------------------------------------


def _label(scope: Scope) -> str:
    route = scope.get("route")
    if isinstance(route, APIRoute):
        return f"{scope['method']} {route.path}"
    if isinstance(route, Mount):
        return f"{scope['method']} {route.path}"
    path: str = scope["path"]
    # The UI's static files and the MCP endpoint are mounts Starlette doesn't
    # name in the scope; their paths are few and fixed.
    if path.startswith("/ui/") or path == "/ui":
        return f"{scope['method']} /ui"
    return f"{scope['method']} {path}"


_MCP_NAME = re.compile(r"[\w./-]{1,64}")


def _mcp_label(body: bytes) -> str:
    """`MCP <method>`, and the tool for a `tools/call`, from a JSON-RPC body.
    The names come from the client, so anything unexpected is `?`."""

    def clean(value: object) -> str:
        return value if isinstance(value, str) and _MCP_NAME.fullmatch(value) else "?"

    try:
        message = json.loads(body)
    except ValueError:
        return "MCP ?"
    if isinstance(message, list):
        return "MCP batch"
    if not isinstance(message, dict):
        return "MCP ?"
    method = clean(message.get("method"))
    params = message.get("params")
    if method == "tools/call" and isinstance(params, dict):
        return f"MCP tools/call {clean(params.get('name'))}"
    return f"MCP {method}"


class RequestTimingMiddleware:
    """Times each HTTP request, including when its response started (which
    is what a load balancer's response time measures) and whether the client
    left before the response ended. A `POST /mcp` is labelled with the
    JSON-RPC method and tool it carried."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status: int | None = None
        finished = False
        mcp_body: bytearray | None = (
            bytearray()
            if scope["method"] == "POST" and scope["path"] == "/mcp"
            else None
        )

        with track("") as timing:

            async def receive_watching() -> Message:
                message = await receive()
                if message["type"] == "http.disconnect" and not finished:
                    timing.disconnected = True
                elif message["type"] == "http.request" and mcp_body is not None:
                    mcp_body.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        timing.label = _mcp_label(bytes(mcp_body))
                return message

            async def send_recording(message: Message) -> None:
                nonlocal status, finished
                if message["type"] == "http.response.start":
                    status = message["status"]
                    timing.add("first_byte", time.perf_counter() - timing.started)
                elif message["type"] == "http.response.body":
                    finished = not message.get("more_body", False)
                await send(message)

            try:
                await self.app(scope, receive_watching, send_recording)
            finally:
                # Labelled on the way out: only routing knows the route's
                # template.
                timing.label = timing.label or _label(scope)
                if status is None:
                    timing.failed = not timing.disconnected
                else:
                    timing.failed = status >= 500


def _offloaded(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Present a sync endpoint as a coroutine that runs it in a worker thread,
    as FastAPI would, but through `run_sync`."""

    @functools.wraps(endpoint)
    async def offloaded(*args: Any, **kwargs: Any) -> Any:
        return await run_sync(functools.partial(endpoint, *args, **kwargs))

    return offloaded


class TimedRoute(APIRoute):
    """The route class of every router: FastAPI hands a sync endpoint to its
    thread pool where nothing could see how long it queued for a thread."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if not inspect.iscoroutinefunction(endpoint):
            endpoint = _offloaded(endpoint)
        super().__init__(path, endpoint, **kwargs)
