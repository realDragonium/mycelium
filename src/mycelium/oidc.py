"""OIDC integration — Auth0 (or any OIDC issuer) for human logins.

The MCP token machinery in `auth.py` doesn't need this module; bearer
tokens work without it. This is purely the cookie-session login path
for the web UI.

Flow
----
1. `/auth/login` redirects to the issuer's hosted login page (Auth0).
2. Issuer redirects back to `/auth/callback?code=…&state=…`.
3. The callback exchanges the code for an ID token, finds-or-creates
   the corresponding `users` row, and writes the user id into the
   signed session cookie.
4. Middleware (`AuthMiddleware` in http.py) resolves the cookie to a
   `Principal` on every subsequent request.

Bootstrap admin
---------------
`MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` — when the first OIDC login matches
this email, the auto-created user is granted `admin` role even with no
prior invite. Lets you reach the admin UI on a fresh install.

Invites
-------
A login whose email matches an active invite consumes that invite and
the user inherits the invited role. A login without a matching invite
or bootstrap is rejected (account not created) — invite-only signup.

Just-in-time provisioning
-------------------------
When `MYCELIUM_JIT_DOMAINS` lists the login's email domain, a user with
no invite is provisioned on the spot (as if self-invited) and granted
`MYCELIUM_JIT_DEFAULT_ROLE` (default `reader`). Unset domains keep the
server invite-only. Invite and bootstrap matches always take priority
over the JIT default role.

Config (env vars)
-----------------
- `MYCELIUM_AUTH` — must be `on` for OIDC routes to do anything
  meaningful. When off, `/auth/login` etc. 404.
- `MYCELIUM_OIDC_ISSUER` — e.g. `https://your-tenant.auth0.com`.
- `MYCELIUM_OIDC_CLIENT_ID`, `MYCELIUM_OIDC_CLIENT_SECRET`.
- `MYCELIUM_OIDC_REDIRECT_URI` — usually `<base>/auth/callback`.
- `MYCELIUM_SESSION_SECRET` — signs the session cookie. Required when
  auth is on; absence raises at startup.
- `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` — optional, see above.
- `MYCELIUM_JIT_DOMAINS` — optional, comma-separated email domains
  pre-registered for just-in-time provisioning. Unset = invite-only.
- `MYCELIUM_JIT_DEFAULT_ROLE` — role for JIT users (default `reader`).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import auth

SESSION_COOKIE = "myc_session"
_oauth: Any | None = None  # lazy: only constructed when OIDC is enabled


def is_configured() -> bool:
    """True when the OIDC env vars are set. Used by route handlers to
    decide whether to 404 (not configured) vs. proceed."""
    return all(
        os.environ.get(k)
        for k in (
            "MYCELIUM_OIDC_ISSUER",
            "MYCELIUM_OIDC_CLIENT_ID",
            "MYCELIUM_OIDC_CLIENT_SECRET",
        )
    )


def _client():
    """Lazily build the Authlib client. Importing at module top would
    require Authlib at import time even on toggle-off installs."""
    global _oauth
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth

        oauth = OAuth()
        issuer = os.environ["MYCELIUM_OIDC_ISSUER"].rstrip("/")
        oauth.register(
            name="myc",
            client_id=os.environ["MYCELIUM_OIDC_CLIENT_ID"],
            client_secret=os.environ["MYCELIUM_OIDC_CLIENT_SECRET"],
            server_metadata_url=f"{issuer}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _oauth = oauth
    return _oauth.myc


# --- route helpers ---------------------------------------------------------


def _safe_next(target: str | None) -> str:
    """Constrain a post-login `next` to a same-site path so it can't be
    abused as an open redirect.

    `next` is attacker-controllable (it rides in the /auth/login and
    /auth/logout query strings), and it ends up as the redirect target
    after a successful login. Without this guard, a link like
    `…/auth/login?next=https://evil.com` would bounce a freshly
    authenticated user off-site from our trusted domain — a phishing
    primitive. We accept only a single leading slash; `//host` and
    `/\\host` (protocol-relative URLs browsers treat as cross-origin)
    and anything not starting with `/` fall back to /ui/.
    """
    if not target or not target.startswith("/"):
        return "/ui/"
    if target.startswith(("//", "/\\")):
        return "/ui/"
    return target


# --- routes ---------------------------------------------------------------


router = APIRouter(prefix="/auth", tags=["auth"])


def _require_oidc() -> None:
    if not auth.is_enabled():
        raise HTTPException(status_code=404, detail="auth disabled")
    if not is_configured():
        raise HTTPException(status_code=503, detail="OIDC not configured")


@router.get("/login")
async def login(
    request: Request,
    next: str = "/ui/",
    prompt: str | None = None,
):
    """Start the OIDC dance.

    `prompt=select_account` (or any other valid OIDC prompt value)
    is forwarded to Auth0, which forwards it to Google — making Google
    show the account picker instead of silently reusing its cached
    session. Use this when you need to switch identities; the default
    is silent re-auth for normal navigation.
    """
    _require_oidc()
    request.session["post_login_next"] = _safe_next(next)
    redirect_uri = os.environ.get("MYCELIUM_OIDC_REDIRECT_URI") or str(
        request.url_for("auth_callback")
    )
    extra: dict[str, str] = {}
    if prompt:
        extra["prompt"] = prompt
    return await _client().authorize_redirect(request, redirect_uri, **extra)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    _require_oidc()
    try:
        token = await _client().authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OIDC exchange failed: {e}")

    claims = token.get("userinfo") or {}
    issuer = os.environ["MYCELIUM_OIDC_ISSUER"].rstrip("/")
    subject = claims.get("sub") or token.get("sub")
    email = claims.get("email")
    name = claims.get("name") or claims.get("nickname")

    # Log the identity we extracted from the OIDC response. Helpful for
    # diagnosing "this account is not authorized" 403s — tells you
    # whether the email claim is present and matches the bootstrap /
    # invite list. Doesn't log the raw token (too sensitive); only the
    # provisioning-relevant claims.
    logging.getLogger("mycelium.oidc").info(
        "OIDC callback: issuer=%s subject=%s email=%s name=%s claim_keys=%s",
        issuer,
        subject,
        email,
        name,
        sorted(claims.keys()),
    )

    if not subject:
        raise HTTPException(status_code=400, detail="OIDC response missing subject")

    from . import server

    conn = server._auth_conn
    if conn is None:
        raise HTTPException(status_code=500, detail="substrate not initialized")
    user_id = auth.find_or_create_user(
        conn,
        issuer=issuer,
        subject=subject,
        email=email,
        name=name,
    )
    if user_id is None:
        # Refuse to silently create unauthorized users — the user sees
        # a clear "not invited" message rather than a half-broken
        # logged-in state.
        raise HTTPException(
            status_code=403,
            detail="this account is not authorized — request an invite from an admin",
        )

    request.session["user_id"] = user_id
    next_url = request.session.pop("post_login_next", "/ui/")
    return RedirectResponse(url=next_url)


@router.post("/logout")
@router.get("/logout")
async def logout(request: Request, next: str = "/ui/"):
    """Clear the Mycelium session cookie and bounce through Auth0's
    federated-logout endpoint to clear the Auth0 session too, then send
    the user to a fresh login.

    Four layers of state to know about:
      1. Mycelium session cookie — cleared here.
      2. Auth0 session — cleared by Auth0's /v2/logout. THIS is the one
         that matters for the silent-reuse problem: our other apps share
         the same Auth0 tenant, so without clearing it `authorize_redirect`
         would log the user straight back in as whatever account that SSO
         session holds (and provisioning keys on email, so it would bind
         the wrong identity). Clearing it forces fresh credentials / the
         account picker on the next login.
      3. Google session — NOT cleared (upstream of Auth0). To also force
         a different Google account, start the next login with
         `/auth/login?prompt=select_account`.
      4. The next login itself — we point Auth0's `returnTo` at
         `/auth/login` (not the app) so the user lands on a clean login
         against an empty Auth0 session. This is why the middleware sends
         an unauthenticated browser here instead of straight to
         `/auth/login`: logout-then-login is what prevents the silent
         reuse. `next` round-trips so the user still ends up where they
         were headed (defaults to /ui/ for a plain logout-button click).

    `returnTo` must be an absolute URL that's on the Auth0 application's
    Allowed Logout URLs list — make sure `<base>/auth/login` is listed.
    We build it from the request's base URL so the same code works on
    localhost / staging / prod without env config drift.
    """
    from urllib.parse import urlencode

    request.session.clear()
    issuer = os.environ.get("MYCELIUM_OIDC_ISSUER")
    client_id = os.environ.get("MYCELIUM_OIDC_CLIENT_ID")
    base = str(request.base_url).rstrip("/")
    login_url = f"{base}/auth/login?{urlencode({'next': next})}"
    if issuer and client_id and auth.is_enabled():
        params = urlencode({"client_id": client_id, "returnTo": login_url})
        return RedirectResponse(url=f"{issuer.rstrip('/')}/v2/logout?{params}")
    # Auth off / OIDC not configured: nothing to clear upstream, just go
    # to login (which itself no-ops to the app when auth is disabled).
    return RedirectResponse(url=login_url)
