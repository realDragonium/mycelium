"""Tests for the auth scaffold: toggle, principal resolution, tokens.

Phase 1 coverage. Phase 2 will add UI-level token-management tests, and
Phase 3 adds OIDC callback tests; the substrate-level pieces tested here
underpin both.
"""

from fastapi.testclient import TestClient

from mycelium import auth, server


def _reset_server() -> None:
    server._conn = None
    server._auth_conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None


def _app(tmp_path, monkeypatch, *, auth_mode: str = "off"):
    """Build a fresh TestClient with a fresh data dir and toggle state.

    Reimports `http` so the module-level `app` is rebuilt against the
    current env — necessary because `http.py` reads MYCELIUM_DATA_DIR
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
        conn = server._auth_conn
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

        r = client.post(
            "/upsert-entity",
            json={"name": "Bearered", "description": ""},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200


def test_revoked_token_rejected(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = server._auth_conn
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
        conn = server._auth_conn
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
        conn = server._auth_conn
        principal = auth.resolve_token(conn, raw)
        assert principal is not None
        assert principal.role == "writer"

        r = client.delete(f"/api/me/tokens/{token_id}")
        assert r.status_code == 200
        assert auth.resolve_token(conn, raw) is None


# --- Phase 4: admin user / invite endpoints -------------------------------


def _admin_bearer(conn) -> str:
    """Helper: create an admin user + token and return the raw bearer."""
    uid = auth.create_user(
        conn,
        name="Admin",
        role="admin",
        type="human",
        email="admin@example.com",
    )
    conn.commit()
    raw, _ = auth.issue_token(conn, user_id=uid, name="bootstrap", scope="admin")
    return raw


def test_admin_endpoints_require_admin_role(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = server._auth_conn
        uid = auth.create_user(
            conn,
            name="Writer",
            role="writer",
            type="human",
            email="w@example.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="key", scope="writer")
        r = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 403


def test_admin_creates_service_account_and_mints_token(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = server._auth_conn
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
        conn = server._auth_conn
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
        conn = server._auth_conn
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
        conn = server._auth_conn
        uid = auth.create_user(
            conn,
            name="R",
            role="reader",
            type="human",
            email="r@x.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="reader")
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
        conn = server._auth_conn
        uid = auth.create_user(
            conn,
            name="W",
            role="writer",
            type="human",
            email="w@x.com",
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="writer")
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
    Verified at the server's request-handler level — what arrives over
    the MCP wire is whatever this handler returns, so this test covers
    both the stdio and HTTP transports.
    """
    import asyncio

    import mcp.types as mt

    # The filter is driven by the principal in the contextvar, not by
    # auth-mode; we manipulate it manually below. Run with auth off
    # to keep the test from needing a session secret on a fresh
    # http.py import.
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        from mycelium import server

        handler = server.mcp._mcp_server.request_handlers[mt.ListToolsRequest]
        req = mt.ListToolsRequest(method="tools/list")

        async def call_with(role: auth.Role):
            token = auth.current_principal.set(
                auth.Principal(id="t", name="t", role=role, type="human"),
            )
            try:
                result = await handler(req)
                return {t.name for t in result.root.tools}
            finally:
                auth.current_principal.reset(token)

        reader = asyncio.run(call_with("reader"))
        writer = asyncio.run(call_with("writer"))
        admin = asyncio.run(call_with("admin"))

        # Reader gets read-shaped tools plus any explicit role="reader"
        # overrides: report_knowledge_gap (a write anyone may do),
        # survey_statements (a read whose name isn't a read-prefix), and
        # ask (the higher-level read entry point, likewise un-prefixed).
        READER_OVERRIDES = {"report_knowledge_gap", "survey_statements", "ask"}
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


def test_admin_can_delete(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = server._auth_conn
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
        conn = server._auth_conn
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
