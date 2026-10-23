"""The HTTP app: the REST mirror of every tool, the browser UI's API and the
MCP transport, served by one FastAPI application.

This module only assembles. Each seam owns its routes on an `APIRouter` in a
module beside this one (`tool_routes` generates the mirror of every `@tool`);
here they get the middleware, the app-wide error handlers, the static UI
mount and, last, the MCP sub-app at `/`, which matches every path and so
would shadow any route registered after it.
"""

import argparse
import functools
import os
import sys
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import RequestBodyLimitMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import (
    auth,
    errors,
    github_connect,
    media_formats,
    oauth_server,
    oidc,
    quarantine,
    server,
    tracing,
)
from ..server import registry, startup
from . import (
    account,
    admin,
    audience_routes,
    documentation,
    draft_review,
    drafts,
    gaps,
    health,
    history,
    media,
    names,
    prompt_texts,
    settings,
    substrate,
    tool_routes,
    traces,
    webui,
)
from .authentication import (
    AuthMiddleware,
    HostAllowlistMiddleware,
    SecurityHeadersMiddleware,
    _session_secret,
    session_cookie_secure,
)
from .startup_gate import StartupGate


def _max_body_bytes() -> int:
    """Deployments without a proxy in front have nothing else bounding what a
    caller can make the server hold in memory."""
    raw = (os.environ.get("MYCELIUM_MAX_BODY_BYTES") or "").strip()
    return int(raw) if raw else 4 * 1024 * 1024


class _BodyLimit:
    """The app-wide body limit, except on the routes that take a file: those
    read their body against the media caps, which are larger and can change
    while the app runs."""

    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.limited = RequestBodyLimitMiddleware(app, max_body_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and media.RAW_BODY.match(scope["path"]):
            await self.app(scope, receive, send)
            return
        await self.limited(scope, receive, send)


def _start_in_background(data_dir: Path, on_failure: Callable[[], None]) -> None:
    try:
        server.init(data_dir)
    except BaseException as exc:
        tracing.emit_error(where="startup", exc=exc)
        on_failure()


def create_app(*, on_startup_failure: Callable[[], None] | None = None) -> FastAPI:
    """Build a fresh app, reading its configuration from the environment now.

    Each call gets its own MCP session manager, whose `run()` may only be
    entered once, so every app can go through one lifespan of its own.

    With `on_startup_failure`, the app serves while startup runs on a thread
    (see `StartupGate`) and calls it if startup fails. Without it, as in
    tests, startup completes before the app serves its first request."""
    # Transport configuration lives here rather than on the MCPServer:
    # `MCPServer` holds the server's identity and tools, the app builder
    # decides how they are served. The same endpoint answers both MCP
    # protocol revisions — a 2025-era client's `initialize` handshake and a
    # 2026-07-28 client's self-describing requests — with nothing to configure.
    mcp_subapp = server.mcp.streamable_http_app(
        transport_security=registry._build_transport_security(),
        max_request_body_size=_max_body_bytes(),
    )
    # `streamable_http_app` replaces the server's session manager with a new
    # one on every call; keep the one that belongs to this sub-app.
    session_manager = server.mcp.session_manager

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Before listening: a contradictory policy is a configuration error
        # the operator must fix, not a slow start to wait out.
        auth.check_domain_policy()
        data_dir = Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser()
        if on_startup_failure is None:
            server.init(data_dir)
        else:
            startup.mark_starting()
            threading.Thread(
                target=_start_in_background,
                args=(data_dir, on_startup_failure),
                name="startup",
                daemon=True,
            ).start()
        # Start the MCP session manager under our lifespan. A mounted
        # sub-app's own lifespan never runs, so nothing else initialises it —
        # without this every `/mcp` call fails with "Task group is not
        # initialized". `MYCELIUM_DISABLE_MCP_HTTP=1` serves the REST mirror
        # and /api/* without the `/mcp` endpoint.
        if os.environ.get("MYCELIUM_DISABLE_MCP_HTTP") == "1":
            yield
            return
        async with session_manager.run():
            yield

    app = FastAPI(title="Mycelium", lifespan=lifespan)

    app.exception_handler(ValueError)(_value_error_handler)
    app.exception_handler(errors.Conflict)(_conflict_handler)
    app.exception_handler(auth.RoleRequired)(_role_required_handler)
    app.exception_handler(Exception)(_unhandled_error_handler)
    app.exception_handler(media.TooLarge)(media._too_large)
    app.exception_handler(media_formats.Rejected)(media._rejected)

    # Middleware in Starlette runs in *reverse* registration order (last
    # added wraps the outermost). We want session decoding to happen
    # *before* auth resolution reads from `request.session`, so register
    # AuthMiddleware FIRST (inner) and SessionMiddleware LAST (outer).
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        session_cookie="myc_session",
        same_site="lax",
        https_only=session_cookie_secure(),
    )
    app.add_middleware(_BodyLimit, max_body_size=_max_body_bytes())
    app.add_middleware(HostAllowlistMiddleware)
    # Outside every layer that reads a database, so nothing reaches one
    # mid-startup.
    app.add_middleware(StartupGate)
    # Outermost, so error responses from the layers inside get the headers too.
    app.add_middleware(SecurityHeadersMiddleware)

    app.router.routes.extend(_routes())

    # --- MCP transport mount ----------------------------------------------
    # Remote MCP clients (Claude Desktop, Claude Code) connect to
    # `https://host/mcp`. The streamable-HTTP sub-app exposes `/mcp`
    # at its root, so mounting that sub-app at `/` makes the public path
    # `/mcp` exactly. Mounted last so it can't shadow explicit routes
    # above — Starlette matches routes in registration order, and a
    # zero-prefix mount matches everything.
    #
    # Auth: `AuthMiddleware` is installed on the parent app and applies to
    # mounted sub-apps. It resolves the bearer header into a `Principal`
    # and stashes it in the `current_principal` ContextVar before the
    # JSON-RPC dispatcher inside the sub-app runs. The per-tool role gate
    # in `server.tool` reads that ContextVar.
    app.mount("/", mcp_subapp)
    return app


