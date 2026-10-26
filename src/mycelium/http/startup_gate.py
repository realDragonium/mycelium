"""Answering while the server starts in the background.

`mycelium-http` starts listening before migrations and index rebuilds finish,
so a health check or a browser can see that it is starting rather than find
nothing listening. Until startup is ready this gate answers every request
itself, before any middleware that reads a database: `/api/server-info` with
the startup state, a browser navigation with a page that reloads itself, and
everything else with a 503.

`/api/server-info` answers 200 while startup is still running and 503 only
once it failed. It is the load balancer's liveness check, and a one-off index
rebuild can outlast any grace period; a 503 there gets the task killed and the
rebuild restarted from scratch.
"""

from __future__ import annotations

import html

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..server import startup
from .authentication import _is_browser_navigation

RETRY_AFTER_S = 5


class StartupGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        current = startup.status()
        if scope["type"] != "http" or current is None or current.state == "ready":
            await self.app(scope, receive, send)
            return
        await _starting(Request(scope), current)(scope, receive, send)


def describe(current: startup.Startup) -> str:
    if current.state == "failed":
        return f"Mycelium failed to start: {current.detail}"
    step = f": {current.detail}" if current.detail else ""
    return f"Mycelium is starting up ({current.state}{step})."


def _starting(request: Request, current: startup.Startup) -> Response:
    headers = {"Retry-After": str(RETRY_AFTER_S)}
    state = {
        "state": current.state,
        "detail": describe(current),
        "elapsed_s": current.elapsed_s,
    }
    if request.url.path == "/api/server-info":
        status_code = 503 if current.state == "failed" else 200
        return JSONResponse(status_code=status_code, content=state, headers=headers)
    if _is_browser_navigation(request):
        refresh = (
            ""
            if current.state == "failed"
            else f'<meta http-equiv="refresh" content="{RETRY_AFTER_S}">'
        )
        page = (
            f'<!doctype html><html><head><meta charset="utf-8">{refresh}'
            "<title>Mycelium is starting</title></head>"
            '<body style="font-family:system-ui,sans-serif;margin:4rem auto;'
            'max-width:36rem;line-height:1.5">'
            f"<h1>Mycelium is {'not running' if current.state == 'failed' else 'starting'}</h1>"
            f"<p>{html.escape(describe(current))}</p>"
            f"<p>Running for {current.elapsed_s:.0f} s."
            f"{'' if current.state == 'failed' else ' This page reloads by itself.'}"
            "</p></body></html>"
        )
        return HTMLResponse(page, status_code=503, headers=headers)
    return JSONResponse(
        status_code=503,
        content={**state, "detail": f"{describe(current)} Try again shortly."},
        headers=headers,
    )
