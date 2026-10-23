"""OAuth 2.1 Authorization Server for the MCP transport.

This is what lets Claude Desktop / Claude Code add Mycelium without
the user pasting a token. The flow:

  1. Client hits /mcp without credentials → 401 with a `WWW-Authenticate`
     header pointing at the resource metadata.
  2. Client fetches `/.well-known/oauth-protected-resource` (RFC 9728)
     and discovers the authorization server URL (us — same host).
  3. Client fetches `/.well-known/oauth-authorization-server` (RFC 8414)
     and learns the endpoint URLs + supported parameters.
  4. Client obtains a `client_id`, one of two ways. Either it hosts a
     Client ID Metadata Document and uses that HTTPS URL as its id — we
     fetch and validate the document on demand, nothing is stored — or it
     POSTs `/register` (RFC 7591 Dynamic Client Registration) and we
     assign one. Registration is deprecated as of the 2026-07-28 revision
     and kept for clients that predate metadata documents. Either way: no
     `client_secret` — public client + PKCE only.
  5. Client opens a browser to `/authorize?client_id=…&redirect_uri=…
     &response_type=code&code_challenge=…&code_challenge_method=S256
     &state=…`.
  6. We require an authenticated session. If the user isn't logged in,
     we bounce them through Auth0 first (existing /auth/login path)
     and bring them back here.
  7. We render a small consent page identifying the client + the user.
     On approval, we generate an authorization code (TTL 60s) and
     redirect to the client's redirect_uri with `?code=…&state=…`.
  8. Client exchanges the code at POST /token. We verify PKCE
     (SHA256(code_verifier) == code_challenge), mark the code used,
     mint a new `mcp_tokens` row tied to the user + client, and
     return the raw token as `access_token`, with an expiry and a
     `refresh_token`.
  9. Client uses `Authorization: Bearer myc_…` for all subsequent
     /mcp requests. AuthMiddleware doesn't care that the token came
     from the OAuth flow vs. a manual mint — they're the same row.
 10. Once the access token expires, the client posts the refresh token
     to /token. The grant's row gets a new secret and expiry, and the
     refresh token is spent and replaced.

Identity is still delegated to Auth0/Google. We are *not* an OIDC
provider — we're an OAuth Authorization Server that uses our own
existing user records (populated by the OIDC callback) as the
source of authenticated identity.

Public-client-with-PKCE only: no client secrets. Token endpoint auth
method advertised as `none`. This matches the MCP authorization spec
recommendation for native/desktop clients.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import anyio.to_thread
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import audiences, auth, cimd, principal_audience, store

router = APIRouter(tags=["oauth"])


def _require_oauth_enabled() -> None:
    """OAuth makes no sense when auth is off (every caller is local-admin
    so issuing tokens is pointless) and we deliberately don't expose the
    endpoints in that mode. Matches the pattern in `oidc.py`."""
    if not auth.is_enabled():
        raise HTTPException(status_code=404, detail="auth disabled")


# Authorization codes are single-use and short-lived. The MCP spec
# doesn't pin a number; 60 seconds is well above any reasonable
# round-trip and well below what an attacker could replay if a code
# leaked through a URL log.
CODE_TTL_SECONDS = 60

# How long a rendered consent page stays answerable. Long enough for a
# person to read it and decide, short enough that an abandoned tab is not
# a standing invitation to approve something later.
CONSENT_TTL_SECONDS = 600

# Manually minted tokens never expire; revocation is their only off-switch.
# An OAuth client refreshes on its own, so its access token can be short-lived
# and a leaked one is useful only briefly. Each refresh extends the refresh
# token's life, so a client in use never has to authorize again.
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL = timedelta(days=30)
REFRESH_TOKEN_PREFIX = "mycr"
_GRANT_TYPES = ("authorization_code", "refresh_token")


def _access_token_ttl() -> timedelta:
    raw = (os.environ.get("MYCELIUM_OAUTH_ACCESS_TOKEN_TTL_SECONDS") or "").strip()
    return timedelta(seconds=int(raw) if raw else DEFAULT_ACCESS_TOKEN_TTL_SECONDS)


# --- helpers --------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _base_url(request: Request) -> str:
    """This deployment's canonical public origin — its OAuth issuer and its
    resource identifier, which have to be one stable string.

    `MYCELIUM_PUBLIC_URL` pins it. Deriving it from the request's Host
    header instead makes both values vary per request, and each direction
    of that is a defect: a client records the issuer during discovery and
    then compares it byte-for-byte against the `iss` on the authorization
    response, so reaching the same deployment by a second hostname breaks
    a legitimate flow; and an attacker-chosen Host would otherwise decide
    what audience a token claims to be for.

    Falling back to the request keeps local development working, where
    there is one host and no proxy in front of it.
    """
    configured = (os.environ.get("MYCELIUM_PUBLIC_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _auth_conn(request: Request) -> sqlite3.Connection:
    from .server import runtime

    try:
        return runtime._auth_db()
    except RuntimeError:
        raise HTTPException(status_code=500, detail="auth substrate not initialized")


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_verify(verifier: str, challenge: str, method: str) -> bool:
    if method == "S256":
        return (
            _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
            == challenge
        )
    return False


@dataclass(frozen=True)
class _Client:
    """A client the authorization flow is willing to act for.

    Registration and Client ID Metadata Documents are two ways of learning
    the same three things, so the endpoints below take this rather than
    caring which one applied. That is also what keeps the redirect_uri check
    identical on both paths, including the native-client loopback port exception.
    """

    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]

    def allows(self, redirect_uri: str) -> bool:
        if redirect_uri in self.redirect_uris:
            return True
        loopback = _loopback_without_port(redirect_uri)
        return loopback is not None and any(
            _loopback_without_port(registered) == loopback
            for registered in self.redirect_uris
        )


def _loopback_without_port(uri: str) -> str | None:
    # RFC 8252 allows ephemeral HTTP loopback ports. Claude Code also uses
    # localhost; preserve every other character so this only relaxes the port.
    match = re.fullmatch(
        r"(http://(?:localhost|127\.0\.0\.1|\[::1\]))(?::([0-9]+))?((?:[/?][^\s#]*)?)",
        uri,
    )
    if match is None:
        return None
    port = match[2]
    if port is not None and (len(port) > 5 or not 1 <= int(port) <= 65535):
        return None
    return match[1] + match[3]


def _record_client(conn: sqlite3.Connection, client: _Client) -> None:
    """Give a CIMD client a row, so the code and token it is about to own
    have something to point at.

    `oauth_codes.client_id` and `mcp_tokens.client_id` both reference
    `oauth_clients`, and foreign keys are enforced, so a client that never
    registered still needs a row to exist. This is bookkeeping, not
    registration: the row is written only once the user has consented, and
    the metadata document stays authoritative for redirect URIs — the row
    is refreshed from it rather than consulted in its place.
    """
    conn.execute(
        "INSERT INTO oauth_clients (client_id, client_name, redirect_uris, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(client_id) DO UPDATE SET "
        "  client_name = excluded.client_name, "
        "  redirect_uris = excluded.redirect_uris",
        (
            client.client_id,
            client.client_name,
            json.dumps(list(client.redirect_uris)),
            _now().isoformat(),
        ),
    )


def _resolve_client(conn: sqlite3.Connection, client_id: str) -> _Client | None:
    """Find the client behind `client_id`, or None if there isn't one.

    An https URL with a path is a Client ID Metadata Document and is
    resolved by fetching it; anything else is one of our own registration
    ids and is looked up. A document that fails to fetch or validate is not
    a client, which callers report as `invalid_client` — the same answer an
    unknown registration id gets, so neither reveals more than the other.
    """
    if cimd.looks_like_client_id_url(client_id):
        try:
            meta = cimd.fetch(client_id)
        except cimd.CimdError:
            return None
        return _Client(
            client_id=meta.client_id,
            client_name=meta.client_name,
            redirect_uris=meta.redirect_uris,
        )

    row = conn.execute(
        "SELECT client_id, client_name, redirect_uris FROM oauth_clients "
        "WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        return None
    return _Client(
        client_id=row["client_id"],
        client_name=row["client_name"] or "An MCP client",
        redirect_uris=tuple(json.loads(row["redirect_uris"])),
    )


# --- discovery: RFC 9728 & RFC 8414 ---------------------------------------


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource_metadata(request: Request) -> dict[str, Any]:
    """RFC 9728: tells the MCP client which Authorization Server to
    use. We're our own AS, so we point at ourselves."""
    _require_oauth_enabled()
    base = _base_url(request)
    return {
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base}/connect",
        # The minimal set needed for basic functionality — a client with no
        # `scope` challenge to work from asks for exactly this. Access is
        # capped at the consenting user's role regardless of what is asked
        # for, so there is nothing finer to advertise.
        "scopes_supported": ["mcp"],
    }


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata(request: Request) -> dict[str, Any]:
    """RFC 8414 / OAuth 2.1 AS metadata. The client reads this to find
    every endpoint URL it needs."""
    _require_oauth_enabled()
    base = _base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "scopes_supported": ["mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": list(_GRANT_TYPES),
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        # RFC 9207 §2.3. A client that records our issuer at discovery
        # compares it against the `iss` we put on every authorization
        # response; advertising it is what tells the client to reject a
        # response that arrives without one. Mandatory once you emit `iss`
        # at all, which we do.
        "authorization_response_iss_parameter_supported": True,
        # A client that sees this uses its own hosted metadata document as
        # its client_id and skips registration entirely; DCR stays advertised
        # above for clients that predate it.
        "client_id_metadata_document_supported": True,
    }


