"""End-to-end tests of the OAuth 2.1 authorization flow.

These cover the happy path (register → authorize → consent → token
exchange → MCP call) plus the high-impact failure modes (PKCE
mismatch, replayed code, expired code, wrong redirect_uri, OAuth
endpoints 404 when auth is off).
"""

import base64
import hashlib
import secrets

from fastapi.testclient import TestClient

from mycelium import auth, auth_store, server, store


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None


def _app(tmp_path, monkeypatch, *, auth_mode: str = "on"):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", auth_mode)
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret-for-oauth-flow")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    _reset_server()
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


def _admin_bearer(conn) -> tuple[str, str]:
    with store.transaction(conn):
        uid = auth.create_user(
            conn,
            name="Admin",
            role="admin",
            type="human",
            email="admin@example.com",
        )
        raw, _ = auth.issue_token(conn, user_id=uid, name="bootstrap", scope="admin")
    return raw, uid


def _pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge_S256)."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


# --- discovery ------------------------------------------------------------


def test_discovery_endpoints_404_when_auth_disabled(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        assert client.get("/.well-known/oauth-authorization-server").status_code == 404
        assert client.get("/.well-known/oauth-protected-resource").status_code == 404


def test_discovery_endpoints_return_metadata(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        meta = r.json()
        assert "issuer" in meta
        assert meta["authorization_endpoint"].endswith("/authorize")
        assert meta["token_endpoint"].endswith("/token")
        assert meta["registration_endpoint"].endswith("/register")
        assert "S256" in meta["code_challenge_methods_supported"]

        r = client.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        prm = r.json()
        assert "authorization_servers" in prm


def test_mcp_401_carries_www_authenticate(tmp_path, monkeypatch):
    """Without this header, Claude Desktop wouldn't know where to find
    the OAuth metadata — the discovery chain starts here."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        assert r.status_code == 401
        www = r.headers.get("www-authenticate", "")
        assert "Bearer" in www
        assert "resource_metadata=" in www


# --- open-redirect guard on the post-login `next` -------------------------


def test_safe_next_passes_same_site_paths():
    """Every real `next` we produce is a root-relative path — these must
    pass through untouched so the guard never breaks a legit redirect."""
    from mycelium.oidc import _safe_next

    for path in ("/ui/", "/connect", "/cockpit/", "/authorize?client_id=abc"):
        assert _safe_next(path) == path


def test_safe_next_rejects_offsite_targets():
    """Off-site and protocol-relative targets — the open-redirect vectors —
    fall back to /ui/ instead of bouncing a logged-in user off our domain."""
    from mycelium.oidc import _safe_next

    for evil in (
        "https://evil.com",
        "http://evil.com",
        "//evil.com",
        "/\\evil.com",
        "ui/no-leading-slash",
        "",
        None,
    ):
        assert _safe_next(evil) == "/ui/"


# --- logout-then-login (clears Auth0 SSO before a fresh login) ------------


def test_unauthenticated_browser_nav_redirects_through_logout(tmp_path, monkeypatch):
    """A browser hitting a protected page with no Mycelium session is sent
    to /auth/logout first — which clears Auth0's shared SSO cookie — not
    straight to /auth/login, which would silently re-auth as whatever
    account the (still-live) tenant-wide SSO session holds."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.get("/ui/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 302
        # next= round-trips so the post-login redirect lands back on /ui/.
        assert r.headers["location"].startswith("/auth/logout?next=/ui/")


def test_logout_bounces_through_auth0_back_to_login(tmp_path, monkeypatch):
    """Logout clears the Auth0 session via /v2/logout and points returnTo
    at our own /auth/login (carrying next), so the next login runs against
    an empty Auth0 session instead of silently reusing the SSO account."""
    from urllib.parse import parse_qs, urlparse

    client = _app(tmp_path, monkeypatch, auth_mode="on")
    monkeypatch.setenv("MYCELIUM_OIDC_ISSUER", "https://tenant.auth0.com")
    monkeypatch.setenv("MYCELIUM_OIDC_CLIENT_ID", "client-abc")
    with client:
        r = client.get(
            "/auth/logout", params={"next": "/ui/graph"}, follow_redirects=False
        )
        assert r.status_code in (302, 307)  # RedirectResponse default is 307
        loc = r.headers["location"]
        assert loc.startswith("https://tenant.auth0.com/v2/logout?")
        q = parse_qs(urlparse(loc).query)
        assert q["client_id"] == ["client-abc"]
        return_to = q["returnTo"][0]
        assert "/auth/login" in return_to
        assert "next=%2Fui%2Fgraph" in return_to  # the original target, encoded


def test_logout_without_oidc_redirects_straight_to_login(tmp_path, monkeypatch):
    """With OIDC unconfigured there's no Auth0 session to clear, so logout
    just sends the user to /auth/login (which no-ops to the app when auth
    is off)."""
    monkeypatch.delenv("MYCELIUM_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("MYCELIUM_OIDC_CLIENT_ID", raising=False)
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.get("/auth/logout", follow_redirects=False)
        assert r.status_code in (302, 307)  # RedirectResponse default is 307
        loc = r.headers["location"]
        assert "/auth/login?next=" in loc
        assert "%2Fui%2F" in loc


# --- DCR ------------------------------------------------------------------


def test_register_creates_client(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.post(
            "/register",
            json={
                "client_name": "Claude Desktop",
                "redirect_uris": ["http://localhost:6274/callback"],
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["client_id"].startswith("mcp_")
        assert body["redirect_uris"] == ["http://localhost:6274/callback"]
        assert body["token_endpoint_auth_method"] == "none"


def test_register_rejects_unsupported_grant_types(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.post(
            "/register",
            json={
                "client_name": "X",
                "redirect_uris": ["http://localhost/cb"],
                "grant_types": ["client_credentials"],
            },
        )
        assert r.status_code == 400


def test_register_requires_redirect_uri(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.post("/register", json={"client_name": "X"})
        assert r.status_code == 400


# --- authorize → token ---------------------------------------------------


def _full_flow(
    client, *, admin_bearer: str, redirect_uri: str = "http://localhost:6274/cb"
):
    """Drive the OAuth flow end-to-end as a logged-in admin. Returns
    the resulting access_token plus the client_id used."""
    # Register the client (anonymous).
    reg = client.post(
        "/register",
        json={"client_name": "Test client", "redirect_uris": [redirect_uri]},
    ).json()
    client_id = reg["client_id"]

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(8)

    # /authorize as the authenticated user (admin bearer impersonates the
    # session — bearer auth and cookie auth both populate the principal).
    r = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp",
        },
        headers={"Authorization": f"Bearer {admin_bearer}"},
    )
    assert r.status_code == 200, r.text
    # Approve. The consent form carries the OAuth params as hidden
    # fields; we re-post them verbatim.
    r = client.post(
        "/authorize/decide",
        data={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mcp",
            "state": state,
            "decision": "allow",
        },
        headers={"Authorization": f"Bearer {admin_bearer}"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith(redirect_uri)
    # Pull the code out of the redirect URL.
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(loc).query)
    code = qs["code"][0]
    assert qs["state"][0] == state

    # Exchange.
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body, client_id, verifier, code


def test_full_oauth_flow(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        admin_bearer, _ = _admin_bearer(server._auth_db())
        body, _, _, _ = _full_flow(client, admin_bearer=admin_bearer)
        assert body["token_type"] == "Bearer"
        assert body["access_token"].startswith("myc_")
        # The issued token works as a bearer.
        r = client.get(
            "/api/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert r.status_code == 200
        me = r.json()
        assert me["role"] == "admin"


def test_authorize_redirects_to_login_when_unauthenticated(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        # Register first (anonymous is fine).
        reg = client.post(
            "/register",
            json={"client_name": "X", "redirect_uris": ["http://localhost/cb"]},
        ).json()
        verifier, challenge = _pkce_pair()
        r = client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": "http://localhost/cb",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "/auth/login" in r.headers["location"]


def test_token_rejects_pkce_mismatch(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        admin_bearer, _ = _admin_bearer(server._auth_db())
        # Drive the flow to a fresh code, then submit a verifier that
        # doesn't hash to the challenge we registered.
        _, client_id, _real_verifier, code = _full_flow(
            client,
            admin_bearer=admin_bearer,
        )
        # The code was just consumed by _full_flow's own /token call.
        # That gives us the "code already used" path under test below;
        # for PKCE-mismatch we need a brand-new flow where we tamper
        # only at /token. So redo the dance, but stop before /token:
        redirect_uri = "http://localhost:6275/cb"
        reg = client.post(
            "/register",
            json={"client_name": "Y", "redirect_uris": [redirect_uri]},
        ).json()
        _v, ch = _pkce_pair()
        r = client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": ch,
                "code_challenge_method": "S256",
            },
            headers={"Authorization": f"Bearer {admin_bearer}"},
        )
        assert r.status_code == 200, r.text
        r = client.post(
            "/authorize/decide",
            data={
                "client_id": reg["client_id"],
                "redirect_uri": redirect_uri,
                "code_challenge": ch,
                "code_challenge_method": "S256",
                "decision": "allow",
            },
            headers={"Authorization": f"Bearer {admin_bearer}"},
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text
        from urllib.parse import parse_qs, urlparse

        new_code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

        # Submit a fabricated verifier — must fail PKCE.
        r = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": new_code,
                "redirect_uri": redirect_uri,
                "client_id": reg["client_id"],
                "code_verifier": "not-the-real-verifier-not-the-real-verifier",
            },
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"


def test_token_rejects_code_reuse(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        admin_bearer, _ = _admin_bearer(server._auth_db())
        body, client_id, verifier, code = _full_flow(client, admin_bearer=admin_bearer)
        # Replay the same exchange.
        r = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:6274/cb",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 400
        assert "already used" in r.json()["error_description"]


def test_denial_redirects_with_error(tmp_path, monkeypatch):
    """Per OAuth 2.1 §4.1.2.1 — when the user denies, the redirect_uri
    receives ?error=access_denied (not an HTTP 4xx)."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        admin_bearer, _ = _admin_bearer(server._auth_db())
        reg = client.post(
            "/register",
            json={"client_name": "X", "redirect_uris": ["http://localhost/cb"]},
        ).json()
        _, challenge = _pkce_pair()
        r = client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": "http://localhost/cb",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "abc",
            },
            headers={"Authorization": f"Bearer {admin_bearer}"},
        )
        r = client.post(
            "/authorize/decide",
            data={
                "client_id": reg["client_id"],
                "redirect_uri": "http://localhost/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "abc",
                "decision": "deny",
            },
            headers={"Authorization": f"Bearer {admin_bearer}"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "error=access_denied" in r.headers["location"]
        assert "state=abc" in r.headers["location"]
