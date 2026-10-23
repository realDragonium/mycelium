"""FastAPI HTTP transport — auto-generated mirror of every registered tool.

Every function in `server.TOOLS` (i.e., everything decorated with `@tool`)
is exposed as an endpoint here, including the tools `server.MCP_TOOLS`
keeps off the MCP surface. Path is the kebab-case tool name; method
is GET when the tool takes no args, POST otherwise. The request body's
Pydantic schema is derived from the function signature.

Add a tool to a module in `mycelium/server/` with `@tool`, list it in
`mycelium.server.__all__` (its position there is its place in every listing),
and you'll find it here too at `/<kebab-case-name>` after a server restart —
no edits needed in this file.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .. import (
    alias_suggestions,
    auth,
    documentation_profiles,
    github_connect,
    names_workspace,
    oauth_server,
    oidc,
    server,
    tracing,
)
from ..docgen.publication import BothSidesEdited
from ..server import registry
from . import (
    account,
    admin,
    documentation,
    draft_review,
    drafts,
    gaps,
    history,
    names,
    prompt_texts,
    settings,
    substrate,
    tool_routes,
    traces,
    webui,
)
from .authentication import AuthMiddleware, _session_secret

# Build the streamable-HTTP sub-app once at import time. Transport
# configuration lives here rather than on the MCPServer: `MCPServer` holds
# the server's identity and tools, the app builder decides how they are
# served. The same endpoint answers both MCP protocol revisions — a
# 2025-era client's `initialize` handshake and a 2026-07-28 client's
# self-describing requests — with nothing to configure.
_MCP_SUBAPP = server.mcp.streamable_http_app(
    transport_security=registry._build_transport_security(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser()
    server.init(data_dir)
    # Start the MCP session manager under our lifespan. A mounted sub-app's
    # own lifespan never runs, so nothing else initialises it — without this
    # every `/mcp` call fails with "Task group is not initialized".
    #
    # `MYCELIUM_DISABLE_MCP_HTTP=1` skips this; the test suite sets the flag
    # because `StreamableHTTPSessionManager.run()` may only be called once
    # per instance, and a test that brings up a second TestClient against
    # this module would otherwise raise on the second lifespan entry. The
    # REST mirror and the auth-gated /api/* endpoints work without the
    # manager; only `/mcp` JSON-RPC needs it.
    if os.environ.get("MYCELIUM_DISABLE_MCP_HTTP") == "1":
        yield
        return
    async with server.mcp.session_manager.run():
        yield


app = FastAPI(title="Mycelium", lifespan=lifespan)


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(auth.RoleRequired)
async def _role_required_handler(
    request: Request, exc: auth.RoleRequired
) -> JSONResponse:
    """The `@tool` wrapper's role gate rejects with `RoleRequired` — reached
    when a call arrives by a route that did not already run `_enforce_role`.
    That's a deliberate 403, not a server fault, and the message names the
    role required."""
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(Exception)
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


app.exception_handler(BothSidesEdited)(documentation._both_sides_edited_handler)


app.exception_handler(documentation_profiles.Conflict)(prompt_texts._profile_conflict)


app.exception_handler(names_workspace.Conflict)(names._names_conflict)
app.exception_handler(alias_suggestions.Conflict)(names.alias_suggestion_conflict)


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
    https_only=False,  # local dev runs on http
)

app.include_router(oidc.router)
app.include_router(oauth_server.router)
app.include_router(github_connect.router)
app.include_router(tool_routes.router)
app.include_router(history.router)
app.include_router(substrate.router)
app.include_router(gaps.router)
app.include_router(traces.router)
app.include_router(account.router)
app.include_router(names.router)
app.include_router(prompt_texts.router)
app.include_router(settings.router)
app.include_router(draft_review.router)
app.include_router(documentation.router)
app.include_router(drafts.router)
app.include_router(admin.router)
app.include_router(webui.router)


# MCP-over-HTTP is mounted at the bottom of this file so it doesn't
# shadow more-specific routes; search for "MCP transport mount" below.


app.mount("/ui", StaticFiles(directory=str(webui._UI_DIR), html=True), name="ui")


# --- MCP transport mount --------------------------------------------------
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
app.mount("/", _MCP_SUBAPP)


def main() -> None:
    # Local-dev convenience: read a `.env` from the working dir. A no-op in
    # deploy — ECS/systemd inject env before the process starts, and
    # load_dotenv never overrides an already-set variable.
    load_dotenv()
    host = os.environ.get("MYCELIUM_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("MYCELIUM_HTTP_PORT", "8765"))
    uvicorn.run(app, host=host, port=port)