# --- RFC 7591 Dynamic Client Registration ---------------------------------

# Registration is anonymous and every accepted client is stored, so these
# bound what one request can make us keep. Real clients register a name and
# a redirect or two.
MAX_REGISTRATION_BYTES = 64 * 1024
MAX_CLIENT_NAME_CHARS = 200
MAX_REDIRECT_URIS = 20
MAX_REDIRECT_URI_CHARS = 2000


async def _read_capped(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="invalid_request: too large")
    return bytes(body)


@router.post("/register", include_in_schema=False)
async def register_client(request: Request) -> JSONResponse:
    """Public, unauthenticated client registration. Anyone who can
    reach this endpoint can register a client — that's fine because
    registration alone grants nothing; the registered client still
    has to drive a user through /authorize to get an access token,
    and only invited Workspace users get past that step.

    We accept the spec'd fields and persist a minimal subset
    (client_name, redirect_uris). A bogus client_metadata field that
    we don't recognise is silently ignored — RFC 7591 allows that.
    """
    _require_oauth_enabled()
    raw = await _read_capped(request, MAX_REGISTRATION_BYTES)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="invalid_request: body must be JSON"
        )
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="invalid_request: body must be a JSON object"
        )

    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not all(
        isinstance(u, str) for u in redirect_uris
    ):
        raise HTTPException(
            status_code=400,
            detail="invalid_redirect_uri: must be a JSON array of strings",
        )
    if not redirect_uris:
        raise HTTPException(
            status_code=400, detail="invalid_redirect_uri: at least one URI required"
        )
    if len(redirect_uris) > MAX_REDIRECT_URIS or any(
        len(u) > MAX_REDIRECT_URI_CHARS for u in redirect_uris
    ):
        raise HTTPException(
            status_code=400, detail="invalid_redirect_uri: too many or too long"
        )

    client_name = body.get("client_name") or "Unnamed MCP client"
    if not isinstance(client_name, str):
        client_name = str(client_name)
    if len(client_name) > MAX_CLIENT_NAME_CHARS:
        raise HTTPException(
            status_code=400, detail="invalid_client_metadata: client_name too long"
        )

    # RFC 7591 §2 — "Authorization servers MAY ignore values they
    # don't support." We answer with the grants every client gets.
    requested_grants = set(body.get("grant_types") or ["authorization_code"])
    if "authorization_code" not in requested_grants:
        raise HTTPException(
            status_code=400,
            detail="invalid_client_metadata: authorization_code grant must be requested",
        )

    requested_response = set(body.get("response_types") or ["code"])
    if "code" not in requested_response:
        raise HTTPException(
            status_code=400,
            detail="invalid_client_metadata: response_type=code must be requested",
        )

    token_auth_method = body.get("token_endpoint_auth_method", "none")
    if token_auth_method not in ("none",):
        # Public clients only — but accept the most common alias.
        # Some clients send "client_secret_post" by default; we still
        # operate as a public client and PKCE-verify, but tell them so
        # in the response so they don't try to send a secret.
        token_auth_method = "none"

    client_id = f"mcp_{secrets.token_urlsafe(16)}"
    conn = _auth_conn(request)
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO oauth_clients "
            "(client_id, client_name, redirect_uris, created_at) "
            "VALUES (?, ?, ?, ?)",
            (client_id, client_name, json.dumps(redirect_uris), _now().isoformat()),
        )
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": list(_GRANT_TYPES),
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


