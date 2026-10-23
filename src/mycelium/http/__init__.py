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
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field as PydField
from starlette.middleware.sessions import SessionMiddleware

from .. import (
    alias_suggestions,
    auth,
    connect_page,
    documentation_profiles,
    github_connect,
    names_workspace,
    oauth_server,
    oidc,
    server,
    store,
    tracing,
)
from ..docgen.publication import BothSidesEdited
from ..server import registry, runtime
from . import (
    account,
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
)
from .access import _require_admin
from .account import _serialize_token_row
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


# MCP-over-HTTP is mounted at the bottom of this file so it doesn't
# shadow more-specific routes; search for "MCP transport mount" below.


# --- admin: user & invite management --------------------------------------
# All endpoints require `role == admin`. Service accounts (type=service)
# represent third-party agents; they can hold tokens but never log in
# through OIDC.


def _serialize_user_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "oidc_issuer": row["oidc_issuer"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


@app.get("/api/admin/users")
def list_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_users(conn)
    return {"users": [_serialize_user_row(r) for r in rows]}


class CreateUserBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=120)
    role: auth.Role = "writer"
    type: auth.UserType = "service"
    email: str | None = None


@app.post("/api/admin/users")
def create_user(body: CreateUserBody, request: Request) -> dict[str, Any]:
    """Create a service account (the common case) or a pre-provisioned
    human row. Humans created here still need an invite or a matching
    OIDC bootstrap to actually log in — this endpoint is most useful
    for service accounts whose entire identity is their tokens."""
    admin = _require_admin(request)
    if body.type == "human" and not body.email:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="human users require an email")
    conn = runtime._auth_db()
    with store.transaction(conn):
        user_id = auth.create_user(
            conn,
            name=body.name,
            role=body.role,
            type=body.type,
            email=body.email,
            created_by=admin.id,
        )
    row = auth.get_user(conn, user_id)
    return {"user": _serialize_user_row(row)}


class UpdateUserBody(BaseModel):
    role: auth.Role | None = None
    status: str | None = None  # 'active' | 'suspended'
    name: str | None = None


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id: str, body: UpdateUserBody, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            row = auth.update_user(
                conn,
                user_id,
                role=body.role,
                status=body.status,
                name=body.name,
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"user": _serialize_user_row(row)}


@app.get("/api/admin/users/{user_id}/tokens")
def list_user_tokens(user_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_tokens(conn, user_id)
    return {"tokens": [_serialize_token_row(r) for r in rows]}


class MintTokenBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=80)
    scope: auth.Scope = "writer"


@app.post("/api/admin/users/{user_id}/tokens")
def mint_token_for_user(
    user_id: str, body: MintTokenBody, request: Request
) -> dict[str, Any]:
    """Admin path to mint a token for any user — typically used to
    create the initial token for a freshly-created service account.
    The scope is still capped by the target user's role."""
    _require_admin(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            raw, row = auth.mint_token_for_user(
                conn, user_id=user_id, name=body.name, scope=body.scope
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"token": raw, **_serialize_token_row(row)}


@app.delete("/api/admin/tokens/{token_id}")
def revoke_token_admin(token_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_token(conn, token_id)
    return {"ok": True}


def _serialize_invite_row(row, *, request: Request) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "link": str(request.url_for("accept_invite", token=row["token"])),
    }


@app.get("/api/admin/invites")
def list_invites(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_invites(conn)
    return {"invites": [_serialize_invite_row(r, request=request) for r in rows]}


class CreateInviteBody(BaseModel):
    email: str = PydField(..., min_length=3, max_length=254)
    role: auth.Role = "writer"


@app.post("/api/admin/invites")
def create_invite(body: CreateInviteBody, request: Request) -> dict[str, Any]:
    admin = _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        row = auth.create_invite(
            conn, email=body.email, role=body.role, invited_by=admin.id
        )
    return _serialize_invite_row(row, request=request)


@app.delete("/api/admin/invites/{invite_id}")
def revoke_invite(invite_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_invite(conn, invite_id)
    return {"ok": True}


@app.get("/auth/invite/{token}", name="accept_invite")
def accept_invite(token: str) -> RedirectResponse:
    """Invite landing — bounces to /auth/login, then on to /connect.

    New invitees arrive without knowing anything about Mycelium yet;
    landing them on /connect (with the client-setup steps) is more
    useful than landing them on the substrate graph at /ui/. They can
    still navigate to /ui/ from there once they're authenticated.

    The invite token itself isn't carried through query params — the
    OIDC callback's `find_or_create_user` consumes whichever active
    invite matches the verified email it gets back from the provider.
    Passing the token here was redundant.
    """
    return RedirectResponse(url="/auth/login?next=/connect")


@app.get("/connect", include_in_schema=False)
def _connect_page() -> Any:
    """Standalone setup-guide page. Reachable without loading the main
    UI bundle so users coming straight to this URL (from docs, a chat
    handoff, an admin's email) don't pay for the graph viz they're
    not about to use."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=connect_page.CONNECT_HTML)


@app.get("/", include_in_schema=False)
def _root_redirect() -> RedirectResponse:
    # The substrate viewer at /ui/ is intentionally not the landing
    # page — it's only useful once you're logged in. Visitors land on
    # the connect / setup page instead, which is public and tells them
    # how to authenticate and get a token.
    return RedirectResponse(url="/connect")


# The browser app is built from `frontend/` into `webui/`, which is committed so
# the server runs without Node.
_WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
_UI_DIR = _WEBUI_DIR / "ui"
app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")


# Serve the app at the bare /ui path too. Starlette would normally redirect
# /ui -> /ui/ via redirect_slashes, but the catch-all MCP sub-app mounted at "/"
# below matches /ui first, so that automatic redirect never fires. Register it
# here, ahead of the "/" mount.
@app.get("/ui", include_in_schema=False)
def _ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# /cockpit was a second app, merged into /ui. Old links redirect permanently;
# the browser keeps the #fragment across a redirect, and /ui resolves the
# cockpit's old hash routes.
@app.get("/cockpit", include_in_schema=False)
@app.get("/cockpit/{rest:path}", include_in_schema=False)
def _cockpit_redirect(rest: str = "") -> RedirectResponse:
    return RedirectResponse(url="/ui/", status_code=301)


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
