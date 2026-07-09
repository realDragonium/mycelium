"""FastAPI HTTP transport — auto-generated mirror of the MCP tool surface.

Every function in `server.TOOLS` (i.e., everything decorated with `@tool`)
is exposed as an endpoint here. Path is the kebab-case tool name; method
is GET when the tool takes no args, POST otherwise. The request body's
Pydantic schema is derived from the function signature.

Add a tool in `server.py` with `@tool` and you'll find it here too at
`/<kebab-case-name>` after a server restart — no edits needed in this file.
"""

import asyncio
import inspect
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, create_model
from pydantic import Field as PydField
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import auth, connect_page, oauth_server, oidc, server, store, tracing

# Build FastMCP's streamable-HTTP sub-app once at import time. The
# sub-app owns a session manager that can only be started once per
# instance — building per-request or per-test would explode.
_MCP_SUBAPP = server.mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser()
    server.init(data_dir)
    # Compose the MCP sub-app's lifespan (session manager startup) with
    # ours so the mounted /mcp endpoint can accept connections.
    #
    # `MYCELIUM_DISABLE_MCP_HTTP=1` skips this; the test suite sets the
    # flag because FastMCP's session manager is a process-singleton
    # with run-once semantics, and a test that brings up multiple
    # TestClient instances against the same module would otherwise
    # explode on the second lifespan entry. The MCP REST mirror and
    # the auth-gated /api/* endpoints still work without the manager;
    # only `/mcp` JSON-RPC needs it.
    if os.environ.get("MYCELIUM_DISABLE_MCP_HTTP") == "1":
        yield
        return
    async with _MCP_SUBAPP.router.lifespan_context(_MCP_SUBAPP):
        yield


