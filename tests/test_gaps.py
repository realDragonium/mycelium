"""Knowledge-gap reporting + management tests.

Covers the round-trip: agent files via report_knowledge_gap → row
exists → HTTP list returns it → PATCH resolves it → row reflects
the terminal state. Also confirms a reader can call the report tool
(per the role= override on @tool).
"""

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


def _app(tmp_path, monkeypatch, *, auth_mode: str = "off"):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", auth_mode)
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    _reset_server()
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


def test_report_knowledge_gap_creates_open_row(tmp_path, monkeypatch):
    """The tool inserts a row that's neither resolved nor dismissed,
    so it shows up as 'open' in the HTTP list."""
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        result = server.report_knowledge_gap("Missing coverage for invoicing flow.")
        assert "gap_id" in result

        r = client.get("/api/knowledge-gaps?status=open")
        gaps = r.json()["gaps"]
        assert len(gaps) == 1
        assert gaps[0]["status"] == "open"
        assert gaps[0]["text"] == "Missing coverage for invoicing flow."


def test_reader_can_report_gap_over_mcp(tmp_path, monkeypatch):
    """Per the role= override on @tool, a reader's principal still
    passes the call-time gate for report_knowledge_gap. Test by
    setting the contextvar directly — same path the streamable-HTTP
    transport uses."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        token = auth.current_principal.set(
            auth.Principal(id="r", name="Reader", role="reader", type="human"),
        )
        try:
            result = server.report_knowledge_gap("Reader-filed gap.")
            assert "gap_id" in result
        finally:
            auth.current_principal.reset(token)


def test_resolve_and_dismiss(tmp_path, monkeypatch):
    """PATCH transitions update the right terminal column, and the
    derived `status` flips accordingly."""
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        a = server.report_knowledge_gap("To resolve")
        b = server.report_knowledge_gap("To dismiss")

        r = client.patch(
            f"/api/knowledge-gaps/{a['gap_id']}", json={"action": "resolve"}
        )
        assert r.status_code == 200
        assert r.json()["gap"]["status"] == "resolved"
        assert r.json()["gap"]["resolved_at"]

        r = client.patch(
            f"/api/knowledge-gaps/{b['gap_id']}", json={"action": "dismiss"}
        )
        assert r.status_code == 200
        assert r.json()["gap"]["status"] == "dismissed"
        assert r.json()["gap"]["dismissed_at"]

        # Open filter drops both.
        open_gaps = client.get("/api/knowledge-gaps?status=open").json()["gaps"]
        assert open_gaps == []

        # Specific filters return only the matching row.
        resolved = client.get("/api/knowledge-gaps?status=resolved").json()["gaps"]
        assert len(resolved) == 1 and resolved[0]["text"] == "To resolve"


def test_reopen_clears_terminal_timestamps(tmp_path, monkeypatch):
    """Reopen is the round-trip path — moves a row back to 'open' and
    clears whichever terminal columns were set."""
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        a = server.report_knowledge_gap("To bounce")
        client.patch(f"/api/knowledge-gaps/{a['gap_id']}", json={"action": "resolve"})
        r = client.patch(
            f"/api/knowledge-gaps/{a['gap_id']}", json={"action": "reopen"}
        )
        body = r.json()["gap"]
        assert body["status"] == "open"
        assert body["resolved_at"] is None
        assert body["dismissed_at"] is None


def test_invalid_action_rejected(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        a = server.report_knowledge_gap("X")
        r = client.patch(
            f"/api/knowledge-gaps/{a['gap_id']}", json={"action": "destroy"}
        )
        assert r.status_code == 400


def test_unknown_gap_returns_404(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        r = client.patch(
            "/api/knowledge-gaps/does-not-exist", json={"action": "resolve"}
        )
        assert r.status_code == 404


def test_empty_text_rejected(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, auth_mode="off")
    with client:
        import pytest

        with pytest.raises(ValueError):
            server.report_knowledge_gap("   ")
