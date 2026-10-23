"""Tests for the auth scaffold: toggle, principal resolution, tokens.

Phase 1 coverage. Phase 2 will add UI-level token-management tests, and
Phase 3 adds OIDC callback tests; the substrate-level pieces tested here
underpin both.
"""

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, store
from mycelium.server import registry, runtime


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    runtime._ctx = None


def _app(tmp_path, monkeypatch, *, auth_mode: str = "off"):
    """Build a fresh TestClient with a fresh data dir and toggle state.

    Reimports `http` so the module-level `app` is rebuilt against the
    current env — necessary because `mycelium.http` reads MYCELIUM_DATA_DIR
    inside its lifespan, but the AuthMiddleware is registered at import.
    """
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", auth_mode)
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    _reset_server()
    # Stub the embedder so server.init doesn't reach for Ollama.
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


def test_auth_off_grants_local_admin(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        # An anonymous request to a write endpoint should succeed —
        # synthetic local-admin has writer privileges.
        r = client.post("/upsert-entity", json={"name": "Anonymous", "description": ""})
        assert r.status_code == 200


def test_auth_on_rejects_anonymous(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        r = client.post("/upsert-entity", json={"name": "Anonymous", "description": ""})
        assert r.status_code == 401


def test_auth_on_exempts_ui_routes(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        # UI bundle and root redirect must remain reachable so the user
        # can navigate to login. They should NOT silently receive the
        # local-admin principal — that's the on-mode contract — but the
        # response itself goes through.
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (200, 307)


def test_auth_on_accepts_valid_bearer(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        # Mint a user + token directly against the substrate; Phase 4
        # will provide an admin UI to do this through HTTP.
        conn = runtime._auth_db()
        assert conn is not None
        user_id = auth.create_user(
            conn,
            name="Test Writer",
            role="writer",
            type="human",
            email="writer@example.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(
            conn,
            user_id=user_id,
            name="laptop",
            scope="writer",
        )
        conn.commit()

        r = client.post(
            "/upsert-entity",
            json={"name": "Bearered", "description": ""},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200


def test_revoked_token_rejected(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        assert conn is not None
        user_id = auth.create_user(
            conn,
            name="Soon Revoked",
            role="writer",
            type="human",
            email="revoke@example.com",
        )
        conn.commit()
        raw, token_id = auth.issue_token(
            conn,
            user_id=user_id,
            name="ci-bot",
            scope="writer",
        )
        auth.revoke_token(conn, token_id)
        conn.commit()

        r = client.post(
            "/upsert-entity",
            json={"name": "Nope", "description": ""},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 401


def test_scope_clamps_against_user_role(tmp_path, monkeypatch):
    """A token can't grant more than the user currently has. We mint a
    token with `admin` scope, then demote the user to `reader`. The
    effective principal must be `reader` — proving the live clamp."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        assert conn is not None
        user_id = auth.create_user(
            conn,
            name="Demoted",
            role="admin",
            type="human",
            email="demote@example.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(
            conn,
            user_id=user_id,
            name="key",
            scope="admin",
        )
        conn.execute("UPDATE users SET role = 'reader' WHERE id = ?", (user_id,))
        conn.commit()

        principal = auth.resolve_token(conn, raw)
        assert principal is not None
        assert principal.role == "reader"


def test_token_format_and_hash_roundtrip():
    raw, prefix, h = auth.generate_token()
    assert raw.startswith("myc_")
    assert f"_{prefix}_" in raw
    assert auth.hash_token(raw) == h
    # New tokens are unique even with the same caller.
    raw2, _, _ = auth.generate_token()
    assert raw != raw2


def test_parse_bearer_rejects_non_mycelium():
    assert auth.parse_bearer(None) is None
    assert auth.parse_bearer("") is None
    assert auth.parse_bearer("Basic abc") is None
    assert auth.parse_bearer("Bearer ghp_some_github_token") is None
    assert auth.parse_bearer("Bearer myc_abc_def") == "myc_abc_def"


# --- Phase 2: /api/me + /api/me/tokens endpoints --------------------------


def test_me_endpoint_returns_principal(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        r = client.get("/api/me")
        assert r.status_code == 200
        me = r.json()
        assert me["role"] == "admin"
        assert me["synthetic"] is True
        assert me["auth_enabled"] is False


def test_token_lifecycle_via_http(tmp_path, monkeypatch):
    """Create → list → use → revoke through the HTTP surface, end to
    end. With auth off, the synthetic local-admin mints against a
    lazily-created placeholder row, which is the path you'd take on a
    fresh checkout to set up Claude Desktop without ever turning auth
    on."""
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        r = client.post("/api/me/tokens", json={"name": "laptop", "scope": "writer"})
        assert r.status_code == 200
        body = r.json()
        raw = body["token"]
        assert raw.startswith("myc_")

        r = client.get("/api/me/tokens")
        assert r.status_code == 200
        tokens = r.json()["tokens"]
        assert len(tokens) == 1
        assert tokens[0]["name"] == "laptop"
        token_id = tokens[0]["id"]

        # The minted token actually authenticates (with auth on) — flip
        # the toggle mid-test by clearing the env and reusing the same
        # data dir. We can't easily restart the app here; instead, prove
        # the bearer path resolves the token directly.
        conn = runtime._auth_db()
        # resolve_token bumps last_used_at; own that write in a transaction
        # (as the middleware does) so this thread's connection commits and
        # releases the lock before the delete request writes on another.
        with store.transaction(conn):
            principal = auth.resolve_token(conn, raw)
        assert principal is not None
        assert principal.role == "writer"

        r = client.delete(f"/api/me/tokens/{token_id}")
        assert r.status_code == 200
        assert auth.resolve_token(conn, raw) is None


# --- Phase 4: admin user / invite endpoints -------------------------------


def _admin_bearer(conn) -> str:
    """Helper: create an admin user + token and return the raw bearer.

    Wrapped in one `store.transaction` so both writes commit before the
    request thread (its own auth connection) tries to resolve the bearer."""
    with store.transaction(conn):
        uid = auth.create_user(
            conn,
            name="Admin",
            role="admin",
            type="human",
            email="admin@example.com",
        )
        raw, _ = auth.issue_token(conn, user_id=uid, name="bootstrap", scope="admin")
    return raw


def test_admin_endpoints_require_admin_role(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        uid = auth.create_user(
            conn,
            name="Writer",
            role="writer",
            type="human",
            email="w@example.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="key", scope="writer")
        conn.commit()
        r = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 403


def test_admin_creates_service_account_and_mints_token(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        admin = _admin_bearer(conn)
        h = {"Authorization": f"Bearer {admin}"}

        r = client.post(
            "/api/admin/users",
            json={"name": "ci-agent", "type": "service", "role": "writer"},
            headers=h,
        )
        assert r.status_code == 200
        svc_id = r.json()["user"]["id"]

        r = client.post(
            f"/api/admin/users/{svc_id}/tokens",
            json={"name": "ci-key", "scope": "writer"},
            headers=h,
        )
        assert r.status_code == 200
        ci_raw = r.json()["token"]

        # The CI key actually authenticates as the service account.
        r = client.post(
            "/upsert-entity",
            json={"name": "made-by-ci", "description": ""},
            headers={"Authorization": f"Bearer {ci_raw}"},
        )
        assert r.status_code == 200


def test_invite_flow_creates_link(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        admin = _admin_bearer(conn)
        h = {"Authorization": f"Bearer {admin}"}

        r = client.post(
            "/api/admin/invites",
            json={"email": "newperson@example.com", "role": "writer"},
            headers=h,
        )
        assert r.status_code == 200
        assert "/auth/invite/" in r.json()["link"]

        r = client.get("/api/admin/invites", headers=h)
        assert r.status_code == 200
        invites = r.json()["invites"]
        assert any(i["email"] == "newperson@example.com" for i in invites)


def test_cannot_demote_last_admin(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        admin_raw = _admin_bearer(conn)
        h = {"Authorization": f"Bearer {admin_raw}"}
        admin_id = conn.execute(
            "SELECT id FROM users WHERE email = 'admin@example.com'"
        ).fetchone()["id"]

        r = client.patch(
            f"/api/admin/users/{admin_id}",
            json={"role": "writer"},
            headers=h,
        )
        assert r.status_code == 400


# --- Phase 5: tool-surface authorization ---------------------------------


def test_reader_can_read_but_not_write(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        uid = auth.create_user(
            conn,
            name="R",
            role="reader",
            type="human",
            email="r@x.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="reader")
        conn.commit()
        h = {"Authorization": f"Bearer {raw}"}

        # list_* is read → allowed
        assert client.post("/list-entities", json={}, headers=h).status_code == 200
        # upsert-entity is write → forbidden
        r = client.post(
            "/upsert-entity",
            json={"name": "Nope", "description": ""},
            headers=h,
        )
        assert r.status_code == 403


def test_writer_can_write_but_not_delete(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        uid = auth.create_user(
            conn,
            name="W",
            role="writer",
            type="human",
            email="w@x.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="writer")
        conn.commit()
        h = {"Authorization": f"Bearer {raw}"}

        r = client.post(
            "/upsert-entity",
            json={"name": "Writable", "description": ""},
            headers=h,
        )
        assert r.status_code == 200
        eid = r.json()["entity_id"]
        r = client.post(
            "/delete-entity",
            json={"id": eid},
            headers=h,
        )
        assert r.status_code == 403  # delete_* requires admin


def test_tool_list_filtered_by_role(tmp_path, monkeypatch):
    """A reader's tools/list response shouldn't carry write tools.

    Drives the filtering middleware over the server's real tool list. Every
    transport's `tools/list` passes through this one middleware, so covering
    it here covers stdio and HTTP, on both protocol revisions.
    """
    import asyncio
    from types import SimpleNamespace

    from mcp.types import ListToolsResult

    # The filter is driven by the principal in the contextvar, not by
    # auth-mode; we manipulate it manually below. Run with auth off
    # to keep the test from needing a session secret on a fresh
    # `mycelium.http` import.
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        from mycelium import server

        middleware = registry._RoleFilteredTools()
        # Only `.method` is read; a stub keeps the test off the SDK's
        # session-bound context construction.
        ctx = SimpleNamespace(method="tools/list")

        async def unfiltered(_ctx):
            # The dispatcher serializes the handler's result before the
            # middleware chain sees it, so hand over the wire dict — feeding
            # the model here would test a shape that never reaches the
            # middleware in a live server.
            result = ListToolsResult(tools=await server.mcp.list_tools())
            return result.model_dump(by_alias=True, mode="json", exclude_none=True)

        async def call_with(role: auth.Role):
            token = auth.current_principal.set(
                auth.Principal(id="t", name="t", role=role, type="human"),
            )
            try:
                result = await middleware(ctx, unfiltered)
                return {t["name"] for t in result["tools"]}
            finally:
                auth.current_principal.reset(token)

        reader = asyncio.run(call_with("reader"))
        writer = asyncio.run(call_with("writer"))
        admin = asyncio.run(call_with("admin"))

        # Reader gets read-shaped tools plus the explicit role="reader"
        # overrides on the MCP surface: report_knowledge_gap (a write anyone
        # may do) and ask (the higher-level read entry point, un-prefixed).
        READER_OVERRIDES = {"report_knowledge_gap", "ask"}
        assert all(
            n.startswith(("list_", "get_", "search_", "grep_", "discover_", "find_"))
            or n in READER_OVERRIDES
            for n in reader
        ), f"reader saw non-read tool: {reader}"
        # No destructive tools.
        assert not any(n.startswith(("delete_", "merge_")) for n in reader)

        # Writer = reader superset + non-destructive writes.
        assert reader.issubset(writer)
        assert "upsert_entity" in writer
        assert not any(n.startswith(("delete_", "merge_")) for n in writer)

        # Admin = everything.
        assert writer.issubset(admin)
        assert any(n.startswith("delete_") for n in admin)
        assert any(n.startswith("merge_") for n in admin)


def test_tool_list_hides_tools_whose_gate_is_stricter_than_its_prefix(
    tmp_path, monkeypatch
):
    """A listed tool must be one the caller can actually invoke.

    The documentation tools declare `real_role=True`, dropping the drafter
    equivalence that `principal_satisfies` grants. Deriving visibility from
    the name alone would advertise them to a drafter, and the call would
    then be refused.
    """
    import asyncio
    from types import SimpleNamespace

    from mcp.types import ListToolsResult

    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        from mycelium import server

        middleware = registry._RoleFilteredTools()
        ctx = SimpleNamespace(method="tools/list")

        async def unfiltered(_ctx):
            result = ListToolsResult(tools=await server.mcp.list_tools())
            return result.model_dump(by_alias=True, mode="json", exclude_none=True)

        async def listed_for(role: auth.Role):
            token = auth.current_principal.set(
                auth.Principal(id="t", name="t", role=role, type="human"),
            )
            try:
                result = await middleware(ctx, unfiltered)
                return {t["name"] for t in result["tools"]}
            finally:
                auth.current_principal.reset(token)

        reader = asyncio.run(listed_for("reader"))
        drafter = asyncio.run(listed_for("drafter"))
        writer = asyncio.run(listed_for("writer"))
        admin = asyncio.run(listed_for("admin"))

        # Lands live, never queues onto a draft.
        assert "request_documentation" not in reader
        assert "request_documentation" not in drafter
        assert "request_documentation" in writer
        assert "revise_document" not in drafter
        assert "revise_document" in writer

        # Admin-only by prefix; a drafter's call queues onto a draft instead.
        assert "delete_statement" in drafter
        assert "delete_statement" not in writer
        assert "delete_statement" in admin


def test_admin_can_delete(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        raw = _admin_bearer(conn)
        h = {"Authorization": f"Bearer {raw}"}
        eid = client.post(
            "/upsert-entity",
            json={"name": "Doomed", "description": ""},
            headers=h,
        ).json()["entity_id"]
        r = client.post(
            "/delete-entity",
            json={"id": eid},
            headers=h,
        )
        assert r.status_code == 200


def test_scope_capped_at_creation(tmp_path, monkeypatch):
    """A reader trying to mint a writer token gets a writer-capped
    request silently clamped to reader. Belt-and-braces with the
    live-clamp at resolve time."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        user_id = auth.create_user(
            conn,
            name="R",
            role="reader",
            type="human",
            email="r@example.com",
        )
        conn.commit()
        # Use an admin-scope cookie-equivalent via direct token use:
        # mint an admin token directly so we can hit the HTTP endpoint
        # as this user.
        raw, _ = auth.issue_token(
            conn, user_id=user_id, name="bootstrap", scope="reader"
        )
        conn.commit()

        r = client.post(
            "/api/me/tokens",
            json={"name": "tried-to-escalate", "scope": "admin"},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200
        # Server should have capped the scope down to the user's role.
        tokens = client.get(
            "/api/me/tokens",
            headers={"Authorization": f"Bearer {raw}"},
        ).json()["tokens"]
        names = {t["name"]: t["scope"] for t in tokens}
        assert names["tried-to-escalate"] == "reader"


def test_asker_reaches_ask_and_its_own_account_but_no_substrate_reads(
    tmp_path, monkeypatch
):
    """`asker` is the role for callers that may only ask. The hand-written
    UI routes read the substrate without going through a tool's role gate,
    so they must not answer an asker either."""
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        with store.transaction(conn):
            uid = auth.create_user(
                conn, name="A", role="asker", type="service", email=None
            )
            raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="asker")
        h = {"Authorization": f"Bearer {raw}"}

        for path in ("/api/data", "/api/history", "/api/drafts", "/api/audiences"):
            assert client.get(path, headers=h).status_code == 403, path
        assert client.get("/api/me", headers=h).status_code == 200
        assert client.get("/api/me/tokens", headers=h).status_code == 200


def test_every_response_refuses_to_be_framed(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        r = client.get("/connect")
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_cross_origin_requests_cannot_ride_ambient_credentials(tmp_path, monkeypatch):
    """With auth off every request is the local admin, and with auth on a
    browser attaches the session cookie to same-site requests. Either way a
    page on another origin could otherwise POST to a bodiless route, such as
    approving a draft, as the person whose browser it runs in."""
    client = _app(tmp_path, monkeypatch)
    with client:
        url = "/api/drafts/drf_missing/approve"
        forged = (
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "https://evil.example"},
        )
        for headers in forged:
            assert client.post(url, headers=headers).status_code == 403, headers

        allowed = (
            {},
            {"Sec-Fetch-Site": "same-origin"},
            {"Origin": "http://testserver"},
        )
        for headers in allowed:
            assert client.post(url, headers=headers).status_code != 403, headers
        assert client.get("/api/drafts", headers=forged[0]).status_code == 200


@pytest.mark.parametrize(
    ("env", "secure"),
    [
        ({}, False),
        ({"MYCELIUM_PUBLIC_URL": "http://localhost:8765"}, False),
        ({"MYCELIUM_PUBLIC_URL": "https://kb.example.com"}, True),
        ({"MYCELIUM_OIDC_REDIRECT_URI": "https://kb.example.com/auth/callback"}, True),
    ],
)
def test_session_cookie_is_secure_when_served_over_https(monkeypatch, env, secure):
    from mycelium.http import authentication

    for name in ("MYCELIUM_PUBLIC_URL", "MYCELIUM_OIDC_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert authentication.session_cookie_secure() is secure


def test_only_read_tools_answer_get(tmp_path, monkeypatch):
    """A browser follows a link or loads an image with GET and the session
    cookie, from any site. `submit_draft` takes only an optional `draft_id`,
    so it was mirrored as GET too: one link would submit the visitor's open
    draft."""
    client = _app(tmp_path, monkeypatch)
    with client:
        assert client.get("/submit-draft").status_code in (404, 405)
        assert client.post("/submit-draft", json={}).status_code == 400
        assert client.get("/list-my-drafts").status_code == 200


def test_rebound_hostname_cannot_reach_a_local_server(tmp_path, monkeypatch):
    """DNS rebinding: an attacker's domain re-pointed at 127.0.0.1 makes its
    pages same-origin with a local server, and with auth off every request
    they send is the local admin. Only the Host header gives them away."""
    monkeypatch.delenv("MYCELIUM_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MYCELIUM_PUBLIC_URL", raising=False)
    client = _app(tmp_path, monkeypatch)
    with client:

        def status(host: str, path: str = "/api/drafts") -> int:
            return client.get(path, headers={"Host": host}).status_code

        assert status("rebound.example") == 421
        assert status("rebound.example:8765") == 421
        for host in ("localhost:8765", "127.0.0.1", "[::1]:8765"):
            assert status(host) == 200, host
        # A load balancer's health probe names the instance address.
        assert status("10.0.0.7:8765", "/api/server-info") == 200

        monkeypatch.setenv("MYCELIUM_ALLOWED_HOSTS", "kb.example.com, alt.example.com")
        assert status("kb.example.com") == 200
        assert status("ALT.example.com:443") == 200
        monkeypatch.setenv("MYCELIUM_PUBLIC_URL", "https://public.example.com")
        assert status("public.example.com") == 200
        assert status("rebound.example") == 421


def test_auth_on_checks_the_host_once_hostnames_are_configured(tmp_path, monkeypatch):
    """With auth on a rebound page holds no credential, and an existing
    deployment that never listed its hostname must keep answering."""
    monkeypatch.delenv("MYCELIUM_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MYCELIUM_PUBLIC_URL", raising=False)
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        assert (
            client.get("/api/me", headers={"Host": "kb.example.com"}).status_code == 401
        )
        monkeypatch.setenv("MYCELIUM_PUBLIC_URL", "https://kb.example.com")
        assert (
            client.get("/api/me", headers={"Host": "kb.example.com"}).status_code == 401
        )
        assert (
            client.get("/api/me", headers={"Host": "other.example"}).status_code == 421
        )


def test_oversized_request_body_is_refused(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        big = b"x" * (4 * 1024 * 1024 + 1)
        r = client.post(
            "/report-knowledge-gap",
            content=big,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413

        def chunks():
            yield big[: len(big) // 2]
            yield big[len(big) // 2 :]

        r = client.post(
            "/report-knowledge-gap",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
