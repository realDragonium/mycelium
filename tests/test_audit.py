"""Audit-column tests: every write stamps created_at; mutating writes bump
updated_at; the module-level actor flows into created_by / updated_by; the
ALTER-TABLE migration is idempotent against legacy DBs without the columns.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from mycelium import store


@pytest.fixture(autouse=True)
def _reset_actor():
    """Each test starts with no actor; clear after to avoid leaks."""
    store.set_actor(None)
    yield
    store.set_actor(None)


def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def _iso_ish(s: str | None) -> bool:
    """Loose check: ISO-8601-ish UTC string with trailing Z."""
    return isinstance(s, str) and len(s) >= 20 and s.endswith("Z") and s[10] == "T"


def test_entity_stamps_created_at_and_actor():
    conn = fresh_conn()
    store.set_actor("alice")
    eid = store.create_entity(conn, "User auth")
    row = store.get_entity_by_id(conn, eid)
    assert _iso_ish(row["created_at"])
    assert row["created_by"] == "alice"
    assert row["updated_at"] is None
    assert row["updated_by"] is None


def test_entity_update_bumps_updated_columns():
    conn = fresh_conn()
    store.set_actor("alice")
    eid = store.create_entity(conn, "old")
    created_at = store.get_entity_by_id(conn, eid)["created_at"]

    # Sleep just long enough that the next millisecond-precision stamp differs.
    time.sleep(0.002)
    store.set_actor("bob")
    store.update_entity_description(conn, eid, "new")
    row = store.get_entity_by_id(conn, eid)
    assert row["created_at"] == created_at  # unchanged
    assert row["created_by"] == "alice"  # unchanged
    assert _iso_ish(row["updated_at"])
    assert row["updated_at"] > created_at
    assert row["updated_by"] == "bob"


def test_actor_absent_means_null_actor_columns():
    conn = fresh_conn()
    # No set_actor call: actor stays None.
    eid = store.create_entity(conn, None)
    row = store.get_entity_by_id(conn, eid)
    assert _iso_ish(row["created_at"])
    assert row["created_by"] is None


def test_statement_audit_lifecycle():
    conn = fresh_conn()
    store.set_actor("alice")
    bid = store.create_statement(conn, "event", "user logs in")
    row = store.get_statement(conn, bid)
    assert _iso_ish(row["created_at"])
    assert row["created_by"] == "alice"
    assert row["updated_at"] is None

    time.sleep(0.002)
    store.set_actor("bob")
    store.update_statement_text(conn, bid, "user authenticates")
    row = store.get_statement(conn, bid)
    assert row["created_by"] == "alice"
    assert row["updated_by"] == "bob"
    assert row["updated_at"] > row["created_at"]


def test_name_rename_bumps_updated():
    conn = fresh_conn()
    store.set_actor("alice")
    eid = store.create_entity(conn, None)
    nid = store.create_name(conn, "Login", eid)

    time.sleep(0.002)
    store.set_actor("bob")
    store.rename_name(conn, nid, "Sign-in")
    row = store.get_name_by_id(conn, nid)
    assert row["created_by"] == "alice"
    assert row["updated_by"] == "bob"
    assert row["updated_at"] > row["created_at"]


def test_annotation_audit_lifecycle():
    conn = fresh_conn()
    store.set_actor("alice")
    aid = store.create_annotation(conn, "note", "draft")
    row = store.get_annotation(conn, aid)
    assert row["created_by"] == "alice"

    time.sleep(0.002)
    store.set_actor("bob")
    store.update_annotation(conn, aid, "note", "revised")
    row = store.get_annotation(conn, aid)
    assert row["created_by"] == "alice"
    assert row["updated_by"] == "bob"


def test_statement_link_stamps_creation():
    conn = fresh_conn()
    store.set_actor("alice")
    b1 = store.create_statement(conn, "event", "A")
    b2 = store.create_statement(conn, "event", "B")
    store.insert_links(conn, [(b1, b2, "triggers", None)])

    row = conn.execute(
        "SELECT created_at, created_by FROM statement_links "
        "WHERE from_statement_id = ? AND to_statement_id = ?",
        (b1, b2),
    ).fetchone()
    assert _iso_ish(row["created_at"])
    assert row["created_by"] == "alice"


def test_entity_link_stamps_creation():
    conn = fresh_conn()
    store.set_actor("alice")
    e1 = store.create_entity(conn, None)
    e2 = store.create_entity(conn, None)
    store.insert_entity_links(conn, [(e1, e2, "contains")])

    row = conn.execute(
        "SELECT created_at, created_by FROM entity_links "
        "WHERE from_entity_id = ? AND to_entity_id = ?",
        (e1, e2),
    ).fetchone()
    assert _iso_ish(row["created_at"])
    assert row["created_by"] == "alice"


def test_annotation_attachment_stamps_creation():
    conn = fresh_conn()
    store.set_actor("alice")
    bid = store.create_statement(conn, "event", "A")
    aid = store.create_annotation(conn, "note", "x")
    store.attach_annotations_to_statements(conn, [(bid, aid)])

    row = conn.execute(
        "SELECT created_at, created_by FROM statement_annotations "
        "WHERE statement_id = ? AND annotation_id = ?",
        (bid, aid),
    ).fetchone()
    assert _iso_ish(row["created_at"])
    assert row["created_by"] == "alice"


def test_migration_adds_columns_to_legacy_db():
    """Simulate a pre-audit DB by creating bare tables, then re-migrate.
    All audit columns must appear, idempotently."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Old-shape entities table — no audit columns.
    conn.execute("CREATE TABLE entities (id TEXT PRIMARY KEY, description TEXT)")
    conn.execute(
        "INSERT INTO entities (id, description) VALUES ('ent_legacy', 'old row')"
    )
    conn.commit()

    # Migrate. New columns should appear; the legacy row's audit fields stay NULL.
    store.migrate(conn)
    row = conn.execute(
        "SELECT id, description, created_at, updated_at, created_by, updated_by "
        "FROM entities WHERE id = 'ent_legacy'"
    ).fetchone()
    assert row["description"] == "old row"
    assert row["created_at"] is None
    assert row["updated_at"] is None
    assert row["created_by"] is None

    # Idempotent — second migrate is a no-op.
    store.migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
    assert {"created_at", "updated_at", "created_by", "updated_by"} <= cols
