"""Shared timing/profiling for the slow surfaces (ask, ingest, find).

Tracing is OFF by default; an admin arms it for a debugging window (see the
`/api/tracing/*` endpoints). While armed, every top-level op produces two
artifacts, at two altitudes:

  1. A one-line per-phase summary to stderr → CloudWatch (`emit_trace`), built
     from lightweight named spans — the cheap `aws logs tail` triage line
     ("embed = 500ms, vector_search = 1ms").
  2. A self-contained pyinstrument **HTML flamegraph** (`profile_to_html`),
     written to the trace dir and served rendered by `GET /api/traces/{id}` —
     the deep call-stack view for *why* a phase is slow.

Spans: `SpanRecorder` records named phases (open/close, monotonic). A primitive
can publish its recorder as the ambient one (`use_recorder`); code deeper down
adds phases via `trace_span(...)` without threading a recorder through, and it's
a no-op when nothing is active — so `trace_span("embed")` inside
`search_statements` enriches a standalone find's summary and costs nothing when
the ask loop calls the same function in-process.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

# (kind, frame name, milliseconds-since-recorder-start); kind is "O" | "C".
SpanEvent = tuple[str, str, float]

#: One structured line per traced op to stderr → CloudWatch on Fargate (mirrors
#: the `mycelium.profile` logger idiom). The speedscope file holds the detail;
#: this is the at-a-glance "where did the time go" for `aws logs tail`.
_TRACE_LOG = logging.getLogger("mycelium.trace")
if not _TRACE_LOG.handlers:
    _TRACE_LOG.addHandler(logging.StreamHandler(sys.stderr))
    _TRACE_LOG.setLevel(logging.INFO)

#: The literal token every uncaught-error line starts with. A CloudWatch metric
#: filter matches on exactly this string to count errors (see the service stack
#: in infra/). Don't change it casually — the filter pattern is coupled to it.
ERROR_TOKEN = "MYCELIUM_ERROR"

#: Errors always log, regardless of the tracing on/off toggle — an unhandled
#: exception in production is exactly what we never want to miss. Same
#: stderr→CloudWatch idiom as the trace/profile loggers.
_ERROR_LOG = logging.getLogger("mycelium.errors")
if not _ERROR_LOG.handlers:
    _ERROR_LOG.addHandler(logging.StreamHandler(sys.stderr))
    _ERROR_LOG.setLevel(logging.INFO)


def emit_error(*, where: str, exc: BaseException, **fields: Any) -> None:
    """Log one structured, greppable line for an uncaught error to stderr →
    CloudWatch, with the traceback attached via ``exc_info``.

    Every line begins with ``ERROR_TOKEN`` so a single metric filter can count
    errors; ``where`` says which boundary caught it (e.g. "http") and ``fields``
    carries context (path, method). Always emits — unlike traces, errors are not
    gated by the tracing toggle. Never raises: a logging failure must not mask
    the original error or break the response path."""
    try:
        extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
        _ERROR_LOG.error(
            "%s where=%s exc=%s msg=%s%s",
            ERROR_TOKEN,
            where,
            type(exc).__name__,
            (str(exc).replace("\n", " ")[:500] or "-"),
            f" {extra}" if extra else "",
            exc_info=exc,
        )
    except Exception:  # noqa: BLE001
        pass

_active: ContextVar["SpanRecorder | None"] = ContextVar(
    "mycelium_trace_recorder", default=None
)
# Reentrancy guard so a nested op (shouldn't happen today, but cheap insurance)
# can't start a second pyinstrument profiler in the same thread.
_profiling: ContextVar[bool] = ContextVar("mycelium_profiling", default=False)

# Runtime on/off — tracing is OFF by default so a deployed task writes nothing
# until you ask it to. Flip it on for a debugging window (optionally with a TTL
# so it auto-disarms) via the `/api/tracing/*` endpoints, then off again. The
# initial state can be forced on at boot with MYCELIUM_TRACE_ENABLED=1.
_TOGGLE_LOCK = threading.Lock()
_enabled: bool = os.environ.get("MYCELIUM_TRACE_ENABLED", "").lower() in (
    "1", "on", "true", "yes",
)
_enabled_until: float | None = None  # monotonic deadline; None = no expiry


def tracing_enabled() -> bool:
    if not _enabled:
        return False
    if _enabled_until is not None and time.monotonic() >= _enabled_until:
        return False
    return True


def set_tracing(enabled: bool, *, ttl_seconds: float | None = None) -> dict[str, Any]:
    """Turn tracing on/off at runtime. `ttl_seconds` auto-disarms after a window
    (only meaningful when enabling). Returns the resulting status."""
    global _enabled, _enabled_until
    with _TOGGLE_LOCK:
        _enabled = enabled
        _enabled_until = (
            time.monotonic() + ttl_seconds if enabled and ttl_seconds else None
        )
    return tracing_status()


def tracing_status() -> dict[str, Any]:
    expires_in = None
    if _enabled and _enabled_until is not None:
        expires_in = round(max(0.0, _enabled_until - time.monotonic()), 1)
    return {"enabled": tracing_enabled(), "expires_in_s": expires_in}


class SpanRecorder:
    """Records nested spans. One per top-level op; live for its duration."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self.events: list[SpanEvent] = []

    def _now_ms(self) -> float:
        return (time.monotonic() - self._t0) * 1000.0

    def total_ms(self) -> float:
        return self._now_ms()

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        self.events.append(("O", name, self._now_ms()))
        try:
            yield
        finally:
            self.events.append(("C", name, self._now_ms()))

    def durations_ms(self) -> dict[str, float]:
        """Inclusive time per frame name, summed across repeats (e.g. all model
        turns collapse into one number). Good enough for a one-line summary."""
        totals: dict[str, float] = {}
        for name, spans in self.per_span_ms().items():
            totals[name] = sum(spans)
        return totals

    def per_span_ms(self) -> dict[str, list[float]]:
        """Inclusive time per frame name, one entry per occurrence in open
        order — so repeated phases (each model turn, each tool call) keep their
        individual durations instead of collapsing. Lets a trace show that, say,
        one model turn was the outlier rather than just the total."""
        out: dict[str, list[float]] = {}
        stack: list[tuple[str, float]] = []
        for kind, name, at in self.events:
            if kind == "O":
                stack.append((name, at))
            elif stack:
                opened_name, opened_at = stack.pop()
                out.setdefault(opened_name, []).append(at - opened_at)
        return out