app = FastAPI(title="Mycelium", lifespan=lifespan)


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort capture for any error that isn't a deliberate 4xx. Emits one
    structured `MYCELIUM_ERROR` line (→ stderr → CloudWatch, where a metric
    filter counts it) and returns an opaque 500. More specific handlers win, so
    ValueError keeps its 400 and FastAPI's HTTPException/validation responses are
    untouched — only genuinely unexpected failures land here."""
    tracing.emit_error(
        where="http",
        exc=exc,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# --- auth middleware ------------------------------------------------------
# Resolves a `Principal` for every request and stashes it on
# `request.state.principal`. When `MYCELIUM_AUTH=off` (default), an
# unauthenticated request gets the synthetic local-admin so nothing
# downstream has to special-case the disabled-auth path. When auth is
# on, a request that fails to resolve any credential is rejected with
# 401 — except for paths in `_AUTH_EXEMPT`, which must stay reachable
# to allow the user to log in or load the public assets.
#
# Also propagates the principal's id into `store.set_actor` so the
# substrate's audit columns (`created_by` / `updated_by`) reflect the
# right identity for the request's writes. Cleared at the end so a
# background thread can't accidentally inherit a stale actor.

_AUTH_EXEMPT_PREFIXES = (
    "/auth/",  # login / callback / logout
    "/static/",
    "/favicon",
    "/docs",  # FastAPI swagger
    "/openapi.json",
    "/redoc",
)
_AUTH_EXEMPT_PATHS = {
    "/",
    "/connect",
    "/api/server-info",
    # OAuth discovery + DCR + token exchange are unauthenticated by
    # design. /authorize is also exempt but redirects to /auth/login
    # internally when no session exists.
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/register",
    "/token",
    "/authorize",
    "/authorize/decide",
}


def _session_secret() -> str:
    """Pull the session cookie signing key. With auth disabled we
    generate an ephemeral per-process key — sessions don't survive a
    restart, which is fine because the local-admin path doesn't need
    them. With auth on, the env var is required so cookies stay valid
    across restarts (and to avoid an obvious dev mistake)."""
    secret = os.environ.get("MYCELIUM_SESSION_SECRET")
    if secret:
        return secret
    if auth.is_enabled():
        raise RuntimeError("MYCELIUM_SESSION_SECRET must be set when MYCELIUM_AUTH=on")
    return secrets.token_urlsafe(32)


def _is_exempt(path: str) -> bool:
    if path in _AUTH_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _AUTH_EXEMPT_PREFIXES)


def _is_browser_navigation(request: Request) -> bool:
    """Heuristic: did this request come from a human typing in the URL
    bar or clicking a link, vs. a JS fetch / API client / MCP client?

    Browser navigations send `Accept: text/html` and not
    `Authorization: Bearer`. fetch() and MCP clients send JSON-leaning
    accepts and/or a bearer. Used to decide whether an unauthenticated
    request gets redirected to /auth/login (browser) or a 401 JSON
    (API/MCP client).
    """
    if request.headers.get("authorization"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from urllib.parse import quote

        principal = self._resolve(request)
        if principal is None and auth.is_enabled() and not _is_exempt(request.url.path):
            if _is_browser_navigation(request):
                # Send the user through logout-then-login, not straight to
                # login. A missing/invalid Mycelium session does NOT mean
                # Auth0's session is gone — it's shared with our other apps
                # on the same tenant, so a bare /auth/login would silently
                # re-auth the user as whatever account that SSO session
                # holds (wrong identity; provisioning keys on email).
                # /auth/logout clears the Auth0 cookie first, then bounces
                # back to /auth/login for a clean login. The next= param
                # round-trips so the post-login redirect lands here.
                next_path = request.url.path
                if request.url.query:
                    next_path += "?" + request.url.query
                return RedirectResponse(
                    url=f"/auth/logout?next={quote(next_path)}",
                    status_code=302,
                )
            # API + MCP clients get a 401. When the request is for the
            # MCP transport we additionally emit RFC 9728's
            # `WWW-Authenticate` so the client can auto-discover the
            # OAuth dance and prompt the user — this is what makes
            # Claude Desktop's "Add Custom Connector" flow Just Work
            # against Mycelium without anyone pasting a token.
            headers = {}
            if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
                base = str(request.base_url).rstrip("/")
                headers["WWW-Authenticate"] = (
                    f'Bearer realm="mycelium", '
                    f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "authentication required"},
                headers=headers,
            )
        # Fall back to the synthetic admin only when auth is disabled —
        # never when auth is on but the path is exempt, so exempt paths
        # don't accidentally see a fake admin and grant write power.
        if principal is None:
            principal = auth.LOCAL_ADMIN if not auth.is_enabled() else None

        request.state.principal = principal
        # Make the principal visible to code that doesn't see the
        # Request object — specifically the MCP `@tool` wrapper, which
        # is invoked from inside the mounted Starlette streamable-HTTP
        # app. The contextvar is task-local, so concurrent requests
        # don't see each other's principal.
        ctx_token = auth.current_principal.set(principal)
        # Carry the MCP session id (set by FastMCP's streamable HTTP
        # transport after `initialize`) so the @tool wrapper can find
        # this caller's auto-created draft. Non-MCP HTTP requests just
        # leave it None — they have no drafts to auto-target.
        session_id = request.headers.get("mcp-session-id")
        session_ctx = auth.current_session_id.set(session_id)
        if principal is not None:
            store.set_actor(principal.id)
        try:
            return await call_next(request)
        finally:
            store.set_actor(None)
            auth.current_principal.reset(ctx_token)
            auth.current_session_id.reset(session_ctx)

    @staticmethod
    def _resolve(request: Request) -> auth.Principal | None:
        conn = server._auth_conn
        if conn is None:
            # Lifespan hasn't run (e.g. ASGI tests hitting the app
            # without the context manager). Treat as no credentials.
            return None
        raw = auth.parse_bearer(request.headers.get("authorization"))
        if raw is not None:
            # resolve_token bumps last_used_at; own that write here since
            # the auth layer is the unit of work for the token lookup.
            with store.transaction(conn):
                principal = auth.resolve_token(conn, raw)
            if principal is not None:
                return principal
        # Starlette session is exposed as a dict on `request.session`
        # once SessionMiddleware has run. The presence check is defensive
        # for early-boot edge cases.
        try:
            user_id = request.session.get("user_id")
        except AssertionError:
            user_id = None
        return auth.resolve_session_user(conn, user_id)


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


def _path_for(func_name: str) -> str:
    return "/" + func_name.replace("_", "-")


def _model_name_for(func_name: str) -> str:
    return func_name.title().replace("_", "") + "Body"


# Tool authorization — convention based. The classification helpers
# live in `auth` so the MCP `@tool` wrapper (server.py) can apply the
# same policy without depending on the HTTP layer.


def _enforce_role(request: Request, required: str) -> None:
    p = getattr(request.state, "principal", None)
    if p is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="authentication required")
    if not auth.principal_satisfies(p, required):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail=f"this operation requires the {required} role",
        )


def _make_post_handler(
    func: Callable[..., Any], BodyModel: type, required_role: str
) -> Callable[..., Any]:
    def handler(body, request: Request):
        _enforce_role(request, required_role)
        return func(**body.model_dump())

    handler.__name__ = func.__name__
    handler.__doc__ = func.__doc__
    handler.__annotations__ = {"body": BodyModel, "request": Request}
    return handler


# Tools whose answer can take longer than an idle connection is allowed to live.
# The path in front of us is Cloudflare -> ALB -> task; the ALB drops a
# connection after 60s of *no bytes flowing* (its default idle timeout), and a
# single multi-turn `ask` can exceed that. The fix is to keep bytes moving: the
# handler below drips whitespace while the blocking tool runs, then emits the
# normal JSON body last. Leading whitespace is ignored by `JSON.parse`, so the
# browser (and any `res.json()` caller) parses the result unchanged — no client
# edit needed.
_STREAMING_TOOLS = {"ask"}
# Finish-fast window: if the tool returns (or raises) within this, respond
# normally so success and 4xx/5xx keep their real HTTP status — identical to
# every other endpoint. Only genuinely slow calls fall through to streaming.
_STREAM_GRACE_SECONDS = 5.0
# Heartbeat cadence — comfortably under the ALB's 60s idle timeout.
_STREAM_HEARTBEAT_SECONDS = 15.0


def _make_streaming_post_handler(
    func: Callable[..., Any], BodyModel: type, required_role: str
) -> Callable[..., Any]:
    async def handler(body, request: Request):
        _enforce_role(request, required_role)
        kwargs = body.model_dump()
        # Run the blocking tool in a worker thread. asyncio.to_thread copies the
        # current contextvars (incl. the resolved principal) into the thread.
        task = asyncio.ensure_future(asyncio.to_thread(func, **kwargs))

        done, _ = await asyncio.wait({task}, timeout=_STREAM_GRACE_SECONDS)
        if task in done:
            # Returning .result() here re-raises any error, so FastAPI's
            # exception handlers still produce the correct 4xx/5xx — the
            # fast path is byte-for-byte the old behaviour.
            return JSONResponse(task.result())

        async def gen():
            while True:
                done, _ = await asyncio.wait({task}, timeout=_STREAM_HEARTBEAT_SECONDS)
                if task in done:
                    break
                yield b" "  # keepalive: ignored by JSON.parse on the client
            try:
                yield json.dumps(task.result()).encode()
            except Exception as exc:  # noqa: BLE001
                # Headers (200) are already on the wire, so a late failure can
                # only come back as a JSON error body, not a status code.
                yield json.dumps({"detail": str(exc)}).encode()

        return StreamingResponse(gen(), media_type="application/json")

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
_TRACED_TOOLS = {"search_statements", "survey_statements", "grep_statements"}


def _make_traced_post_handler(
    func: Callable[..., Any], BodyModel: type, required_role: str
) -> Callable[..., Any]:
    def handler(body, request: Request):
        _enforce_role(request, required_role)
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
    def handler(request: Request):
        _enforce_role(request, required_role)
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

    if not sig.parameters:
        app.get(path, name=func.__name__)(_make_get_handler(func, required))
        return

    if (
        len(sig.parameters) == 1
        and "draft_id" in sig.parameters
        and sig.parameters["draft_id"].default is None
    ):
        app.get(path, name=func.__name__)(_make_get_handler(func, required))

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        annotation = hints.get(name, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    BodyModel = create_model(_model_name_for(func.__name__), **fields)
    if func.__name__ in _STREAMING_TOOLS:
        make = _make_streaming_post_handler
    elif func.__name__ in _TRACED_TOOLS:
        make = _make_traced_post_handler
    else:
        make = _make_post_handler
    app.post(path, name=func.__name__)(make(func, BodyModel, required))


for _func in server.TOOLS:
    _register(_func)


# MCP-over-HTTP is mounted at the bottom of this file so it doesn't
# shadow more-specific routes; search for "MCP transport mount" below.


# --- HTTP-only endpoints (NOT exposed via MCP) ----------------------------
# These are read-side helpers for the bundled web UI. They are deliberately
# not registered with @tool because they're shaped for a browser, not for an
# AI consumer composing primitives over MCP.


@app.get("/api/data")
def get_substrate_dump() -> dict[str, Any]:
    """Dump the entire substrate in the shape the UI expects.

    See `store.substrate_dump` for the returned shape.
    """
    return store.substrate_dump(store.substrate_connection())


_ALLOWED_OPS = {"create", "update", "link", "attach"}
_ALLOWED_KINDS = {
    "entity",
    "statement",
    "name",
    "statement_link",
    "entity_link",
    "entity_statement_link",
}


def _csv_set(raw: str | None, allowed: set[str]) -> set[str]:
    if not raw:
        return set()
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return parts & allowed


@app.get("/api/history")
def get_history(
    limit: int = 50,
    offset: int = 0,
    op: str | None = None,
    target_kind: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Recent creates/updates/links/attachments from the live substrate,
    newest first.

    Sourced from the `created_at`/`updated_at` columns on the live tables
    — not from the attached history log — so deletes are invisible (the
    row is gone). Each event has `at`, `op`, `target_kind`, `target_id`,
    `actor`. The UI resolves rich detail (text, neighbors) from the
    `/api/data` snapshot.

    Query params:
      - op: comma-separated subset of {create,update,link,attach}
      - target_kind: comma-separated subset of the target kinds
      - q: case-insensitive substring match on target_id
    """
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    ops = _csv_set(op, _ALLOWED_OPS)
    kinds = _csv_set(target_kind, _ALLOWED_KINDS)
    query = (q or "").strip()

    rows, total = store.activity_feed(
        store.substrate_connection(),
        limit=limit,
        offset=offset,
        ops=ops,
        kinds=kinds,
        query=query,
    )

    events = [
        {
            "event_id": f"{r['target_kind']}:{r['target_id']}:{r['op']}:{r['at']}",
            "at": r["at"],
            "actor": r["actor"],
            "op": r["op"],
            "target_kind": r["target_kind"],
            "target_id": r["target_id"],
        }
        for r in rows
    ]
    return {"events": events, "total": total, "limit": limit, "offset": offset}


