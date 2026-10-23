"""Vocabulary tools edit glossary entries without deleting their uses."""

import pytest

from mycelium import server, store


@pytest.fixture
def db():
    conn = store.connect(":memory:")
    store.migrate(conn)
    store.use_substrate_connection(conn)
    try:
        yield conn
    finally:
        store.reset_substrate()
        conn.close()


def test_upsert_statement_kind_creates_and_updates(db):
    assert server.upsert_statement_kind(
        "workspace-note", "Workspace behavior.", "For workspace details."
    ) == {"kind": "workspace-note"}
    assert dict(store.get_statement_kind_glossary(db, "workspace-note")) == {
        "kind": "workspace-note",
        "description": "Workspace behavior.",
        "when_to_use": "For workspace details.",
    }
    server.upsert_statement_kind("workspace-note", "Updated workspace behavior.")
    assert dict(store.get_statement_kind_glossary(db, "workspace-note")) == {
        "kind": "workspace-note",
        "description": "Updated workspace behavior.",
        "when_to_use": None,
    }
    with pytest.raises(ValueError, match="kind cannot be empty"):
        server.upsert_statement_kind(" ", "Workspace behavior.")
    with pytest.raises(ValueError, match="description cannot be empty"):
        server.upsert_statement_kind("workspace-note", " ")


def test_delete_statement_kind_keeps_statements_and_is_idempotent(db):
    server.upsert_statement_kind("workspace-note", "Workspace behavior.")
    sid = store.create_statement(db, "workspace-note", "Workspaces support SSO.")
    assert server.delete_statement_kind("workspace-note") == {"kind": "workspace-note"}
    assert store.get_statement_kind_glossary(db, "workspace-note") is None
    assert store.get_statement(db, sid)["kind"] == "workspace-note"
    assert server.delete_statement_kind("workspace-note") == {"kind": "workspace-note"}


def test_delete_link_type_keeps_links_and_is_idempotent(db):
    server.upsert_link_type("exports-to", "An export produces an invoice.")
    source = store.create_statement(db, "state", "Exports are enabled.")
    target = store.create_statement(db, "state", "Invoices are available.")
    store.insert_links(db, [(source, target, "exports-to", None)])
    assert server.delete_link_type("exports-to") == {"link_type": "exports-to"}
    assert store.get_statement_link_type_glossary(db, "exports-to") is None
    assert store.count_statement_links_by_type(db) == {"exports-to": 1}
    assert server.delete_link_type("exports-to") == {"link_type": "exports-to"}


def test_delete_entity_link_type_keeps_links_and_is_idempotent(db):
    server.upsert_entity_link_type("exports-to", "Workspace invoice exports.")
    source = store.create_entity(db, "Workspace")
    target = store.create_entity(db, "Invoices")
    store.insert_entity_links(db, [(source, target, "exports-to")])
    assert server.delete_entity_link_type("exports-to") == {"link_type": "exports-to"}
    assert store.get_entity_link_type_glossary(db, "exports-to") is None
    assert store.count_entity_links_by_type(db) == {"exports-to": 1}
    assert server.delete_entity_link_type("exports-to") == {"link_type": "exports-to"}
