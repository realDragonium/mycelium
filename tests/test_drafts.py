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
  - An op carries optional provenance, and replay resolves cross-op
    `@<seq>:<index>` statement references without touching an
    `upsert_statements` payload's own bare `@N` siblings.

Tests run with auth disabled (so the local-admin principal is in
play); we set the drafter principal directly via contextvar where
needed — that's the same path the streamable-HTTP transport uses.
"""

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, drafts_store, server, store, vector
from mycelium.connect import extract
from mycelium.connect.draft import BatchInput, assemble_draft


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    server._ctx = None


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
        drafts = server._drafts_db().execute("SELECT * FROM drafts").fetchall()
        assert len(drafts) == 1
        ops = server._drafts_db().execute("SELECT * FROM draft_ops").fetchall()
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
            server._drafts_db(),
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
        with store.transaction(server._drafts_db()):
            flag_seq = drafts_store.add_op(
                server._drafts_db(),
                draft_id=draft_id,
                kind="flag",
                payload={"reason": "unmatched"},
                created_by="d1",
            )

        # Submit, then approve via HTTP (curator path = local-admin here).
        sub = client.post(f"/api/drafts/{draft_id}/submit")
        assert sub.status_code == 200

        appr = client.post(f"/api/drafts/{draft_id}/approve")
        assert appr.status_code == 200, appr.text
        body = appr.json()
        assert body["applied"] == 2
        assert body["skipped"] == 1
        assert body["results"][-1] == {
            "seq": flag_seq,
            "kind": "flag",
            "skipped": "flag",
        }

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
        ops = (
            server._drafts_db()
            .execute(
                "SELECT seq FROM draft_ops WHERE draft_id = ? ORDER BY seq", (draft_id,)
            )
            .fetchall()
        )
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

        row = drafts_store.find_open_session_draft(server._drafts_db(), "sess-E", "d1")
        draft_id = row["id"]

        client.post(f"/api/drafts/{draft_id}/submit")
        appr = client.post(f"/api/drafts/{draft_id}/approve")
        assert appr.status_code == 400

        # Still in submitted (not approved) state — curator can edit & retry.
        from mycelium import drafts_store

        row = drafts_store.get_draft(server._drafts_db(), draft_id)
        assert drafts_store.status_for(row) == "submitted"


def test_approve_failure_restores_vector_indexes(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-index-rollback")
        try:
            queued = server.upsert_statement(
                kind="state", text="the flow halts", links=[]
            )
            server.upsert_entity(name="Rollback Fixture", description="test entity")
            server.delete_statement(id="stm_nonexistent")
        finally:
            _restore(tokens)
        draft_id = queued["draft_id"]
        statement_ids_before = server._idx().ids()
        name_ids_before = server._name_idx().ids()
        assert statement_ids_before == []
        assert name_ids_before == []

        submitted = client.post(f"/api/drafts/{draft_id}/submit")
        assert submitted.status_code == 200
        approved = client.post(f"/api/drafts/{draft_id}/approve")
        assert approved.status_code == 400

        conn = store.substrate_connection()
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
        assert server._idx().ids() == statement_ids_before
        assert server._name_idx().ids() == name_ids_before

        index_path = tmp_path / "mycelium.vec"
        name_index_path = tmp_path / "mycelium-names.vec"
        assert vector.Index.load(index_path).ids() == statement_ids_before
        assert vector.Index.load(name_index_path).ids() == name_ids_before
        assert list(tmp_path.glob("*.pre-apply*")) == []


def test_commit_failure_rolls_back_and_restores_indexes(tmp_path, monkeypatch):
    class FlakyCommitConnection(sqlite3.Connection):
        fail_commits = False

        def commit(self) -> None:
            if FlakyCommitConnection.fail_commits:
                raise sqlite3.OperationalError("injected commit failure")
            super().commit()

    real_connect = sqlite3.connect

    def connect_with_flaky_substrate(database, *args, **kwargs):
        if Path(str(database)).name == "mycelium.db":
            kwargs["factory"] = FlakyCommitConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_with_flaky_substrate)
    client = _app(tmp_path, monkeypatch)

    with client:
        tokens = _as_drafter("sess-commit-failure")
        try:
            queued = server.upsert_statement(
                kind="state", text="the flow halts", links=[]
            )
            server.upsert_entity(name="Commit Fixture", description="test entity")
        finally:
            _restore(tokens)
        draft_id = queued["draft_id"]

        FlakyCommitConnection.fail_commits = True
        try:
            with pytest.raises(sqlite3.OperationalError):
                server.apply_draft(draft_id)
        finally:
            FlakyCommitConnection.fail_commits = False

        conn = store.substrate_connection()
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
        assert server._idx().ids() == []
        assert server._name_idx().ids() == []

        # Suppress plural-name generation so "After" contributes exactly one
        # name vector and the count below stays exact.
        monkeypatch.setattr(server.plurals, "regular_plural", lambda _: None)
        server.upsert_entity(name="After", description="x")

        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
        assert server._idx().ids() == []
        assert len(server._name_idx().ids()) == 1
        assert list(tmp_path.glob("*.pre-apply*")) == []


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


def _push_principal(principal, session_id):
    p_tok = auth.current_principal.set(principal)
    s_tok = auth.current_session_id.set(session_id)
    return (p_tok, s_tok)


def test_list_drafts_curator_sees_all_creators(tmp_path, monkeypatch):
    """The MCP `list_drafts` tool returns every creator's drafts (unlike
    `list_my_drafts`), each carrying an op_count, for a real writer+."""
    client = _app(tmp_path, monkeypatch)
    with client:
        # Two distinct drafters each queue an op under their own draft.
        for pid, sess in (("d-a", "sess-A"), ("d-b", "sess-B")):
            p = auth.Principal(id=pid, name=pid, role="drafter", type="human")
            tokens = _push_principal(p, sess)
            try:
                server.upsert_entity(name=f"E-{pid}", description="x")
            finally:
                _restore(tokens)

        curator = auth.Principal(id="w1", name="W", role="writer", type="human")
        tokens = _push_principal(curator, "sess-cur")
        try:
            # list_my_drafts is scoped to the curator → nothing of theirs.
            assert server.list_my_drafts() == []
            # list_drafts spans both creators.
            drafts = server.list_drafts()
        finally:
            _restore(tokens)

        assert {d["created_by"] for d in drafts} == {"d-a", "d-b"}
        assert all(d["op_count"] == 1 for d in drafts)
        assert all(d["status"] == "open" for d in drafts)

        # status filter narrows the set (nothing submitted yet).
        tokens = _push_principal(curator, "sess-cur")
        try:
            assert server.list_drafts(status="submitted") == []
        finally:
            _restore(tokens)


def test_list_drafts_denied_for_drafter(tmp_path, monkeypatch):
    """A drafter passes the writer rank via the redirect shortcut for
    normal writes, but must NOT be able to enumerate everyone's drafts."""
    import pytest

    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-deny")
        try:
            with pytest.raises(PermissionError):
                server.list_drafts()
        finally:
            _restore(tokens)


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
        row = (
            server._drafts_db()
            .execute("SELECT session_id FROM drafts WHERE id = ?", (r1["draft_id"],))
            .fetchone()
        )
        assert row["session_id"] == "actor:d2"


