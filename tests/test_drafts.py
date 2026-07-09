"""Draft queue tests.

Covers the contract:
  - A drafter principal's write call auto-creates a session draft and
    queues an op instead of mutating the substrate.
  - An explicit `draft_id` from a writer/admin queues an op against
    that draft without role-fighting.
  - Submit + approve replays ops against the substrate as the curator.
  - Reject leaves substrate untouched.
  - Failed replay halts cleanly.
  - discard_draft_op (MCP) and DELETE /api/drafts/<id>/ops/<seq> drop
    queued ops.

Tests run with auth disabled (so the local-admin principal is in
play); we set the drafter principal directly via contextvar where
needed — that's the same path the streamable-HTTP transport uses.
"""

from fastapi.testclient import TestClient

from mycelium import auth, server, store


def _reset_server() -> None:
    store.reset_substrate()
    server._auth_conn = None
    server._drafts_conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None


def _app(tmp_path, monkeypatch, *, auth_mode: str = "off"):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", auth_mode)
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    _reset_server()
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


def _as_drafter(session_id="sess-1"):
    """Push a drafter principal + session id into the contextvars."""
    p = auth.Principal(id="d1", name="Drafter One", role="drafter", type="human")
    p_tok = auth.current_principal.set(p)
    s_tok = auth.current_session_id.set(session_id)
    return (p_tok, s_tok)


def _restore(tokens):
    p_tok, s_tok = tokens
    auth.current_principal.reset(p_tok)
    auth.current_session_id.reset(s_tok)


def test_drafter_write_creates_session_draft_and_queues_op(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        # No entities in substrate initially.
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM entities")
            .fetchone()["n"]
            == 0
        )

        tokens = _as_drafter()
        try:
            result = server.upsert_entity(name="Acme", description="A test entity")
        finally:
            _restore(tokens)

        # Substrate untouched.
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM entities")
            .fetchone()["n"]
            == 0
        )
        # Receipt shape.
        assert result["queued"] == "upsert_entity"
        assert "draft_id" in result and result["seq"] == 1

        # One draft, one op.
        drafts = server._drafts_conn.execute("SELECT * FROM drafts").fetchall()
        assert len(drafts) == 1
        ops = server._drafts_conn.execute("SELECT * FROM draft_ops").fetchall()
        assert len(ops) == 1
        assert ops[0]["kind"] == "upsert_entity"


