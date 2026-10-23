"""Who is calling: the session cookie and the middleware that resolves a principal.

Every request leaves `AuthMiddleware` with `request.state.principal` and the
`auth.current_principal` contextvar set, so route handlers and the MCP `@tool`
wrapper inside the mounted transport read the same identity.
"""

from __future__ import annotations

import os
import secrets

import anyio.to_thread
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import auth, store
from ..server import runtime

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


def _asker_may_reach(path: str) -> bool:
    """An asker may call `ask` and nothing else that reads the substrate.

    Tool routes enforce that through their role gate, but the `/api/*` routes
    behind the web UI mostly check only that someone is signed in. So askers
    are kept off `/api/*` here, except for their own account and tokens, and
    a route added later is closed to them until someone decides otherwise."""
    if not path.startswith("/api/") or _is_exempt(path):
        return True
    return path == "/api/me" or path.startswith("/api/me/")


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


class AuthMiddleware:
    # Plain ASGI rather than `BaseHTTPMiddleware`: its `call_next` raises
    # "No response returned." when the inner app returns without responding,
    # which the MCP transport does when the client disconnects mid-call. Here
    # that is just a closed connection, not a 500.
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from urllib.parse import quote

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        raw_token, session_user_id = self._credentials(request)
        principal = await self._resolve(raw_token, session_user_id)
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
                redirect = RedirectResponse(
                    url=f"/auth/logout?next={quote(next_path)}",
                    status_code=302,
                )
                await redirect(scope, receive, send)
                return
            # API + MCP clients get a 401. When the request is for the
            # MCP transport we additionally emit RFC 9728's
            # `WWW-Authenticate` so the client can auto-discover the
            # OAuth dance and prompt the user — this is what makes
            # Claude Desktop's "Add Custom Connector" flow Just Work
            # against Mycelium without anyone pasting a token.
            headers: dict[str, str] = {}
            if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
                base = str(request.base_url).rstrip("/")
                # `scope` tells the client what to ask for without first
                # fetching the metadata document; RFC 6750 §3 makes the
                # challenge authoritative for this request, so a client
                # that reads it needs no second round trip to find out.
                headers["WWW-Authenticate"] = (
                    f'Bearer realm="mycelium", scope="mcp", '
                    f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
                )
            rejection = JSONResponse(
                status_code=401,
                content={"detail": "authentication required"},
                headers=headers,
            )
            await rejection(scope, receive, send)
            return
        if principal is not None and principal.role == "asker":
            if not _asker_may_reach(request.url.path):
                rejection = JSONResponse(
                    status_code=403,
                    content={"detail": "the asker role can only call ask"},
                )
                await rejection(scope, receive, send)
                return
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
        # Carry the MCP session id so the @tool wrapper can find this
        # caller's auto-created draft. Only a 2025-era client has one: the
        # 2026-07-28 revision removed sessions, so a modern MCP request and
        # a REST request both leave this None and the wrapper falls back to
        # a principal-scoped key.
        session_id = request.headers.get("mcp-session-id")
        session_ctx = auth.current_session_id.set(session_id)
        if principal is not None:
            store.set_actor(principal.id)
        try:
            await self.app(scope, receive, send)
        finally:
            store.set_actor(None)
            auth.current_principal.reset(ctx_token)
            auth.current_session_id.reset(session_ctx)

    @staticmethod
    def _credentials(request: Request) -> tuple[str | None, str | None]:
        """Pull the raw credentials off the request. Pure — no I/O, so it stays
        on the event loop and tells the caller whether there is anything worth
        a database round trip at all.

        Starlette session is exposed as a dict on `request.session` once
        SessionMiddleware has run. The presence check is defensive for
        early-boot edge cases.
        """
        raw = auth.parse_bearer(request.headers.get("authorization"))
        try:
            user_id = request.session.get("user_id")
        except AssertionError:
            user_id = None
        return raw, user_id

    @staticmethod
    def _lookup(raw: str | None, user_id: str | None) -> auth.Principal | None:
        """Resolve credentials against the auth DB. Blocking: a token hit also
        WRITES (last_used_at), so under concurrent traffic this waits on the
        single writer — which is why `_resolve` keeps it off the event loop."""
        try:
            conn = runtime._auth_db()
        except RuntimeError:
            # Lifespan hasn't run (e.g. ASGI tests hitting the app
            # without the context manager), so the auth store isn't
            # configured yet. Treat as no credentials.
            return None
        if raw is not None:
            # resolve_token bumps last_used_at; own that write here since
            # the auth layer is the unit of work for the token lookup.
            with store.transaction(conn):
                principal = auth.resolve_token(conn, raw)
            if principal is not None:
                return principal
        return auth.resolve_session_user(conn, user_id)

    @classmethod
    async def _resolve(
        cls, raw: str | None, user_id: str | None
    ) -> auth.Principal | None:
        """An anonymous request carries nothing to look up, so it never touches
        the DB and never needs a worker thread — which is what keeps the health
        probe cheap even while every thread is busy serving tool calls."""
        if raw is None and not user_id:
            return None
        return await anyio.to_thread.run_sync(cls._lookup, raw, user_id)