@functools.cache
def _routes() -> tuple[BaseRoute, ...]:
    """Every route but the MCP mount, built once per process and shared by
    every app. None of them depends on the environment, and FastAPI rebuilds
    each route it includes, which for the tool routes alone costs more than
    the rest of an app build. Being assembled on a bare router, they don't
    see an app's `dependency_overrides`; nothing here uses them."""
    combined = APIRouter()
    for router in (
        oidc.router,
        oauth_server.router,
        github_connect.router,
        tool_routes.router,
        history.router,
        substrate.router,
        gaps.router,
        health.router,
        traces.router,
        account.router,
        names.router,
        audience_routes.router,
        media.router,
        prompt_texts.router,
        settings.router,
        draft_review.router,
        documentation.router,
        drafts.router,
        admin.router,
        webui.router,
    ):
        combined.include_router(router)
    combined.mount(
        "/ui", StaticFiles(directory=str(webui._UI_DIR), html=True), name="ui"
    )
    return tuple(combined.routes)


async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def _conflict_handler(request: Request, exc: errors.Conflict) -> JSONResponse:
    content = {"detail": str(exc)}
    if exc.code is not None:
        content["code"] = exc.code
    return JSONResponse(status_code=409, content=content)


async def _role_required_handler(
    request: Request, exc: auth.RoleRequired
) -> JSONResponse:
    """The `@tool` wrapper's role gate rejects with `RoleRequired` — reached
    when a call arrives by a route that did not already run `_enforce_role`.
    That's a deliberate 403, not a server fault, and the message names the
    role required."""
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort capture for any error that isn't a deliberate 4xx. Emits one
    structured `MYCELIUM_ERROR` line (→ stderr, where a deployment's log-metric
    filter can count it) and returns an opaque 500. More specific handlers win, so
    ValueError keeps its 400 and FastAPI's HTTPException/validation responses are
    untouched — only genuinely unexpected failures land here."""
    tracing.emit_error(
        where="http",
        exc=exc,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@functools.cache
def _default_app() -> FastAPI:
    return create_app()


def __getattr__(name: str) -> FastAPI:
    """`mycelium.http:app`, for uvicorn and other ASGI servers, built on first
    access rather than at import: importing any `mycelium.http` module would
    otherwise fix the app's configuration to whatever the environment held at
    that moment."""
    if name == "app":
        return _default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    # Local-dev convenience: read a `.env` from the working dir. A no-op in
    # deploy — ECS/systemd inject env before the process starts, and
    # load_dotenv never overrides an already-set variable.
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="mycelium-http", description="Serve Mycelium over HTTP."
    )
    parser.add_argument(
        "--quarantine",
        action="store_true",
        help="open a copy of production data safely: no background AI "
        f"workers, draft review or GitHub delivery (same as {quarantine.ENV}=1)",
    )
    if parser.parse_args().quarantine:
        quarantine.enable()
    tracing.configure_logging()
    host = os.environ.get("MYCELIUM_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("MYCELIUM_HTTP_PORT", "8765"))

    def stop() -> None:
        listener.should_exit = True

    listener = uvicorn.Server(
        uvicorn.Config(create_app(on_startup_failure=stop), host=host, port=port)
    )
    listener.run()
    current = startup.status()
    # `started` stays False when the lifespan refused to start, as on a
    # contradictory domain policy.
    if not listener.started or (current is not None and current.state == "failed"):
        sys.exit(1)