def test_another_drafter_cannot_reach_a_draft_by_reusing_its_session_id(
    tmp_path, monkeypatch
):
    """A session id is minted by the transport and travels in a header. It is
    not bound to the principal that obtained it, so presenting someone else's
    must not hand over write access to their draft.

    The auto-draft lookup matches on creator as well as session, so the second
    drafter gets their own draft and the first one's queue is untouched.
    """
    client = _app(tmp_path, monkeypatch)
    with client:
        tokens = _as_drafter("sess-shared")
        try:
            server.upsert_entity(name="Victim Work", description="")
        finally:
            _restore(tokens)

        conn = server._drafts_db()
        victim = drafts_store.find_open_session_draft(conn, "sess-shared", "d1")
        assert victim is not None

        other = auth.Principal(
            id="d2", name="Drafter Two", role="drafter", type="human"
        )
        p_tok = auth.current_principal.set(other)
        s_tok = auth.current_session_id.set("sess-shared")
        try:
            server.upsert_entity(name="Attacker Work", description="")
        finally:
            auth.current_principal.reset(p_tok)
            auth.current_session_id.reset(s_tok)

        attacker = drafts_store.find_open_session_draft(conn, "sess-shared", "d2")
        assert attacker is not None
        assert attacker["id"] != victim["id"]

        victim_ops = drafts_store.list_ops(conn, victim["id"])
        assert len(victim_ops) == 1
        assert "Victim Work" in str(dict(victim_ops[0]))


