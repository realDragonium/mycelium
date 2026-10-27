"""The web app's "Propose as draft" marker: a real writer or admin sending it
acts as a drafter for that request, so their writes stage on their own draft."""

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, drafts_store, store
from mycelium.server import runtime

MARKER = {auth.PROPOSE_HEADER: "draft"}


@pytest.mark.parametrize(
    ("role", "marker", "acts_as"),
    [
        ("writer", "draft", "drafter"),
        ("admin", "draft", "drafter"),
        ("writer", None, "writer"),
        ("admin", "live", "admin"),
        ("reader", "draft", "reader"),
        ("drafter", "draft", "drafter"),
    ],
)
def test_the_marker_only_narrows_a_real_writer_or_admin(role, marker, acts_as):
    principal = auth.Principal(id="u1", name="U", role=role, type="human")
    assert auth.proposing(principal, marker).role == acts_as
    assert auth.proposing(principal, marker).id == "u1"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    from mycelium import embed

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


def _add_statement(client: TestClient, headers: dict[str, str], text: str):
    return client.post(
        "/upsert-statement",
        headers=headers,
        json={
            "kind": "state",
            "text": text,
            "links": [],
            "allow_phrasing_violations": True,
        },
    )


def _edit(client: TestClient, headers: dict[str, str], statement_id: str, text: str):
    return client.post(
        "/replace-text",
        headers=headers,
        json={"id": statement_id, "text": text, "allow_phrasing_violations": True},
    )


def _live_texts() -> list[str]:
    rows = store.substrate_connection().execute(
        "SELECT text FROM statements ORDER BY text"
    )
    return [row["text"] for row in rows]


def test_a_writer_proposing_stages_on_their_draft_and_writes_live_without(client):
    writer = _bearer("writer")
    statement_id = _add_statement(client, writer, "An invoice has a due date.").json()[
        "statement_id"
    ]

    edited = _edit(client, writer | MARKER, statement_id, "An invoice has a due day.")
    added = _add_statement(client, writer | MARKER, "An export runs nightly.")

    assert edited.json()["queued"] == "replace_text"
    assert added.json()["draft_id"] == edited.json()["draft_id"]
    assert _live_texts() == ["An invoice has a due date."]
    mine = client.get("/api/me/draft", headers=writer).json()["draft"]
    assert mine == {"id": edited.json()["draft_id"], "op_count": 2}

    assert _edit(client, writer, statement_id, "An invoice has a due day.").is_success
    assert _live_texts() == ["An invoice has a due day."]
    assert client.get("/api/me/draft", headers=writer).json()["draft"]["op_count"] == 2


def test_a_writer_proposing_cannot_decide_drafts(client):
    """Curation lands live, so it is a drafter's no while proposing."""
    writer = _bearer("writer")
    draft_id = _add_statement(
        client, writer | MARKER, "A workspace has members."
    ).json()["draft_id"]

    approved = client.post(f"/api/drafts/{draft_id}/approve", headers=writer | MARKER)

    assert approved.status_code == 403
    assert _live_texts() == []


def test_a_reader_gains_nothing_from_the_marker(client):
    reader = _bearer("reader")

    assert (
        _add_statement(client, reader | MARKER, "SSO signs a user in.").status_code
        == 403
    )
    assert client.get("/api/me/draft", headers=reader).json() == {"draft": None}
