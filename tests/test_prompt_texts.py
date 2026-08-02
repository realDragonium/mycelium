"""Editable prompt texts — store semantics + management tools.

Two layers. The store tests drive `prompt_store` against an in-memory DB
and pin the append-only contract: latest-wins reads, ordered history, a
tombstone that hides a name without touching its past versions. The tool
tests go through the `@tool` registry, so they also cover the derived role
gates and the REST mirror the decorator generates.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, prompt_store, server, store


def _conn() -> sqlite3.Connection:
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    return conn


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    prompt_store.reset()
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


def _as(role: str):
    """Run the enclosed tool calls as a principal of `role`."""
    return auth.current_principal.set(
        auth.Principal(id=role[0], name=role, role=role, type="human"),
    )


# --- store ------------------------------------------------------------------


def test_save_round_trip():
    conn = _conn()
    row = prompt_store.save(
        conn, type="doctrine", name="ingest", text="Be precise.", created_by="u1"
    )
    assert row["version"] == 1
    assert row["created_by"] == "u1"
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "Be precise."


def test_latest_wins_after_multiple_saves():
    """Each save appends; reads serve the newest version, and the earlier
    rows are still there untouched."""
    conn = _conn()
    for text in ("v1", "v2", "v3"):
        prompt_store.save(conn, type="doctrine", name="ingest", text=text)

    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "v3"
    assert prompt_store.latest(conn, "doctrine", "ingest")["version"] == 3
    assert [r["text"] for r in prompt_store.history(conn, "doctrine", "ingest")] == [
        "v3",
        "v2",
        "v1",
    ]


def test_history_is_ordered_newest_first():
    conn = _conn()
    for text in ("a", "b", "c"):
        prompt_store.save(conn, type="doctrine", name="ingest", text=text)
    versions = [r["version"] for r in prompt_store.history(conn, "doctrine", "ingest")]
    assert versions == [3, 2, 1]


def test_names_are_independent():
    """Versions count per (type, name) — two names never share a sequence,
    and a same-named text under another type is a different row."""
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="i1")
    prompt_store.save(conn, type="doctrine", name="ingest", text="i2")
    prompt_store.save(conn, type="doctrine", name="research", text="r1")
    prompt_store.save(conn, type="guidelines", name="ingest", text="g1")

    assert prompt_store.latest(conn, "doctrine", "research")["version"] == 1
    assert prompt_store.latest_text(conn, "guidelines", "ingest") == "g1"
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "i2"


def test_delete_hides_the_name_and_keeps_history():
    """The tombstone stops the name being served and listed; every earlier
    version stays readable, and the name can be saved again afterwards."""
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="v1")
    prompt_store.save(conn, type="doctrine", name="ingest", text="v2")

    assert prompt_store.delete(conn, type="doctrine", name="ingest") is True
    assert prompt_store.latest(conn, "doctrine", "ingest") is None
    assert prompt_store.list_current(conn) == []

    hist = prompt_store.history(conn, "doctrine", "ingest")
    assert [r["version"] for r in hist] == [3, 2, 1]
    assert bool(hist[0]["deleted"]) is True
    assert [r["text"] for r in hist[1:]] == ["v2", "v1"]

    revived = prompt_store.save(conn, type="doctrine", name="ingest", text="v3")
    assert revived["version"] == 4
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "v3"


def test_delete_unknown_name_is_false():
    conn = _conn()
    assert prompt_store.delete(conn, type="doctrine", name="nope") is False


def test_list_current_filters_by_type():
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="i")
    prompt_store.save(conn, type="doctrine", name="research", text="r")
    prompt_store.save(conn, type="guidelines", name="tutorial", text="t")
    prompt_store.save(conn, type="doctrine", name="ingest", text="i2")

    everything = [(r["type"], r["name"]) for r in prompt_store.list_current(conn)]
    assert everything == [
        ("doctrine", "ingest"),
        ("doctrine", "research"),
        ("guidelines", "tutorial"),
    ]

    doctrines = prompt_store.list_current(conn, "doctrine")
    assert [r["name"] for r in doctrines] == ["ingest", "research"]
    assert [r["version"] for r in doctrines] == [2, 1]
    assert prompt_store.list_current(conn, "unknown-type") == []


def test_save_if_absent_never_overwrites():
    """The seeding path: it fills an empty name, leaves an edited one alone,
    and seeds again once the name has been retired."""
    conn = _conn()
    seeded = prompt_store.save_if_absent(
        conn, type="doctrine", name="ingest", text="packaged"
    )
    assert seeded["version"] == 1

    prompt_store.save(conn, type="doctrine", name="ingest", text="operator edit")
    assert (
        prompt_store.save_if_absent(
            conn, type="doctrine", name="ingest", text="packaged"
        )
        is None
    )
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "operator edit"

    prompt_store.delete(conn, type="doctrine", name="ingest")
    assert prompt_store.save_if_absent(
        conn, type="doctrine", name="ingest", text="packaged"
    )
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "packaged"


def test_blank_key_or_text_rejected():
    conn = _conn()
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="  ", name="ingest", text="x")
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="doctrine", name="", text="x")
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="doctrine", name="ingest", text="   ")


# --- tools ------------------------------------------------------------------


def test_tool_round_trip(tmp_path, monkeypatch):
    """save → get → list through the registry, and a second save is visible
    to the next read with no restart in between."""
    client = _app(tmp_path, monkeypatch)
    with client:
        saved = server.save_prompt_text("doctrine", "ingest", "Be precise.")
        assert saved["version"] == 1 and saved["deleted"] is False

        assert server.get_prompt_text("doctrine", "ingest")["text"] == "Be precise."

        server.save_prompt_text("doctrine", "ingest", "Be very precise.")
        assert (
            server.get_prompt_text("doctrine", "ingest")["text"] == "Be very precise."
        )

        listed = server.list_prompt_texts()["prompt_texts"]
        assert listed == [
            {
                "type": "doctrine",
                "name": "ingest",
                "version": 2,
                "chars": len("Be very precise."),
                "created_at": listed[0]["created_at"],
                "created_by": None,
            }
        ]

        versions = server.list_prompt_text_versions("doctrine", "ingest")["versions"]
        assert [v["text"] for v in versions] == ["Be very precise.", "Be precise."]


def test_tool_list_by_type(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        server.save_prompt_text("doctrine", "ingest", "i")
        server.save_prompt_text("guidelines", "tutorial", "t")

        names = [
            p["name"] for p in server.list_prompt_texts(type="doctrine")["prompt_texts"]
        ]
        assert names == ["ingest"]


def test_tool_retire(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        server.save_prompt_text("doctrine", "ingest", "v1")
        assert server.retire_prompt_text("doctrine", "ingest") == {"retired": True}
        assert server.retire_prompt_text("doctrine", "ingest") == {"retired": False}

        assert server.list_prompt_texts()["prompt_texts"] == []
        with pytest.raises(ValueError):
            server.get_prompt_text("doctrine", "ingest")

        # History survives the tombstone.
        versions = server.list_prompt_text_versions("doctrine", "ingest")["versions"]
        assert [v["deleted"] for v in versions] == [True, False]


def test_unknown_name_raises(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        with pytest.raises(ValueError):
            server.get_prompt_text("doctrine", "nope")
        assert server.list_prompt_text_versions("doctrine", "nope") == {"versions": []}


def test_save_records_the_caller(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        token = _as("writer")
        try:
            saved = server.save_prompt_text("doctrine", "ingest", "v1")
        finally:
            auth.current_principal.reset(token)
        assert saved["created_by"] == "w"


def test_role_gates(tmp_path, monkeypatch):
    """Names carry the gate: `save_`/`get_`/`list_` derive writer/reader,
    and `retire_` is explicitly admin — nothing here is draftable."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        token = _as("reader")
        try:
            with pytest.raises(PermissionError):
                server.save_prompt_text("doctrine", "ingest", "v1")
            assert server.list_prompt_texts()["prompt_texts"] == []
        finally:
            auth.current_principal.reset(token)

        token = _as("writer")
        try:
            server.save_prompt_text("doctrine", "ingest", "v1")
            with pytest.raises(PermissionError):
                server.retire_prompt_text("doctrine", "ingest")
        finally:
            auth.current_principal.reset(token)

        token = _as("admin")
        try:
            assert server.retire_prompt_text("doctrine", "ingest") == {"retired": True}
        finally:
            auth.current_principal.reset(token)