def current_recorder() -> "SpanRecorder | None":
    return _active.get()


@contextmanager
def use_recorder(recorder: "SpanRecorder") -> Iterator["SpanRecorder"]:
    """Publish `recorder` as the ambient one for the duration of the block."""
    token = _active.set(recorder)
    try:
        yield recorder
    finally:
        _active.reset(token)


@contextmanager
def trace_span(name: str) -> Iterator[None]:
    """Add a phase to the ambient recorder, or do nothing if none is active."""
    recorder = _active.get()
    if recorder is None:
        yield
    else:
        with recorder.span(name):
            yield


def default_trace_dir() -> Path:
    """Where flamegraph files are written / served from. Under the data dir so
    on Fargate it lands on the writable volume. Empty string disables writing."""
    raw = os.environ.get("MYCELIUM_TRACE_DIR")
    if raw is None:
        raw = str(Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")) / "traces")
    return Path(raw).expanduser()


def emit_trace(
    spans: SpanRecorder,
    *,
    kind: str,
    label: Any,
    record: dict[str, Any],
    trace_dir: str | Path | None = None,  # unused; kept for caller compatibility
) -> None:
    """Log a one-line per-phase timing summary to stderr → CloudWatch. The
    visual artifact (a pyinstrument HTML flamegraph) is written separately by
    `profile_to_html`; this is just the cheap `aws logs tail` triage line. No-op
    when tracing is disabled (the default)."""
    if not tracing_enabled():
        return
    try:
        durations = spans.durations_ms()
        summary = " ".join(
            f"{name}={ms:.0f}ms"
            for name, ms in sorted(durations.items(), key=lambda kv: -kv[1])
        )
        _TRACE_LOG.info(
            "kind=%s outcome=%s total_ms=%.0f turns=%s ops=%s | %s",
            kind,
            record.get("outcome"),
            record.get("latency_ms", 0.0),
            record.get("model_turns", "-"),
            record.get("op_count", "-"),
            summary,
        )
    except Exception:  # noqa: BLE001
        pass


TRACE_SUFFIX = ".html"
META_SUFFIX = ".meta.json"


@contextmanager
def profile_to_html(kind: str, label: str) -> Iterator[None]:
    """When tracing is on, profile the wrapped op with pyinstrument and write a
    self-contained HTML flamegraph (+ a small `.meta.json` sidecar) to the trace
    dir, served as the rendered page by `/api/traces/{id}`. No-op and zero
    overhead when tracing is disabled — which is the default."""
    if not tracing_enabled() or _profiling.get():
        yield
        return
    try:
        from pyinstrument import Profiler
    except Exception:  # noqa: BLE001 — pyinstrument optional; never block the op
        yield
        return

    token = _profiling.set(True)
    profiler = Profiler(interval=0.001, async_mode="disabled")
    started = time.monotonic()
    profiler.start()
    try:
        yield
    finally:
        try:
            profiler.stop()
            out_dir = default_trace_dir()
            if str(out_dir) != "":
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = int(time.time() * 1000)
                slug = f"{abs(hash(str(label))) % 0x100000:05x}"
                base = f"{stamp}_{kind}_{slug}"
                (out_dir / f"{base}{TRACE_SUFFIX}").write_text(
                    profiler.output_html(), encoding="utf-8"
                )
                (out_dir / f"{base}{META_SUFFIX}").write_text(
                    json.dumps(
                        {
                            "kind": kind,
                            "label": str(label),
                            "latency_ms": round((time.monotonic() - started) * 1000.0, 2),
                        }
                    ),
                    encoding="utf-8",
                )
        except Exception:  # noqa: BLE001
            pass
        finally:
            _profiling.reset(token)
