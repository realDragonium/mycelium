"""`open_draft`: a writer or admin proposes over MCP through a draft they open,
instead of needing a drafter-scoped token."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, drafts_store, server, store
from mycelium.server import runtime


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda text: [1.0] + [0.0] * 767)
    from mycelium.http import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@contextmanager
def _as(user_id: str, role: auth.Role) -> Iterator[None]:
    principal = auth.Principal(id=user_id, name=user_id, role=role, type="human")
    token = auth.current_principal.set(principal)
    try:
        yield
    finally:
        auth.current_principal.reset(token)


def _live_statement(text: str) -> str:
    result = server.upsert_statement(
        kind="state", text=text, links=[], allow_phrasing_violations=True
    )
    statement_id: str = result["statement_id"]
    return statement_id


def _live_text(statement_id: str) -> str:
    row = (
        store.substrate_connection()
        .execute("SELECT text FROM statements WHERE id = ?", (statement_id,))
        .fetchone()
    )
    return str(row["text"])


def test_a_writer_stages_edits_on_the_draft_they_open_and_submits_it(client):
    statement = _live_statement("An invoice export link is valid for 24 hours.")

    with _as("usr_writer", "writer"):
        opened = server.open_draft(title="Export links")
        draft_id = opened["draft_id"]
        receipt = server.patch_statement(
            id=statement,
            text="An invoice export link is valid for 72 hours.",
            allow_phrasing_violations=True,
            draft_id=draft_id,
        )
        again = server.open_draft()
        submitted = server.submit_draft(draft_id=draft_id)
        mine = server.list_my_drafts()

    assert opened["created"] and opened["title"] == "Export links"
    assert receipt["draft_id"] == draft_id
    assert _live_text(statement) == "An invoice export link is valid for 24 hours."
    assert (again["draft_id"], again["created"], again["op_count"]) == (
        draft_id,
        False,
        1,
    )
    assert submitted == {"draft_id": draft_id, "op_count": 1}
    assert [(d["id"], d["status"]) for d in mine] == [(draft_id, "submitted")]


def test_a_reader_cannot_open_a_draft(client):
    with _as("usr_reader", "reader"), pytest.raises(auth.RoleRequired):
        server.open_draft()


def test_each_caller_opens_their_own_draft_and_cannot_stage_on_anothers(client):
    with _as("usr_writer", "writer"):
        theirs = server.open_draft()["draft_id"]
    with _as("usr_other", "writer"):
        own = server.open_draft()["draft_id"]
    with _as("usr_drafter", "drafter"), pytest.raises(auth.RoleRequired):
        server.upsert_entity(name="Workspace", description="", draft_id=theirs)

    assert own != theirs
    assert drafts_store.list_ops(server._drafts_db(), theirs) == []