# --- account & token endpoints --------------------------------------------
# Used by the bundled UI's settings page. Authenticated principal is read
# from `request.state.principal`, which the middleware populates from a
# session cookie, a bearer token, or the synthetic local-admin when auth
# is off. The synthetic principal is allowed to mint tokens too — handy
# in single-user local mode for bootstrapping an MCP client without ever
# enabling auth.


def _require_principal(request: Request) -> auth.Principal:
    p = getattr(request.state, "principal", None)
    if p is None:
        # Should be unreachable: middleware either sets a principal or
        # returns 401 itself. Defensive in case of future middleware
        # reordering.
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="authentication required")
    return p


def _serialize_token_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "scope": row["scope"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


# --- knowledge gaps -------------------------------------------------------
# Free-form reports flagged by callers (humans via the UI, agents via
# the report_knowledge_gap MCP tool). The reads/lists are useful to
# every authenticated user; marking resolved/dismissed too. Admins can
# hard-delete via direct DB if needed; the UI doesn't expose it.


def _serialize_gap(row) -> dict[str, Any]:
    if row["resolved_at"]:
        status = "resolved"
    elif row["dismissed_at"]:
        status = "dismissed"
    else:
        status = "open"
    return {
        "id": row["id"],
        "text": row["text"],
        "status": status,
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
        "dismissed_at": row["dismissed_at"],
        "dismissed_by": row["dismissed_by"],
    }


@app.get("/api/knowledge-gaps")
def list_knowledge_gaps(request: Request, status: str | None = None) -> dict[str, Any]:
    """List gap reports.

    `status` query param filters to `open` / `resolved` / `dismissed`
    (or `all`, the default — returns everything ordered newest first).
    The status column is virtual: derived from which terminal
    timestamp is set.
    """
    _require_principal(request)
    conn = store.substrate_connection()
    assert conn is not None
    status = status or "all"
    if status not in ("all", "open", "resolved", "dismissed"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, resolved, dismissed",
        )
    rows = store.list_knowledge_gaps(conn, status=status)
    return {"gaps": [_serialize_gap(r) for r in rows]}


class GapUpdateBody(BaseModel):
    # One of:
    #   {"action": "resolve"}    → set resolved_at + resolved_by
    #   {"action": "dismiss"}    → set dismissed_at + dismissed_by
    #   {"action": "reopen"}     → clear both terminal timestamps
    action: str


@app.patch("/api/knowledge-gaps/{gap_id}")
def update_knowledge_gap(
    gap_id: str, body: GapUpdateBody, request: Request
) -> dict[str, Any]:
    p = _require_principal(request)
    conn = store.substrate_connection()
    assert conn is not None
    if store.get_knowledge_gap(conn, gap_id) is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="gap not found")
    if body.action not in ("resolve", "dismiss", "reopen"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="action must be one of: resolve, dismiss, reopen",
        )
    with store.transaction(conn):
        updated = store.set_knowledge_gap_status(conn, gap_id, body.action, p.id)
    return {"gap": _serialize_gap(updated)}


