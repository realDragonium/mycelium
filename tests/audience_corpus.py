"""A running app with auth on and a corpus whose statements carry different
audiences: one labelled for external readers and one left internal, whose
text holds `SECRET`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, store
from mycelium.server import runtime

SECRET = "internal queue codenamed ZZQUILL"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    store.reset_substrate()
    auth_store.reset()
    runtime._ctx = None
    from mycelium import embed

    # One vector for every text: unscoped search would rank every statement.
    monkeypatch.setattr(embed, "embed", lambda text: [1.0] + [0.0] * 767)
    from mycelium.http import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _bearer(role: str) -> dict[str, str]:
    conn = runtime._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(conn, user_id=user, name="t", scope=role)
    return {"Authorization": f"Bearer {raw}"}


def _corpus(client: TestClient, admin: dict[str, str]) -> tuple[str, str, str]:
    def statement(text: str, links: list[dict[str, str]]) -> str:
        r = client.post(
            "/upsert-statement",
            headers=admin,
            json={
                "kind": "state",
                "text": text,
                "links": links,
                "allow_phrasing_violations": True,
            },
        )
        assert r.status_code == 200, r.text
        return str(r.json()["statement_id"])

    r = client.post(
        "/upsert-entity",
        headers=admin,
        json={"name": "workspace export", "description": f"Runs on the {SECRET}."},
    )
    entity = str(r.json()["entity_id"])
    hidden = statement(f"A workspace export runs on the {SECRET}.", [])
    public = statement(
        "A workspace export downloads as a CSV file.",
        [{"to_id": hidden, "link_type": "requires"}],
    )
    r = client.put(
        f"/api/statements/{public}/audiences",
        headers=admin,
        json={"audiences": ["external-technical"], "reason": "public"},
    )
    assert r.status_code == 200, r.text
    return public, hidden, entity