# --- /authorize: consent + code issuance ----------------------------------


_CONSENT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<link rel="icon" type="image/svg+xml" href="/ui/favicon.svg" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Authorize {client_name} · Mycelium</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0b0b0c; color: #f4f4f5;
          min-height: 100vh; margin: 0; display: flex; align-items: center; justify-content: center; }}
  .card {{ background: #121214; border: 1px solid #26262a; border-radius: 10px;
           padding: 32px 36px; max-width: 480px; width: 92vw; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; }}
  p {{ color: #c5c5cb; line-height: 1.55; font-size: 14.5px; }}
  .row {{ display: grid; grid-template-columns: 110px 1fr; gap: 6px 16px;
          font-size: 13.5px; margin: 18px 0 22px; padding: 14px 16px;
          background: #1a1a1d; border-radius: 6px; }}
  .row > :nth-child(odd) {{ color: #8a8a93; }}
  .actions {{ display: flex; gap: 10px; }}
  button, .btn {{ flex: 1; padding: 10px 16px; font-size: 14px; border-radius: 6px;
                  border: 1px solid #26262a; background: #1a1a1d; color: #f4f4f5;
                  cursor: pointer; font-family: inherit; text-align: center;
                  text-decoration: none; }}
  button.primary {{ background: #2563eb; border-color: #2563eb; }}
  button.primary:hover {{ background: #1d4ed8; }}
  .btn-secondary:hover {{ background: #26262a; }}
  .scope {{ font-family: ui-monospace, monospace; font-size: 12px;
            background: #1a1a1d; padding: 2px 8px; border-radius: 4px; }}
  label {{ display: block; font-size: 13.5px; color: #8a8a93; margin: 0 0 20px; }}
  select {{ display: block; width: 100%; margin-top: 6px; padding: 8px; font: inherit;
            background: #1a1a1d; color: #f4f4f5; border: 1px solid #26262a; border-radius: 6px; }}
  .warn {{ border-left: 3px solid #b26a00; background: #1a1a1d; padding: 10px 14px;
           margin: 0 0 20px; font-size: 13px; color: #c5c5cb; border-radius: 0 6px 6px 0; }}
</style>
</head>
<body>
<div class="card">
  <h1>Authorize {client_name}?</h1>
  <p>This will let <strong>{client_name}</strong> access Mycelium on your behalf as <strong>{user_name}</strong>.</p>
  <div class="row">
    <span>Signed in as</span><span>{user_name} <span class="scope">{user_role}</span></span>
    <span>Client</span><span>{client_name}</span>
    <span>Redirects to</span><span class="scope">{redirect_host}</span>
    <span>Access</span><span>{access}</span>
  </div>
  {redirect_warning}
  <form method="post" action="/authorize/decide">
    <input type="hidden" name="consent_id" value="{consent_id}" />
    {audience_field}
    <div class="actions">
      <button type="submit" name="decision" value="deny" class="btn-secondary">Deny</button>
      <button type="submit" name="decision" value="allow" class="primary">Allow</button>
    </div>
  </form>
</div>
</body>
</html>
"""


@router.get("/authorize", include_in_schema=False)
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str | None = None,
    state: str | None = None,
    resource: str | None = None,
) -> Any:
    """Start the auth-code flow. Validates the request, ensures the
    user has a session (bouncing through OIDC if not), and shows the
    consent page."""
    _require_oauth_enabled()
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if not code_challenge:
        raise HTTPException(
            status_code=400, detail="invalid_request: code_challenge is required (PKCE)"
        )
    if code_challenge_method != "S256":
        raise HTTPException(
            status_code=400,
            detail="invalid_request: code_challenge_method must be S256",
        )

    conn = _auth_conn(request)
    # Resolving a metadata document means DNS and an HTTPS request to a
    # host the caller chose. Both are blocking, and these handlers are
    # async, so doing it inline would let one slow endpoint stall every
    # other request the worker is serving.
    client = await anyio.to_thread.run_sync(_resolve_client, conn, client_id)
    if client is None:
        raise HTTPException(status_code=400, detail="invalid_client")
    if not client.allows(redirect_uri):
        raise HTTPException(
            status_code=400,
            detail="invalid_request: redirect_uri not registered for this client",
        )

    # The user must be logged in to consent. If they aren't, route
    # them through Auth0 first; the session carries the post-login
    # destination so they end up back here with the same query string.
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.synthetic:
        # The authorize URL with its full query string IS the post-login
        # next URL. We can't put it in the session because the user
        # might have multiple tabs; instead, encode it directly.
        # /auth/login reads ?next= from query, not session — adjust
        # the existing login route to honor it if needed.
        return RedirectResponse(
            url=f"/auth/login?next={quote(str(request.url.path) + '?' + request.url.query)}",
            status_code=302,
        )

    # Record the request and hand the form nothing but an id. The OAuth
    # parameters are fixed here, where they have been validated against a
    # request the user actually navigated to, and read back from the row on
    # submit — so whoever posts the form cannot choose them.
    #
    # That is what makes the decision a decision. Re-validating parameters
    # supplied by the submitter only ever proves the submitter picked valid
    # ones; it cannot show the user saw them. Without this, a page on a
    # sibling host — same-site, so `SameSite=Lax` still sends the session
    # cookie on its POST — could auto-submit an approval for a client it
    # controls and collect the code.
    consent_id = str(uuid.uuid4())
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO oauth_consents "
            "(id, user_id, client_id, redirect_uri, code_challenge, "
            " code_challenge_method, scope, resource, state, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                consent_id,
                principal.id,
                client_id,
                redirect_uri,
                code_challenge,
                code_challenge_method,
                scope or "",
                resource or None,
                state or "",
                _now().isoformat(),
                (_now() + timedelta(seconds=CONSENT_TTL_SECONDS)).isoformat(),
            ),
        )

    html = _CONSENT_HTML.format(
        client_name=_html_escape(client.client_name),
        user_name=_html_escape(principal.name),
        user_role=_html_escape(principal.role),
        consent_id=_html_escape(consent_id),
        redirect_host=_html_escape(_redirect_host(redirect_uri)),
        redirect_warning=_localhost_warning(redirect_uri),
        access=_html_escape(_access_text(principal)),
        audience_field=_audience_field(principal),
    )
    return HTMLResponse(content=html)


def _access_text(principal: auth.Principal) -> str:
    if principal.audience_id is None:
        return "Read and write to the substrate (capped at your role)"
    audience = next(
        (item for item in audiences.live() if item.id == principal.audience_id), None
    )
    return (
        f"Read only what {audience.name if audience else principal.audience_id} may see"
    )


def _audience_field(principal: auth.Principal) -> str:
    """An admin may scope the grant to an audience as it is minted. The
    choice only ever narrows what the token reads, so it is safe to take
    from the submitted form."""
    if not principal.is_admin or principal.audience_id is not None:
        return ""
    options = "".join(
        f'<option value="{_html_escape(item.id)}">{_html_escape(item.name)}</option>'
        for item in audiences.live()
    )
    return (
        '<label>Audience<select name="audience_id">'
        '<option value="">Full access (your role)</option>'
        f"{options}</select></label>"
    )


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _redirect_host(redirect_uri: str) -> str:
    """The host the code will be handed to, for the consent page.

    `hostname` and not `netloc`: netloc carries userinfo, so
    `https://login.trusted.example@evil.example/cb` would render starting
    with the trusted name while the code goes to evil.example. Documents
    carrying userinfo are rejected outright, and this is the second place
    that would have to fail for the deception to land.

    The port is kept, since a loopback client is identified by it.
    """
    try:
        parts = urlsplit(redirect_uri)
    except ValueError:
        return "unparseable redirect"
    if not parts.hostname:
        return "unparseable redirect"
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname


def _is_loopback_redirect(redirect_uri: str) -> bool:
    """Whether the code would be handed to this machine.

    `ipaddress` only understands the fully-written forms, but resolvers
    accept shorthand and alternate bases — `127.1`, `0177.0.0.1`,
    `0x7f.0.0.1` all reach loopback — so `inet_aton` gets a turn too. Being
    generous here is the safe direction: the cost of a false positive is one
    extra caution on a consent page.
    """
    import socket

    try:
        host = (urlsplit(redirect_uri).hostname or "").rstrip(".")
    except ValueError:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return False
    return ipaddress.IPv4Address(packed).is_loopback


def _localhost_warning(redirect_uri: str) -> str:
    """A caution when the code will be handed to this machine.

    Keyed on the redirect actually being authorized, not on the client's
    whole list: a client asking for `127.0.0.1` could otherwise silence
    this by listing one hosted URI it never uses. Any local program can
    listen on a loopback port, so the document proves nothing about which
    one is asking — the spec asks us to say so rather than imply otherwise.
    """
    if not _is_loopback_redirect(redirect_uri):
        return ""
    return (
        '<div class="warn">This client receives the authorization on this '
        "machine. Approve it only if you started it yourself — any local "
        "program can listen on the same address.</div>"
    )


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


@router.post("/authorize/decide", include_in_schema=False)
async def authorize_decide(
    request: Request,
    consent_id: str = Form(...),
    decision: str = Form(...),
    audience_id: str = Form(""),
) -> RedirectResponse:
    """Consume the consent decision.

    The submitter supplies only which pending decision this is and what the
    user answered. Every OAuth parameter comes from the row written when the
    page was rendered, so a forged submission cannot choose a client, a
    redirect, or a PKCE challenge — the worst it can do is answer a consent
    the user was already being shown, and the row is bound to that user.
    """
    _require_oauth_enabled()
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.synthetic:
        raise HTTPException(status_code=401, detail="session expired; please retry")

    conn = _auth_conn(request)
    pending = conn.execute(
        "SELECT * FROM oauth_consents WHERE id = ?", (consent_id,)
    ).fetchone()
    # One answer per pending decision, by the user it was shown to. Failing
    # all four the same way keeps this from reporting whether a given
    # consent id exists or whose it is.
    if (
        pending is None
        or pending["user_id"] != principal.id
        or pending["used_at"] is not None
        or datetime.fromisoformat(pending["expires_at"]) < _now()
    ):
        raise HTTPException(status_code=400, detail="invalid_request: no such consent")

    client_id = pending["client_id"]
    redirect_uri = pending["redirect_uri"]
    code_challenge = pending["code_challenge"]
    code_challenge_method = pending["code_challenge_method"]
    scope = pending["scope"] or ""
    state = pending["state"] or ""
    resource = pending["resource"] or ""

    with store.transaction(conn):
        conn.execute(
            "UPDATE oauth_consents SET used_at = ? WHERE id = ? AND used_at IS NULL",
            (_now().isoformat(), consent_id),
        )

    # The document may have changed since the page was rendered, so the
    # client is resolved again and the redirect re-checked against it —
    # a URI revoked in the meantime must not still be honoured.
    client = await anyio.to_thread.run_sync(_resolve_client, conn, client_id)
    if client is None:
        raise HTTPException(status_code=400, detail="invalid_client")
    if not client.allows(redirect_uri):
        raise HTTPException(
            status_code=400, detail="invalid_request: redirect_uri not registered"
        )

    # RFC 9207 §2: `iss` rides on every authorization response, errors
    # included, so a client that recorded our issuer at discovery can tell
    # a response from us apart from one from another authorization server
    # it also talks to. Without it, a mix-up attack lands a code meant for
    # someone else on our token endpoint.
    issuer = _base_url(request)

    if decision != "allow":
        return RedirectResponse(
            url=_with_query(
                redirect_uri,
                {"error": "access_denied", "state": state, "iss": issuer},
            ),
            status_code=302,
        )

    if resource and not _resource_matches(resource, issuer):
        return RedirectResponse(
            url=_with_query(
                redirect_uri,
                {"error": "invalid_target", "state": state, "iss": issuer},
            ),
            status_code=302,
        )

    if audience_id:
        if not principal.is_admin:
            raise HTTPException(
                status_code=403, detail="only an admin can scope a grant to an audience"
            )
        principal_audience.require_live(audience_id)
    # A scoped principal's own audience binds the grant, so the stored code
    # never claims more than the person consenting could see.
    grant_audience = principal.audience_id or audience_id or None

    # Mint a code. TTL is short; client must exchange within
    # CODE_TTL_SECONDS or restart the flow.
    code = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=CODE_TTL_SECONDS)
    with store.transaction(conn):
        if cimd.looks_like_client_id_url(client_id):
            _record_client(conn, client)
        conn.execute(
            "INSERT INTO oauth_codes "
            "(code, client_id, user_id, redirect_uri, code_challenge, "
            " code_challenge_method, scope, resource, created_at, expires_at, "
            " audience_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code,
                client_id,
                principal.id,
                redirect_uri,
                code_challenge,
                code_challenge_method,
                scope,
                resource or None,
                _now().isoformat(),
                expires_at.isoformat(),
                grant_audience,
            ),
        )
    return RedirectResponse(
        url=_with_query(redirect_uri, {"code": code, "state": state, "iss": issuer}),
        status_code=302,
    )


def _with_query(url: str, params: dict[str, str]) -> str:
    sep = "&" if "?" in url else "?"
    return url + sep + urlencode({k: v for k, v in params.items() if v})


def _resource_matches(value: str, base: str) -> bool:
    """Whether an RFC 8707 `resource` is a canonical URI naming this server.

    A client is told to send the most specific URI it can, so both the
    origin and the `/mcp` endpoint under it name us. Scheme and host
    compare case-insensitively — the spec asks servers to accept uppercase
    components — and one trailing slash is ignored, since the canonical
    form omits it.

    Everything else is rejected rather than normalised away. A fragment is
    explicitly not a canonical URI; a query string or userinfo means the
    caller is naming something other than what we advertise; and repeated
    slashes are a different path, not a sloppier spelling of ours. Each
    would otherwise let a value that is not our identifier be accepted as
    if it were.
    """
    from urllib.parse import urlsplit

    def _canon(u: str) -> tuple[str, str, str] | None:
        try:
            parts = urlsplit(u)
            netloc = parts.netloc  # raises on a malformed IPv6 literal
            host = parts.hostname
        except ValueError:
            return None
        if not parts.scheme or not host:
            return None
        if parts.fragment or parts.query or "@" in netloc:
            return None
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        if "//" in path:
            return None
        return (parts.scheme.lower(), netloc.lower(), path)

    target = _canon(value)
    ours = _canon(base)
    if target is None or ours is None:
        return False
    if target[:2] != ours[:2]:
        return False
    return target[2] in (ours[2], f"{ours[2]}/mcp")


# --- /token: code → access token -----------------------------------------


@router.post("/token", include_in_schema=False)
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
    resource: str = Form(""),
) -> JSONResponse:
    """Exchange an authorization code or a refresh token for an access token.

    A code exchange follows OAuth 2.1 + PKCE: the verifier must hash to the
    challenge captured at /authorize, the code must not be expired or
    already used, and every echoed field (client_id, redirect_uri) must
    match what /authorize stored. It creates a row in `mcp_tokens`, the
    grant, and returns its raw value as `access_token`. The token is
    interchangeable with manually-minted tokens — same table, same lookup
    path, same revocation UI — except that it expires and comes with a
    refresh token."""
    _require_oauth_enabled()
    # RFC 8707 §2: a token is minted for one resource. We serve exactly
    # one, so a request naming a different one is asking us to issue a
    # credential for somewhere else — the confused-deputy shape resource
    # indicators exist to close. Honouring it silently is what would make
    # the token replayable against another server.
    if resource and not _resource_matches(resource, _base_url(request)):
        return _oauth_error(
            "invalid_target", "resource does not identify this MCP server"
        )
    conn = _auth_conn(request)
    if grant_type == "refresh_token":
        return _refresh(conn, refresh_token, client_id)
    if grant_type != "authorization_code":
        return _oauth_error(
            "unsupported_grant_type",
            "only authorization_code and refresh_token are supported",
        )
    if not (code and redirect_uri and client_id and code_verifier):
        return _oauth_error(
            "invalid_request",
            "code, redirect_uri, client_id and code_verifier are required",
        )
    row = conn.execute(
        "SELECT client_id, user_id, redirect_uri, code_challenge, "
        "       code_challenge_method, scope, resource, expires_at, used_at, "
        "       audience_id "
        "FROM oauth_codes WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return _oauth_error("invalid_grant", "code not found")
    if row["used_at"] is not None:
        return _oauth_error("invalid_grant", "code already used")
    if datetime.fromisoformat(row["expires_at"]) < _now():
        return _oauth_error("invalid_grant", "code expired")
    if row["client_id"] != client_id:
        return _oauth_error("invalid_grant", "client_id mismatch")
    if row["redirect_uri"] != redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri mismatch")
    if not _pkce_verify(
        code_verifier, row["code_challenge"], row["code_challenge_method"]
    ):
        return _oauth_error("invalid_grant", "PKCE verification failed")

    # RFC 8707 §2: the token request's resource must be the one the code was
    # authorized for. Re-validating against our own identity is not enough on
    # its own — that would let a code obtained for one audience be redeemed
    # for another, which is the binding the resource parameter exists to
    # create. Codes minted before this column existed carry NULL and are
    # treated as having named no resource.
    if (row["resource"] or "") != resource:
        return _oauth_error(
            "invalid_target", "resource does not match the authorization request"
        )

    # Mark used BEFORE minting the token so a concurrent exchange
    # can't double-redeem (SQLite under default isolation serializes
    # writes, but we want correctness if that ever changes). One
    # transaction owns the whole exchange: the used_at mark is durable
    # whether we go on to mint or bail out on an inactive user.
    with store.transaction(conn):
        conn.execute(
            "UPDATE oauth_codes SET used_at = ? WHERE code = ? AND used_at IS NULL",
            (_now().isoformat(), code),
        )

        # Look up the user's current role so we can scope the token. The
        # MCP spec doesn't define standard scopes for tools, so we just
        # mirror the user's full role into the token — same convention as
        # manually-minted "default scope" tokens.
        user_row = conn.execute(
            "SELECT id, role, status, type, email FROM users WHERE id = ?",
            (row["user_id"],),
        ).fetchone()
        if user_row is None or user_row["status"] != "active":
            return _oauth_error("invalid_grant", "user no longer active")
        if auth.blocked_by_domain_policy(user_row["type"], user_row["email"]):
            return _oauth_error("invalid_grant", "email domain not allowed")

        scope_to_grant: auth.Scope = user_row["role"]
        raw, prefix, h = auth.generate_token()
        client_row = conn.execute(
            "SELECT client_name FROM oauth_clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        token_name = (
            f"OAuth: {client_row['client_name']}"
            if client_row and client_row["client_name"]
            else "OAuth client"
        )
        token_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO mcp_tokens "
            "(id, user_id, name, prefix, hash, scope, created_at, client_id, "
            " expires_at, audience_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token_id,
                user_row["id"],
                token_name,
                prefix,
                h,
                scope_to_grant,
                _now().isoformat(),
                client_id,
                (_now() + _access_token_ttl()).isoformat(),
                row["audience_id"],
            ),
        )
        conn.execute(
            "UPDATE oauth_clients SET last_used_at = ? WHERE client_id = ?",
            (_now().isoformat(), client_id),
        )
        refresh = _new_refresh_token(conn, token_id)

    return _token_response(raw, refresh, scope_to_grant)


def _refresh(
    conn: sqlite3.Connection, refresh_token: str, client_id: str
) -> JSONResponse:
    """Rotate a grant: a new access-token secret and expiry on the same
    `mcp_tokens` row, and a new refresh token in place of the spent one.

    The scope stays what the grant was given (RFC 6749 §6 forbids widening
    it); `resolve_token` still caps it at the user's current role."""
    if not (refresh_token and client_id):
        return _oauth_error(
            "invalid_request", "refresh_token and client_id are required"
        )
    with store.transaction(conn):
        row = conn.execute(
            "SELECT r.token_id, r.expires_at, r.used_at, t.client_id, t.prefix, "
            "       t.scope, t.revoked_at, u.status, u.type, u.email "
            "FROM oauth_refresh_tokens r "
            "JOIN mcp_tokens t ON t.id = r.token_id "
            "JOIN users u ON u.id = t.user_id "
            "WHERE r.hash = ?",
            (auth.hash_token(refresh_token),),
        ).fetchone()
        if row is None:
            return _oauth_error("invalid_grant", "refresh token not found")
        if row["client_id"] != client_id:
            return _oauth_error("invalid_grant", "client_id mismatch")
        if row["used_at"] is not None:
            # Two parties hold this token and nothing says which one is the
            # client, so the grant ends for both (OAuth 2.1 §4.3.1).
            auth.revoke_token(conn, row["token_id"])
            return _oauth_error(
                "invalid_grant", "refresh token already used; the grant is revoked"
            )
        if row["revoked_at"] is not None:
            return _oauth_error("invalid_grant", "grant revoked")
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return _oauth_error("invalid_grant", "refresh token expired")
        if row["status"] != "active":
            return _oauth_error("invalid_grant", "user no longer active")
        if auth.blocked_by_domain_policy(row["type"], row["email"]):
            return _oauth_error("invalid_grant", "email domain not allowed")

        conn.execute(
            "UPDATE oauth_refresh_tokens SET used_at = ? WHERE hash = ?",
            (_now().isoformat(), auth.hash_token(refresh_token)),
        )
        raw, _, h = auth.generate_token(prefix=row["prefix"])
        conn.execute(
            "UPDATE mcp_tokens SET hash = ?, expires_at = ? WHERE id = ?",
            (h, (_now() + _access_token_ttl()).isoformat(), row["token_id"]),
        )
        refresh = _new_refresh_token(conn, row["token_id"])
    return _token_response(raw, refresh, row["scope"])


def _new_refresh_token(conn: sqlite3.Connection, token_id: str) -> str:
    raw = f"{REFRESH_TOKEN_PREFIX}_{secrets.token_urlsafe(32)}"
    conn.execute(
        "INSERT INTO oauth_refresh_tokens (hash, token_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (
            auth.hash_token(raw),
            token_id,
            _now().isoformat(),
            (_now() + REFRESH_TOKEN_TTL).isoformat(),
        ),
    )
    return raw


def _token_response(access_token: str, refresh_token: str, scope: str) -> JSONResponse:
    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": int(_access_token_ttl().total_seconds()),
            "refresh_token": refresh_token,
            "scope": scope,
        },
        # RFC 6749 §5.1: a response carrying credentials must not be cached.
        headers={"Cache-Control": "no-store"},
    )


def _oauth_error(error: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 error response. status 400 with the error code
    in the body — not in headers — so clients parse it from JSON."""
    return JSONResponse(
        status_code=400,
        content={"error": error, "error_description": description},
    )