# --- pending mentions (suspect-match review) -------------------------------
# A statement matched a short/common ("suspect") entity name, which is too
# ambiguous to auto-link, so it is held here for per-occurrence human
# approval. This is the review surface for derived mentions. It is HTTP-only
# by design — never an MCP tool — so the substrate's write API gives no hint
# that mentions are derived. Approving materializes the real mention.


def _serialize_pending_mention(row) -> dict[str, Any]:
    if row["approved_at"]:
        status = "approved"
    elif row["rejected_at"]:
        status = "rejected"
    else:
        status = "open"
    return {
        "id": row["id"],
        "statement_id": row["statement_id"],
        "statement_text": row["statement_text"],
        "statement_kind": row["statement_kind"],
        "name_id": row["name_id"],
        "name": row["name"],
        "entity_id": row["entity_id"],
        "status": status,
        "created_at": row["created_at"],
        "approved_at": row["approved_at"],
        "rejected_at": row["rejected_at"],
    }


@app.get("/api/pending-mentions")
def list_pending_mentions(
    request: Request, status: str | None = None, limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    """Suspect mention matches awaiting review.

    `status` filters to open / approved / rejected / all (default open). Each
    row carries the statement text and the suspect name so a reviewer can
    judge whether this occurrence is a real reference to the entity.
    """
    _require_principal(request)
    conn = store.substrate_connection()
    assert conn is not None
    status = status or "open"
    if status not in ("open", "approved", "rejected", "all"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="status must be one of: open, approved, rejected, all",
        )
    rows = store.list_pending_mentions(conn, status=status, limit=limit, offset=offset)
    return {"pending_mentions": [_serialize_pending_mention(r) for r in rows]}


class PendingMentionUpdateBody(BaseModel):
    # {"action": "approve"} → materialize the mention; {"action": "reject"} → drop it.
    action: str


@app.patch("/api/pending-mentions/{pending_id}")
def update_pending_mention(
    pending_id: int, body: PendingMentionUpdateBody, request: Request
) -> dict[str, Any]:
    """Approve (materialize the mention) or reject (write nothing) one
    suspect occurrence. The principal is stamped as approved_by/rejected_by
    via the per-request actor."""
    _require_principal(request)
    conn = store.substrate_connection()
    assert conn is not None
    if body.action not in ("approve", "reject"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400, detail="action must be one of: approve, reject"
        )
    with store.transaction(conn):
        if body.action == "approve":
            ok = store.approve_pending_mention(conn, pending_id)
        else:
            ok = store.reject_pending_mention(conn, pending_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404, detail="pending mention not found or already resolved"
        )
    row = store.get_pending_mention(conn, pending_id)
    return {
        "resolved": True,
        "id": pending_id,
        "status": "approved" if row["approved_at"] else "rejected",
    }


@app.get("/api/entity-positions", include_in_schema=False)
def get_entity_positions(request: Request) -> Any:
    """Stream the baked entity layout JSON.

    The bake artifact lives in the data dir (next to the substrate
    DB), not the source tree — so deploys can't accidentally wipe
    it and the systemd hardening's read-only-system protection
    permits the bake to write. The UI fetches from this route
    instead of a static /ui/data/ path; the URL is stable even if
    we change where the file lives on disk.
    """
    from fastapi.responses import FileResponse
    from fastapi.responses import JSONResponse as _JSON

    from . import layout_baker

    path = layout_baker.output_path()
    if path is None or not path.exists():
        return _JSON(
            status_code=404, content={"detail": "entity positions not baked yet"}
        )
    return FileResponse(path, media_type="application/json")


# --- timing traces (pyinstrument flamegraphs) -----------------------------
# When tracing is enabled, each ask / ingest / find run drops a self-contained
# pyinstrument `*.html` flamegraph (+ a `.meta.json` sidecar) under the trace
# dir (see mycelium/tracing.py). `/api/traces` lists them with a `view_url` per
# trace; `GET /api/traces/{id}` serves that trace's HTML so it renders straight
# in the browser — no download, no speedscope.app. Admin-only.
_TRACE_SUFFIX = tracing.TRACE_SUFFIX
_META_SUFFIX = tracing.META_SUFFIX


def _trace_dir() -> Path:
    return tracing.default_trace_dir()


@app.get("/api/traces")
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


@app.get("/api/traces/{trace_id}")
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
@app.get("/api/tracing")
def tracing_status_endpoint(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.tracing_status()


@app.post("/api/tracing/enable")
def tracing_enable(request: Request, minutes: float | None = None) -> Any:
    """Turn tracing on. `?minutes=N` auto-disarms after N minutes."""
    _enforce_role(request, "admin")
    ttl = minutes * 60.0 if minutes and minutes > 0 else None
    return tracing.set_tracing(True, ttl_seconds=ttl)


@app.post("/api/tracing/disable")
def tracing_disable(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.set_tracing(False)


@app.get("/api/server-info")
def get_server_info(request: Request) -> dict[str, Any]:
    """Public-ish discovery endpoint used by the setup help page so the
    UI can render config snippets containing the actual MCP URL the
    client should connect to.

    Exempt from auth (path starts with /api/ but the endpoint itself
    returns no secrets) — but to keep the surface honest we only
    expose data the user would learn just by looking at the address
    bar. No tokens, no env, no internal config.
    """
    base = str(request.base_url).rstrip("/")
    return {
        "base_url": base,
        "mcp_url": f"{base}/mcp",
        "auth_enabled": auth.is_enabled(),
    }


@app.get("/api/me")
def get_me(request: Request) -> dict[str, Any]:
    """Return the current principal. The UI uses this to decide whether
    to show admin-only affordances and whose tokens to list."""
    p = _require_principal(request)
    return {
        "id": p.id,
        "name": p.name,
        "role": p.role,
        "type": p.type,
        "synthetic": p.synthetic,
        "auth_enabled": auth.is_enabled(),
    }


@app.get("/api/me/tokens")
def list_my_tokens(request: Request) -> dict[str, Any]:
    """List the calling user's MCP tokens. Revoked tokens stay in the
    list (UI greys them out) so a user can see what was revoked and
    when — useful when the same label was reused later."""
    p = _require_principal(request)
    conn = server._auth_conn
    assert conn is not None
    rows = auth.list_tokens(conn, auth.owner_id_for(p))
    return {"tokens": [_serialize_token_row(r) for r in rows]}


class CreateTokenBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=80)
    scope: auth.Scope = "writer"


@app.post("/api/me/tokens")
def create_my_token(body: CreateTokenBody, request: Request) -> dict[str, Any]:
    """Mint a new MCP token for the calling user. Scope can't exceed
    the user's current role — the server caps it server-side rather
    than trusting the client.

    Returns the raw token exactly once. The client is expected to copy
    it immediately; it cannot be retrieved later.
    """
    p = _require_principal(request)
    conn = server._auth_conn
    assert conn is not None
    with store.transaction(conn):
        raw, row = auth.mint_own_token(
            conn, principal=p, name=body.name, scope=body.scope
        )
    return {"token": raw, **_serialize_token_row(row)}


@app.delete("/api/me/tokens/{token_id}")
def revoke_my_token(token_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    conn = server._auth_conn
    assert conn is not None
    try:
        with store.transaction(conn):
            auth.revoke_own_token(
                conn, token_id=token_id, owner_id=auth.owner_id_for(p)
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"ok": True}


# --- drafts ---------------------------------------------------------------
# Drafts are pending change sets submitted by drafters (or anyone passing
# an explicit draft_id to a write tool). Curators review and either
# approve (replay ops against the substrate) or reject (drop without
# applying). Status is derived from terminal timestamps + decision, same
# pattern as knowledge_gaps.


def _serialize_draft(row, *, ops=None) -> dict[str, Any]:
    from . import drafts_store

    return drafts_store.serialize_draft(row, ops=ops)


@app.get("/api/drafts")
def list_drafts(request: Request, status: str | None = None) -> dict[str, Any]:
    """List drafts, newest first. `status` filters to one of:
    open / submitted / approved / rejected / withdrawn / all (default).
    """
    _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    status = status or "all"
    if status not in ("all", "open", "submitted", "approved", "rejected", "withdrawn"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, submitted, approved, rejected, withdrawn",
        )
    rows = drafts_store.list_drafts(conn, status=status)
    counts = drafts_store.count_ops_by_draft(conn)
    out = []
    for r in rows:
        d = drafts_store.serialize_draft(r)
        d["op_count"] = counts.get(r["id"], 0)
        out.append(d)
    return {"drafts": out}


@app.get("/api/drafts/{draft_id}")
def get_draft_detail(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    ops = drafts_store.list_ops(conn, draft_id)
    return {"draft": drafts_store.serialize_draft(row, ops=ops)}


class DraftOpEditBody(BaseModel):
    payload: dict[str, Any]


@app.patch("/api/drafts/{draft_id}/ops/{seq}")
def edit_draft_op(
    draft_id: str, seq: int, body: DraftOpEditBody, request: Request
) -> dict[str, Any]:
    """Replace an op's payload. Only valid on open drafts (a submitted
    draft is awaiting review; if the curator wants to tweak it they
    should approve-or-reject and have the drafter re-submit)."""
    _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"cannot edit ops on a {status} draft",
        )
    with store.transaction(conn):
        ok = drafts_store.update_op_payload(conn, draft_id, seq, body.payload)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True}


@app.delete("/api/drafts/{draft_id}/ops/{seq}")
def remove_draft_op_http(draft_id: str, seq: int, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"cannot remove ops from a {status} draft",
        )
    with store.transaction(conn):
        ok = drafts_store.remove_op(conn, draft_id, seq)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True}


class DraftDecisionBody(BaseModel):
    # Only meaningful for /approve and /reject — submit takes no body.
    pass


@app.post("/api/drafts/{draft_id}/submit")
def submit_draft_http(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    if drafts_store.status_for(row) != "open":
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="only open drafts can be submitted",
        )
    with store.transaction(conn):
        drafts_store.set_submitted(conn, draft_id)
    return {"ok": True}


def _enforce_curator(request: Request) -> auth.Principal:
    """Approve/reject require a *real* writer or admin — `_enforce_role`
    routes drafters through too (because the @tool wrapper's drafter
    equivalence makes them satisfy writer), which would let a drafter
    approve their own draft and re-queue every op into a brand new
    auto-draft at replay time. Use the strict rank check instead.
    """
    p = _require_principal(request)
    if not auth.principal_has_real_role(p, "writer"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="approving / rejecting a draft requires the writer or admin role",
        )
    return p


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, request: Request) -> dict[str, Any]:
    """Replay the draft's ops against the substrate as the curator.

    Requires real writer+ (not drafter — see `_enforce_curator`).
    All-or-nothing: a single op failure halts replay and leaves the
    draft in its prior state so the curator can edit and retry.
    """
    p = _enforce_curator(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    try:
        result = server.apply_draft(draft_id)
    except (ValueError, RuntimeError) as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(ex))
    with store.transaction(conn):
        drafts_store.set_decision(conn, draft_id, decision="approved", by=p.id)
    return {"ok": True, **result}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _enforce_curator(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    if drafts_store.status_for(row) not in ("open", "submitted"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="only open or submitted drafts can be rejected",
        )
    with store.transaction(conn):
        drafts_store.set_decision(conn, draft_id, decision="rejected", by=p.id)
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/withdraw")
def withdraw_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    from . import drafts_store

    conn = server._drafts_conn
    assert conn is not None
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    if drafts_store.status_for(row) not in ("open", "submitted"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="only open or submitted drafts can be withdrawn",
        )
    with store.transaction(conn):
        drafts_store.set_decision(conn, draft_id, decision="withdrawn", by=p.id)
    return {"ok": True}


# --- admin: user & invite management --------------------------------------
# All endpoints require `role == admin`. Service accounts (type=service)
# represent third-party agents; they can hold tokens but never log in
# through OIDC.


def _require_admin(request: Request) -> auth.Principal:
    p = _require_principal(request)
    if not p.is_admin:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="admin role required")
    return p


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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
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
    conn = server._auth_conn
    assert conn is not None
    rows = auth.list_invites(conn)
    return {"invites": [_serialize_invite_row(r, request=request) for r in rows]}