def test_op_provenance_round_trips_and_defaults_to_none():
    conn = drafts_store.connect(":memory:")
    drafts_store.migrate(conn)
    draft_id = drafts_store.create_draft(conn, created_by="tester", session_id=None)

    drafts_store.add_op(
        conn,
        draft_id=draft_id,
        kind="add_links",
        payload={"links": []},
        provenance={"source": "rule", "score": 0.81},
        created_by="tester",
    )
    drafts_store.add_op(
        conn,
        draft_id=draft_id,
        kind="upsert_entity",
        payload={"name": "ordinary"},
        created_by="tester",
    )

    serialized = [
        drafts_store.serialize_op(row) for row in drafts_store.list_ops(conn, draft_id)
    ]
    assert serialized[0]["provenance"] == {"source": "rule", "score": 0.81}
    assert serialized[1]["provenance"] is None


def test_migrate_adds_provenance_column_to_existing_draft_ops_table():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE draft_ops (
            id           TEXT PRIMARY KEY,
            draft_id     TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            seq          INTEGER NOT NULL,
            kind         TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            created_by   TEXT,
            UNIQUE (draft_id, seq)
        );
        """
    )

    drafts_store.migrate(conn)
    drafts_store.migrate(conn)

    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(draft_ops)").fetchall()
    }
    assert "provenance_json" in columns
    draft_id = drafts_store.create_draft(conn, created_by="tester", session_id=None)
    drafts_store.add_op(
        conn,
        draft_id=draft_id,
        kind="add_links",
        payload={"links": []},
        provenance={"source": "rule"},
        created_by="tester",
    )
    assert drafts_store.serialize_op(drafts_store.list_ops(conn, draft_id)[0])[
        "provenance"
    ] == {"source": "rule"}


def test_resolve_draft_refs_leaves_bare_batch_references_untouched():
    payload = {
        "statements": [{"links": [{"to_id": "@2"}]}],
        "proposal": {"from_id": "@1:0"},
    }
    results = {1: {"results": [{"statement_id": "stm_created"}]}}

    assert server._resolve_draft_refs(payload, results) == {
        "statements": [{"links": [{"to_id": "@2"}]}],
        "proposal": {"from_id": "stm_created"},
    }


_DRAFTS_JSX = Path(__file__).resolve().parents[1] / "src/mycelium/ui/drafts.jsx"


def test_draft_detail_serves_the_fields_the_flag_list_renders(tmp_path, monkeypatch):
    """The drafts UI lists each flag beside the graph from `text`, `reason` and
    `detail` on the op. Nothing else on the draft surface reads those three, so
    this goes through the real writer: renaming one in `assemble_draft` has to
    fail here rather than only in a browser."""
    client = _app(tmp_path, monkeypatch)
    with client:
        flags = extract.extract("The status becomes active").flags
        assert flags, "expected the phrasing catalog to refuse this wording"
        draft_id = assemble_draft(
            server._drafts_db(),
            batch=[BatchInput(kind="event", text="the exporter uploads the report")],
            proposals=[],
            text_of=lambda _id: None,
            created_by="d1",
            flags=flags,
        )

        r = client.get(f"/api/drafts/{draft_id}")
        assert r.status_code == 200, r.text
        flag_ops = [op for op in r.json()["draft"]["ops"] if op["kind"] == "flag"]
        assert len(flag_ops) == 1
        assert flag_ops[0]["payload"]["text"] == "The status becomes active"
        assert flag_ops[0]["payload"]["reason"] == "rejected"
        assert flag_ops[0]["payload"]["detail"]
        assert flag_ops[0]["provenance"]["source"] == "phrasing"


def test_drafts_ui_explains_every_flag_reason_the_pipeline_emits():
    """Every reason the pipeline can emit gets a stage and a sentence in the
    drafts UI. A reason added to FLAG_SOURCES without both falls back to the
    bare enum — the unreadable review surface this list replaced."""
    table = re.search(
        r"const _FLAG_REASONS = \{(.*?)\n\};", _DRAFTS_JSX.read_text(), re.S
    )
    assert table is not None, "could not find _FLAG_REASONS in ui/drafts.jsx"
    explained = {
        reason: re.findall(r"'([^']*)'", value)
        for reason, value in re.findall(r"^  (\w+): \[(.+)\],$", table.group(1), re.M)
    }

    assert extract.FLAG_SOURCES.keys() <= explained.keys()
    for reason in extract.FLAG_SOURCES:
        parts = explained[reason]
        assert len(parts) == 2, f"{reason} needs a stage and an explanation"
        stage, explanation = parts
        assert stage.strip(), f"{reason} names no stage"
        assert explanation.strip().endswith("."), f"{reason} has no explaining sentence"