def test_drafter_cannot_edit_prompt_texts(tmp_path, monkeypatch):
    """A drafter clears writer/admin gates only because their substrate
    writes get redirected onto a draft. These tools are outside that
    machinery, so the write path rejects them and queues nothing; reads
    still work."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        server.save_prompt_text("doctrine", "ingest", "v1")

        token = _as("drafter")
        try:
            with pytest.raises(PermissionError):
                server.save_prompt_text("doctrine", "ingest", "hijacked")
            with pytest.raises(PermissionError):
                server.retire_prompt_text("doctrine", "ingest")
            assert server.get_prompt_text("doctrine", "ingest")["text"] == "v1"
            assert server.list_my_drafts() == []
        finally:
            auth.current_principal.reset(token)


def test_rest_mirror(tmp_path, monkeypatch):
    """The @tool decorator generates the REST routes; no custom HTTP code."""
    client = _app(tmp_path, monkeypatch)
    with client:
        r = client.post(
            "/save-prompt-text",
            json={"type": "doctrine", "name": "ingest", "text": "v1"},
        )
        assert r.status_code == 200 and r.json()["version"] == 1

        r = client.post("/get-prompt-text", json={"type": "doctrine", "name": "ingest"})
        assert r.json()["text"] == "v1"

        r = client.post("/list-prompt-texts", json={})
        assert [p["name"] for p in r.json()["prompt_texts"]] == ["ingest"]


def test_rest_rejects_drafter_with_403(tmp_path, monkeypatch):
    """The real-role check runs inside the tool, past the route's own gate —
    it still has to read as a role rejection, not a server fault."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = server._auth_db()
        uid = auth.create_user(
            conn, name="D", role="drafter", type="human", email="d@x.com"
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="drafter")
        conn.commit()
        h = {"Authorization": f"Bearer {raw}"}

        r = client.post(
            "/save-prompt-text",
            json={"type": "doctrine", "name": "ingest", "text": "v1"},
            headers=h,
        )
        assert r.status_code == 403
        assert "writer" in r.json()["detail"]

        r = client.post(
            "/retire-prompt-text",
            json={"type": "doctrine", "name": "ingest"},
            headers=h,
        )
        assert r.status_code == 403
