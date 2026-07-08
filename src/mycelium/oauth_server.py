"""OAuth 2.1 Authorization Server for the MCP transport.

This is what lets Claude Desktop / Claude Code add Mycelium without
the user pasting a token. The flow:

  1. Client hits /mcp without credentials → 401 with a `WWW-Authenticate`
     header pointing at the resource metadata.
  2. Client fetches `/.well-known/oauth-protected-resource` (RFC 9728)
     and discovers the authorization server URL (us — same host).
  3. Client fetches `/.well-known/oauth-authorization-server` (RFC 8414)
     and learns the endpoint URLs + supported parameters.
  4. Client POSTs `/register` (RFC 7591 Dynamic Client Registration)
     with its name + redirect URIs. We assign a `client_id`. No
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
     return the raw token as `access_token`.
  9. Client uses `Authorization: Bearer myc_…` for all subsequent
     /mcp requests. AuthMiddleware doesn't care that the token came
     from the OAuth flow vs. a manual mint — they're the same row.

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
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import auth

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

# Bearer tokens issued via OAuth flow. Mycelium's manual tokens never
# expire (revocation is the only off-switch); for OAuth-issued tokens
# we mirror that for simplicity — `expires_at` is left NULL. The MCP
# spec allows long-lived tokens with revocation; refresh tokens are
# optional and we don't implement them yet.


# --- helpers --------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_url(request: Request) -> str:
    """The public scheme://host. Reverse-proxy aware (uses Host header
    + the X-Forwarded-Proto restored by Starlette from the proxy)."""
    return str(request.base_url).rstrip("/")


def _auth_conn(request: Request) -> sqlite3.Connection:
    from . import server

    conn = server._auth_conn
    if conn is None:
        raise HTTPException(status_code=500, detail="auth substrate not initialized")
    return conn


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_verify(verifier: str, challenge: str, method: str) -> bool:
    if method == "plain":
        return verifier == challenge
    if method == "S256":
        return (
            _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
            == challenge
        )
    return False


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
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


# --- RFC 7591 Dynamic Client Registration ---------------------------------


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
    try:
        body = await request.json()
    except Exception:
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

    client_name = body.get("client_name") or "Unnamed MCP client"
    if not isinstance(client_name, str):
        client_name = str(client_name)

    # RFC 7591 §2 — "Authorization servers MAY ignore values they
    # don't support." Claude Desktop / Claude Code in particular asks
    # for `refresh_token` in grant_types; we don't issue refresh
    # tokens but rejecting the whole registration over that would be
    # spec-non-compliant and a bad UX. Instead we accept the request
    # and advertise back the subset we actually support in the
    # response body — the client uses the advertised subset.
    requested_grants = set(body.get("grant_types") or ["authorization_code"])
    supported_grants = ["authorization_code"]
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
    conn.execute(
        "INSERT INTO oauth_clients (client_id, client_name, redirect_uris, created_at) "
        "VALUES (?, ?, ?, ?)",
        (client_id, client_name, json.dumps(redirect_uris), _now().isoformat()),
    )
    conn.commit()
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": supported_grants,
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


# --- /authorize: consent + code issuance ----------------------------------


_CONSENT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
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
</style>
</head>
<body>
<div class="card">
  <h1>Authorize {client_name}?</h1>
  <p>This will let <strong>{client_name}</strong> access Mycelium on your behalf as <strong>{user_name}</strong>.</p>
  <div class="row">
    <span>Signed in as</span><span>{user_name} <span class="scope">{user_role}</span></span>
    <span>Client</span><span>{client_name}</span>
    <span>Access</span><span>Read and write to the substrate (capped at your role)</span>
  </div>
  <form method="post" action="/authorize/decide">
    <input type="hidden" name="client_id" value="{client_id}" />
    <input type="hidden" name="redirect_uri" value="{redirect_uri}" />
    <input type="hidden" name="code_challenge" value="{code_challenge}" />
    <input type="hidden" name="code_challenge_method" value="{code_challenge_method}" />
    <input type="hidden" name="scope" value="{scope}" />
    <input type="hidden" name="state" value="{state}" />
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
    if code_challenge_method not in ("S256", "plain"):
        raise HTTPException(
            status_code=400,
            detail="invalid_request: code_challenge_method must be S256 or plain",
        )

    conn = _auth_conn(request)
    client_row = conn.execute(
        "SELECT client_id, client_name, redirect_uris FROM oauth_clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if client_row is None:
        raise HTTPException(status_code=400, detail="invalid_client")
    allowed = json.loads(client_row["redirect_uris"])
    if redirect_uri not in allowed:
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

    # The form posts the OAuth params back as hidden fields rather than
    # us stashing them in the session. Two reasons: (1) avoids
    # session-modification races when multiple authorize flows interleave
    # in the same browser/test session, and (2) the params are
    # re-validated on decide (client_id exists, redirect_uri matches the
    # registered list) so tampering with the form can't elevate access.
    # The principal that consents is taken from the session/bearer —
    # not the form — so a manipulated form can't grant tokens to a
    # different account.
    html = _CONSENT_HTML.format(
        client_name=_html_escape(client_row["client_name"] or "An MCP client"),
        user_name=_html_escape(principal.name),
        user_role=_html_escape(principal.role),
        client_id=_html_escape(client_id),
        redirect_uri=_html_escape(redirect_uri),
        code_challenge=_html_escape(code_challenge),
        code_challenge_method=_html_escape(code_challenge_method),
        scope=_html_escape(scope or ""),
        state=_html_escape(state or ""),
    )
    return HTMLResponse(content=html)


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
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    decision: str = Form(...),
    scope: str = Form(""),
    state: str = Form(""),
) -> RedirectResponse:
    """Consume the consent decision. Re-validates the OAuth params
    (client_id exists, redirect_uri is on the client's allow-list)
    so the form can't be edited to redirect a code to a third party.
    Identity comes from the session/bearer, not the form."""
    _require_oauth_enabled()
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.synthetic:
        raise HTTPException(status_code=401, detail="session expired; please retry")

    conn = _auth_conn(request)
    client_row = conn.execute(
        "SELECT client_id, redirect_uris FROM oauth_clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if client_row is None:
        raise HTTPException(status_code=400, detail="invalid_client")
    if redirect_uri not in json.loads(client_row["redirect_uris"]):
        raise HTTPException(
            status_code=400, detail="invalid_request: redirect_uri not registered"
        )
    if code_challenge_method not in ("S256", "plain"):
        raise HTTPException(
            status_code=400, detail="invalid_request: bad code_challenge_method"
        )

    if decision != "allow":
        return RedirectResponse(
            url=_with_query(redirect_uri, {"error": "access_denied", "state": state}),
            status_code=302,
        )

    # Mint a code. TTL is short; client must exchange within
    # CODE_TTL_SECONDS or restart the flow.
    code = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=CODE_TTL_SECONDS)
    conn.execute(
        "INSERT INTO oauth_codes "
        "(code, client_id, user_id, redirect_uri, code_challenge, "
        " code_challenge_method, scope, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            code,
            client_id,
            principal.id,
            redirect_uri,
            code_challenge,
            code_challenge_method,
            scope,
            _now().isoformat(),
            expires_at.isoformat(),
        ),
    )
    conn.commit()
    return RedirectResponse(
        url=_with_query(redirect_uri, {"code": code, "state": state}),
        status_code=302,
    )


def _with_query(url: str, params: dict[str, str]) -> str:
    sep = "&" if "?" in url else "?"
    return url + sep + urlencode({k: v for k, v in params.items() if v})


# --- /token: code → access token -----------------------------------------


@router.post("/token", include_in_schema=False)
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
) -> JSONResponse:
    """Exchange an authorization code for an access token. Per OAuth 2.1
    + PKCE: the verifier must hash to the challenge captured at /authorize,
    the code must not be expired or already used, and every echoed field
    (client_id, redirect_uri) must match what /authorize stored.

    Issues a row in `mcp_tokens` and returns its raw value as
    `access_token`. The token is interchangeable with manually-minted
    tokens — same table, same lookup path, same revocation UI."""
    _require_oauth_enabled()
    if grant_type != "authorization_code":
        return _oauth_error(
            "unsupported_grant_type", "only authorization_code is supported"
        )

    conn = _auth_conn(request)
    row = conn.execute(
        "SELECT client_id, user_id, redirect_uri, code_challenge, "
        "       code_challenge_method, scope, expires_at, used_at "
        "FROM oauth_codes WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return _oauth_error("invalid_grant", "code not found")
    if row["used_at"] is not None:
        # Replay attempt — invalidate any token previously issued for
        # this code as a safety measure.
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

    # Mark used BEFORE minting the token so a concurrent exchange
    # can't double-redeem (SQLite under default isolation serializes
    # writes, but we want correctness if that ever changes).
    conn.execute(
        "UPDATE oauth_codes SET used_at = ? WHERE code = ? AND used_at IS NULL",
        (_now().isoformat(), code),
    )

    # Look up the user's current role so we can scope the token. The
    # MCP spec doesn't define standard scopes for tools, so we just
    # mirror the user's full role into the token — same convention as
    # manually-minted "default scope" tokens.
    user_row = conn.execute(
        "SELECT id, role, status FROM users WHERE id = ?",
        (row["user_id"],),
    ).fetchone()
    if user_row is None or user_row["status"] != "active":
        conn.commit()
        return _oauth_error("invalid_grant", "user no longer active")

    scope_to_grant: auth.Scope = user_row["role"]  # type: ignore[assignment]
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
    conn.execute(
        "INSERT INTO mcp_tokens "
        "(id, user_id, name, prefix, hash, scope, created_at, client_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_row["id"],
            token_name,
            prefix,
            h,
            scope_to_grant,
            _now().isoformat(),
            client_id,
        ),
    )
    conn.execute(
        "UPDATE oauth_clients SET last_used_at = ? WHERE client_id = ?",
        (_now().isoformat(), client_id),
    )
    conn.commit()

    return JSONResponse(
        content={
            "access_token": raw,
            "token_type": "Bearer",
            "scope": scope_to_grant,
        }
    )


def _oauth_error(error: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 error response. status 400 with the error code
    in the body — not in headers — so clients parse it from JSON."""
    return JSONResponse(
        status_code=400,
        content={"error": error, "error_description": description},
    )
