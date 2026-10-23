"""Timing traces (pyinstrument flamegraphs) and the switch that records them.

When tracing is enabled, each ask / ingest / find run drops a self-contained
pyinstrument `*.html` flamegraph (+ a `.meta.json` sidecar) under the trace
dir (see mycelium/tracing.py). `/api/traces` lists them with a `view_url` per
trace; `GET /api/traces/{id}` serves that trace's HTML so it renders straight
in the browser — no download, no speedscope.app. Admin-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from .. import tracing
from ..request_timing import TimedRoute
from .access import _enforce_role

router = APIRouter(route_class=TimedRoute)


_TRACE_SUFFIX = tracing.TRACE_SUFFIX
_META_SUFFIX = tracing.META_SUFFIX


def _trace_dir() -> Path:
    return tracing.default_trace_dir()


@router.get("/api/traces")
def list_traces(request: Request) -> Any:
    """Recent flamegraph traces for this task, newest first. Each entry's
    `view_url` renders the flamegraph in the browser."""
    _enforce_role(request, "admin")
    d = _trace_dir()
    if not d.exists():
        return {"traces": []}
    files = sorted(
        d.glob(f"*{_TRACE_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:100]
    traces = []
    for p in files:
        trace_id = p.name[: -len(_TRACE_SUFFIX)]
        meta: dict[str, Any] = {}
        meta_path = d / f"{trace_id}{_META_SUFFIX}"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a corrupt sidecar shouldn't hide the rest
                pass
        traces.append(
            {
                "id": trace_id,
                "mtime": p.stat().st_mtime,
                "kind": meta.get("kind"),
                "label": meta.get("label"),
                "latency_ms": meta.get("latency_ms"),
                "view_url": f"/api/traces/{trace_id}",
            }
        )
    return {"traces": traces}


@router.get("/api/traces/{trace_id}")
def get_trace(trace_id: str, request: Request) -> Any:
    """Render one trace's flamegraph — open this URL in a browser."""
    from fastapi.responses import HTMLResponse
    from fastapi.responses import JSONResponse as _JSON

    _enforce_role(request, "admin")
    if "/" in trace_id or "\\" in trace_id or ".." in trace_id:
        return _JSON(status_code=400, content={"detail": "bad trace id"})
    path = _trace_dir() / f"{trace_id}{_TRACE_SUFFIX}"
    if not path.exists():
        return _JSON(status_code=404, content={"detail": "trace not found"})
    return HTMLResponse(path.read_text(encoding="utf-8"))


# --- tracing on/off switch -------------------------------------------------
# Tracing is OFF by default; nothing is written until an admin turns it on for
# a debugging window. `/api/tracing` (status), `/api/tracing/enable?minutes=N`
# (auto-disarms after N minutes if given, else stays on until disabled), and
# `/api/tracing/disable`. Distinct path prefix from `/api/traces` (the files),
# so no route collision.
# Status is a safe GET. The state-changing enable/disable are POST-only: a GET
# toggle would be flippable by a cross-site top-level navigation riding the
# admin's session cookie (CSRF). Flip them with curl + a bearer token, which is
# also CSRF-immune (no ambient cookie):
#   curl -X POST -H "Authorization: Bearer $TOK" "$S/api/tracing/enable?minutes=15"
@router.get("/api/tracing")
def tracing_status_endpoint(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.tracing_status()


@router.post("/api/tracing/enable")
def tracing_enable(request: Request, minutes: float | None = None) -> Any:
    """Turn tracing on. `?minutes=N` auto-disarms after N minutes."""
    _enforce_role(request, "admin")
    ttl = minutes * 60.0 if minutes and minutes > 0 else None
    return tracing.set_tracing(True, ttl_seconds=ttl)


@router.post("/api/tracing/disable")
def tracing_disable(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.set_tracing(False)