def test_drafter_writes_in_same_session_share_one_draft(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-A")
        try:
            r1 = server.upsert_entity(name="Foo", description="x")
            r2 = server.upsert_entity(name="Bar", description="y")
        finally:
            _restore(tokens)
        assert r1["draft_id"] == r2["draft_id"]
        assert r2["seq"] == r1["seq"] + 1


def test_explicit_draft_id_queues_op_for_any_writer(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        # Local-admin (synthetic admin) creates an open draft manually.
        from mycelium import drafts_store

        draft_id = drafts_store.create_draft(
            server._drafts_conn,
            created_by="someone-else",
            session_id=None,
        )
        # Admin caller passes draft_id explicitly — no role flip.
        result = server.upsert_entity(name="Routed", description="r", draft_id=draft_id)
        assert result["draft_id"] == draft_id
        assert result["queued"] == "upsert_entity"
        # Substrate still untouched.
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM entities")
            .fetchone()["n"]
            == 0
        )


def test_submit_then_approve_replays_to_substrate(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        # Drafter queues two upserts.
        tokens = _as_drafter("sess-B")
        try:
            r = server.upsert_entity(name="One", description="d1")
            server.upsert_entity(name="Two", description="d2")
        finally:
            _restore(tokens)
        draft_id = r["draft_id"]

        # Submit, then approve via HTTP (curator path = local-admin here).
        sub = client.post(f"/api/drafts/{draft_id}/submit")
        assert sub.status_code == 200

        appr = client.post(f"/api/drafts/{draft_id}/approve")
        assert appr.status_code == 200, appr.text
        body = appr.json()
        assert body["applied"] == 2

        # Both entities now exist in the substrate.
        rows = (
            store.substrate_connection()
            .execute("SELECT description FROM entities ORDER BY description")
            .fetchall()
        )
        assert [r["description"] for r in rows] == ["d1", "d2"]


def test_reject_leaves_substrate_untouched(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-C")
        try:
            r = server.upsert_entity(name="DontApply", description="nope")
        finally:
            _restore(tokens)
        draft_id = r["draft_id"]

        client.post(f"/api/drafts/{draft_id}/submit")
        rej = client.post(f"/api/drafts/{draft_id}/reject")
        assert rej.status_code == 200
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM entities")
            .fetchone()["n"]
            == 0
        )

        # Draft now in rejected state, no further approve possible.
        appr = client.post(f"/api/drafts/{draft_id}/approve")
        assert appr.status_code == 400


def test_discard_draft_op_drops_a_queued_op(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-D")
        try:
            server.upsert_entity(name="A", description="a")
            r2 = server.upsert_entity(name="B", description="b")
        finally:
            _restore(tokens)
        draft_id = r2["draft_id"]

        # Drop the second op.
        server.discard_draft_op(draft_id=draft_id, seq=2)
        ops = server._drafts_conn.execute(
            "SELECT seq FROM draft_ops WHERE draft_id = ? ORDER BY seq", (draft_id,)
        ).fetchall()
        assert [o["seq"] for o in ops] == [1]


def test_approve_failure_halts_and_does_not_mark_decided(tmp_path, monkeypatch):
    """Queue a deliberately-broken op (delete of a nonexistent statement)
    and confirm approve fails without flipping the draft to approved."""
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-E")
        try:
            # delete_statement on a nonexistent id will raise inside the
            # underlying tool — replay halts on the exception.
            server.delete_statement(id="stm_nonexistent")
        finally:
            _restore(tokens)
        from mycelium import drafts_store

        row = drafts_store.find_open_session_draft(server._drafts_conn, "sess-E")
        draft_id = row["id"]

        client.post(f"/api/drafts/{draft_id}/submit")
        appr = client.post(f"/api/drafts/{draft_id}/approve")
        assert appr.status_code == 400

        # Still in submitted (not approved) state — curator can edit & retry.
        from mycelium import drafts_store

        row = drafts_store.get_draft(server._drafts_conn, draft_id)
        assert drafts_store.status_for(row) == "submitted"


def test_list_drafts_endpoint_returns_counts(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-F")
        try:
            server.upsert_entity(name="One", description="x")
        finally:
            _restore(tokens)
        r = client.get("/api/drafts")
        assert r.status_code == 200
        body = r.json()
        assert len(body["drafts"]) == 1
        assert body["drafts"][0]["op_count"] == 1
        assert body["drafts"][0]["status"] == "open"


def test_list_tools_with_draft_id_return_queued_ops(tmp_path, monkeypatch):
    """list_entities(draft_id=X) returns upsert_entity ops, NOT substrate
    rows. The substrate stays untouched so the ops are the only source."""
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-readback")
        try:
            r = server.upsert_entity(name="Acme", description="d")
            server.upsert_entity(name="Beta", description="d2")
            server.upsert_statement(kind="claim", text="t", links=[])
        finally:
            _restore(tokens)
        draft_id = r["draft_id"]

        # Substrate empty.
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM entities")
            .fetchone()["n"]
            == 0
        )

        # Without draft_id → substrate result (empty).
        assert server.list_entities() == {"entities": [], "total": 0}

        # With draft_id → ops shaped as payloads.
        ents = server.list_entities(draft_id=draft_id)
        assert len(ents) == 2
        assert {e["name"] for e in ents} == {"Acme", "Beta"}
        assert all(e["_kind"] == "upsert_entity" for e in ents)

        # Statement op shows up in list_statements but not list_entities.
        stmts = server.list_statements(draft_id=draft_id)
        assert len(stmts) == 1 and stmts[0]["text"] == "t"


def test_drafter_cannot_approve_their_own_draft(tmp_path, monkeypatch):
    """Approve / reject require a real writer+ — a drafter passing the
    rank shortcut would otherwise re-queue every op at replay time."""
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        tokens = _as_drafter("sess-self-approve")
        try:
            r = server.upsert_entity(name="X", description="x")
        finally:
            _restore(tokens)
        draft_id = r["draft_id"]
        client.post(f"/api/drafts/{draft_id}/submit")

        # Now hit /approve while a drafter principal is in the contextvar.
        # The HTTP middleware would normally set the real authed user; we
        # patch it to a drafter to simulate that flow.
        p_tok = auth.current_principal.set(
            auth.Principal(id="d3", name="D", role="drafter", type="human"),
        )
        try:
            # Bypass middleware by calling the endpoint function directly
            # with a stub request that carries our drafter principal.
            from fastapi import HTTPException

            from mycelium.http import approve_draft

            class _Req:
                class state:
                    principal = auth.Principal(
                        id="d3", name="D", role="drafter", type="human"
                    )

            import pytest

            with pytest.raises(HTTPException) as exc:
                approve_draft(draft_id, _Req())
            assert exc.value.status_code == 403
        finally:
            auth.current_principal.reset(p_tok)


def test_drafter_without_session_id_falls_back_to_actor_scope(tmp_path, monkeypatch):
    """Many MCP clients don't echo Mcp-Session-Id back on tool calls
    (Claude Code, in particular). When the header's missing, the
    auto-draft is scoped per-principal — one open draft at a time across
    all of a drafter's clients."""
    client = _app(tmp_path, monkeypatch)
    with client:
        p = auth.Principal(id="d2", name="X", role="drafter", type="human")
        p_tok = auth.current_principal.set(p)
        try:
            r1 = server.upsert_entity(name="Z", description="z")
            r2 = server.upsert_entity(name="W", description="w")
        finally:
            auth.current_principal.reset(p_tok)
        # Both calls landed in the same auto-draft, no error.
        assert r1["draft_id"] == r2["draft_id"]
        # session_id is the actor fallback marker.
        row = server._drafts_conn.execute(
            "SELECT session_id FROM drafts WHERE id = ?", (r1["draft_id"],)
        ).fetchone()
        assert row["session_id"] == "actor:d2"