class CreateInviteBody(BaseModel):
    email: str = PydField(..., min_length=3, max_length=254)
    role: auth.Role = "writer"


@app.post("/api/admin/invites")
def create_invite(body: CreateInviteBody, request: Request) -> dict[str, Any]:
    admin = _require_admin(request)
    conn = server._auth_conn
    assert conn is not None
    with store.transaction(conn):
        row = auth.create_invite(
            conn, email=body.email, role=body.role, invited_by=admin.id
        )
    return _serialize_invite_row(row, request=request)


@app.delete("/api/admin/invites/{invite_id}")
def revoke_invite(invite_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = server._auth_conn
    assert conn is not None
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


_UI_DIR = Path(__file__).resolve().parent / "ui"
app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")

# Second, parallel UI: the "cockpit" — an AI-native authoring surface
# (Ask / Find / Ingest / Drafts / Coverage) recreated from a Claude Design
# handoff. A static React/Babel bundle like /ui, wired to the live substrate
# through the same endpoints (/api/data, /search-statements, /ask, /ingest,
# /api/drafts, …) via its own api.js bridge. Gated by the same AuthMiddleware
# as /ui — /cockpit is not in the auth-exempt list.
_COCKPIT_DIR = Path(__file__).resolve().parent / "cockpit"
app.mount(
    "/cockpit", StaticFiles(directory=str(_COCKPIT_DIR), html=True), name="cockpit"
)


# Serve the bundles at the bare /ui and /cockpit paths too. Starlette would
# normally redirect /cockpit -> /cockpit/ via redirect_slashes, but the
# catch-all MCP sub-app mounted at "/" below matches /cockpit first, so that
# automatic redirect never fires. Register explicit redirects here, ahead of
# the "/" mount, so visitors can use the clean /ui and /cockpit URLs.
@app.get("/ui", include_in_schema=False)
def _ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/cockpit", include_in_schema=False)
def _cockpit_redirect() -> RedirectResponse:
    return RedirectResponse(url="/cockpit/")


# --- MCP transport mount --------------------------------------------------
# Remote MCP clients (Claude Desktop, Claude Code) connect to
# `https://host/mcp`. FastMCP's streamable-HTTP sub-app exposes `/mcp`
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
