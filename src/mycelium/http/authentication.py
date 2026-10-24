"""Who is calling: the session cookie and the middleware that resolves a principal.

Every request leaves `AuthMiddleware` with `request.state.principal` and the
`auth.current_principal` contextvar set, so route handlers and the MCP `@tool`
wrapper inside the mounted transport read the same identity.
"""

from __future__ import annotations

import functools
import os
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import auth, hosts, request_timing, store
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
    # The UI's build output and fonts carry no data, and serving them
    # without a session is what lets a shared cache keep them. The public
    # /connect page uses the fonts too.
    "/ui/assets/",
    "/ui/fonts/",
    "/favicon",
    "/docs",  # FastAPI swagger
    "/openapi.json",
    "/redoc",
    # An upload link is its own credential (see `mycelium.media`).
    "/api/media/uploads/",
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


def session_cookie_secure() -> bool:
    """Whether the session cookie gets the `Secure` flag.

    Deployments terminate TLS at a proxy, so the request scheme says nothing;
    the configured public address does. Without the flag the browser also
    sends the cookie on a plain-http request, such as the one that precedes
    the proxy's redirect to https, where anyone on the network can read it."""
    public = os.environ.get("MYCELIUM_PUBLIC_URL") or os.environ.get(
        "MYCELIUM_OIDC_REDIRECT_URI"
    )
    return (public or "").strip().lower().startswith("https://")


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _is_cross_origin(request: Request) -> bool:
    """Whether a browser sent this request on behalf of another origin.

    `Sec-Fetch-Site` is set by every current browser and cannot be forged by
    a page. `same-site` counts as foreign: a sibling host shares the
    `SameSite=Lax` cookie but not our trust. Older browsers send only
    `Origin`, compared by host since TLS ends at the proxy. Requests carrying
    neither header are not from a browser page."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc != request.headers.get("host", "")


def _is_exempt(path: str) -> bool:
    if path in _AUTH_EXEMPT_PATHS:
        return True
    # `/ui/assets/../index.html` would otherwise reach a gated file through
    # an exempt prefix.
    return ".." not in path and any(
        path.startswith(prefix) for prefix in _AUTH_EXEMPT_PREFIXES
    )


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
        # A browser attaches the session cookie by itself, and with auth off
        # there is no credential at all, so neither proves the page that sent
        # the request is ours. A bearer token does: a page on another origin
        # cannot add an Authorization header without a CORS grant.
        if (
            request.method not in _SAFE_METHODS
            and raw_token is None
            and (principal is not None or not auth.is_enabled())
            and _is_cross_origin(request)
        ):
            rejection = JSONResponse(
                status_code=403,
                content={"detail": "cross-origin request refused"},
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
        """Resolve credentials against the auth DB. Blocking, and a token hit
        now and then writes its `last_used_at`, which is why `_resolve` keeps
        it off the event loop."""
        try:
            conn = runtime._auth_db()
        except RuntimeError:
            # Lifespan hasn't run (e.g. ASGI tests hitting the app
            # without the context manager), so the auth store isn't
            # configured yet. Treat as no credentials.
            return None
        if raw is not None:
            principal = auth.resolve_token(conn, raw)
            if principal is not None:
                auth.record_token_use(conn, raw)
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
        return await request_timing.run_sync(
            functools.partial(cls._lookup, raw, user_id)
        )


# Nothing Mycelium serves is meant to be embedded. Framed by another page, the
# OAuth consent screen or a curation button can be overlaid with a decoy and
# clicked through. A same-site page gets the session cookie even in a frame.
_SECURITY_HEADERS = (
    ("x-frame-options", "DENY"),
    ("content-security-policy", "frame-ancestors 'none'"),
    ("x-content-type-options", "nosniff"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS:
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Load balancers probe by instance address, which no allowlist names, and the
# probe needs no credential, so a rebound page gains nothing here either.
_HOST_CHECK_EXEMPT = frozenset({"/api/server-info"})


class HostAllowlistMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"] not in _HOST_CHECK_EXEMPT
            and hosts.enforced()
            and not hosts.is_allowed(Headers(scope=scope).get("host"))
        ):
            rejection = JSONResponse(
                status_code=421, content={"detail": "invalid host header"}
            )
            await rejection(scope, receive, send)
            return
        await self.app(scope, receive, send)
