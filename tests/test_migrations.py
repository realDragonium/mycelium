"""Schema migration runner tests.

Covers: fresh DB fast-forwards to current; legacy DB (pre-versioning,
missing audit columns) runs v1; idempotency on re-run; rejection of
a future-version DB (downgrade safety).
"""

from __future__ import annotations

import sqlite3

import pytest

from mycelium import migrations, store


def _user_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _has_column(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def test_fresh_db_fast_forwards_to_current():
    conn = store.connect(":memory:")
    store.migrate(conn)
    assert _user_version(conn) == migrations.CURRENT_VERSION
    # And every audit column is present (came in via SCHEMA, not v1).
    assert _has_column(conn, "entities", "created_at")
    assert _has_column(conn, "statements", "updated_by")


def test_legacy_db_runs_v1():
    """Simulate the pre-audit shape: tables without the audit columns
    and no `user_version` set. The runner detects this and applies v1."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create a minimal subset of the pre-audit schema. The runner only
    # needs tables that v1's `_ensure_column` will probe; a full legacy
    # schema isn't necessary for this test.
    conn.execute("CREATE TABLE entities (id TEXT PRIMARY KEY, description TEXT)")
    conn.execute(
        "CREATE TABLE statements (id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE names ("
        "id TEXT PRIMARY KEY, text TEXT NOT NULL UNIQUE, "
        "entity_id TEXT NOT NULL REFERENCES entities(id))"
    )
    # The annotation tables below mirror the real pre-audit shape: legacy
    # DBs carry them (the subsystem has since been removed from live code),
    # and the byte-frozen v1 migration probes them via _ensure_column, so
    # the fixture must keep them for v1 to run.
    conn.execute(
        "CREATE TABLE annotations (id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE statement_links (link_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "from_statement_id TEXT NOT NULL REFERENCES statements(id), "
        "to_statement_id TEXT NOT NULL REFERENCES statements(id), "
        "link_type TEXT NOT NULL, when_hash TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE entity_links ("
        "from_entity_id TEXT NOT NULL REFERENCES entities(id), "
        "to_entity_id TEXT NOT NULL REFERENCES entities(id), "
        "link_type TEXT NOT NULL, "
        "PRIMARY KEY (from_entity_id, to_entity_id, link_type))"
    )
    conn.execute(
        "CREATE TABLE statement_annotations ("
        "statement_id TEXT NOT NULL REFERENCES statements(id), "
        "annotation_id TEXT NOT NULL REFERENCES annotations(id), "
        "PRIMARY KEY (statement_id, annotation_id))"
    )
    conn.execute(
        "CREATE TABLE entity_annotations ("
        "entity_id TEXT NOT NULL REFERENCES entities(id), "
        "annotation_id TEXT NOT NULL REFERENCES annotations(id), "
        "PRIMARY KEY (entity_id, annotation_id))"
    )
    # Insert a legacy row to verify it survives the migration.
    conn.execute(
        "INSERT INTO entities (id, description) VALUES ('ent_legacy', 'legacy')"
    )
    conn.commit()

    assert _user_version(conn) == 0
    assert not _has_column(conn, "entities", "created_at")

    migrations.apply_migrations(conn)

    assert _user_version(conn) == migrations.CURRENT_VERSION
    assert _has_column(conn, "entities", "created_at")
    assert _has_column(conn, "statements", "updated_by")
    assert _has_column(conn, "statement_links", "created_by")
    # Legacy row survives with NULL audit columns — the honest answer.
    row = conn.execute(
        "SELECT description, created_at FROM entities WHERE id = 'ent_legacy'"
    ).fetchone()
    assert row["description"] == "legacy"
    assert row["created_at"] is None


def test_re_running_is_a_no_op():
    """Migrations are idempotent: applying twice doesn't break anything."""
    conn = store.connect(":memory:")
    store.migrate(conn)
    before = _user_version(conn)
    store.migrate(conn)
    assert _user_version(conn) == before


def test_future_version_db_is_rejected():
    """A DB at a version newer than this build raises rather than
    silently running against an unknown-future schema."""
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute(f"PRAGMA user_version = {migrations.CURRENT_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer than this build"):
        migrations.apply_migrations(conn)


def test_v2_widens_when_nodes_check_constraint():
    """A v1-shape DB (when_nodes CHECK restricted to 'and'/'or') gets
    upgraded so 'not' becomes a legal op."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Minimal v1-era schema for the tables v2 touches.
    conn.execute(
        "CREATE TABLE statements (id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE statement_links (link_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "from_statement_id TEXT NOT NULL REFERENCES statements(id), "
        "to_statement_id TEXT NOT NULL REFERENCES statements(id), "
        "link_type TEXT NOT NULL, when_hash TEXT NOT NULL)"
    )
    # The pre-v2 when_nodes shape: CHECK restricted to 'and'/'or'.
    conn.execute("""
        CREATE TABLE when_nodes (
            node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id     INTEGER NOT NULL REFERENCES statement_links(link_id) ON DELETE CASCADE,
            parent_id   INTEGER REFERENCES when_nodes(node_id) ON DELETE CASCADE,
            op          TEXT,
            statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
            child_index INTEGER NOT NULL,
            CHECK ((op IS NULL) <> (statement_id IS NULL)),
            CHECK (op IS NULL OR op IN ('and', 'or'))
        )
    """)
    # Insert a row using the old vocabulary to confirm it survives the rebuild.
    conn.execute(
        "INSERT INTO statements (id, kind, text) VALUES ('stm_x', 'state', 'X')"
    )
    conn.execute(
        "INSERT INTO statement_links (from_statement_id, to_statement_id, link_type, when_hash) "
        "VALUES ('stm_x', 'stm_x', 'triggers', 'NONE')"
    )
    link_id = conn.execute("SELECT link_id FROM statement_links").fetchone()["link_id"]
    conn.execute(
        "INSERT INTO when_nodes (link_id, parent_id, op, statement_id, child_index) "
        "VALUES (?, NULL, 'and', NULL, 0)",
        (link_id,),
    )
    conn.commit()
    conn.execute("PRAGMA user_version = 1")

    # 'not' rejected before the migration.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO when_nodes (link_id, parent_id, op, statement_id, child_index) "
            "VALUES (?, NULL, 'not', NULL, 0)",
            (link_id,),
        )
    conn.rollback()

    migrations.apply_migrations(conn)

    assert _user_version(conn) == migrations.CURRENT_VERSION
    # Existing row survived.
    assert conn.execute("SELECT COUNT(*) FROM when_nodes").fetchone()[0] == 1
    # 'not' now accepted.
    conn.execute(
        "INSERT INTO when_nodes (link_id, parent_id, op, statement_id, child_index) "
        "VALUES (?, NULL, 'not', NULL, 1)",
        (link_id,),
    )
    # An unknown op still rejected.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO when_nodes (link_id, parent_id, op, statement_id, child_index) "
            "VALUES (?, NULL, 'xor', NULL, 2)",
            (link_id,),
        )
    conn.rollback()


def test_backup_schema_version_matches_runner():
    """The backup format's SCHEMA_VERSION must track the migration
    runner's CURRENT_VERSION — they describe the same notion."""
    from mycelium import backup

    assert backup.SCHEMA_VERSION == migrations.CURRENT_VERSION


def test_v5_upgrade_enqueues_existing_statements_for_rederive():
    """A legacy DB whose statements carry hand-asserted mentions must, after
    the v5 upgrade, have every statement enqueued for the worker to re-derive
    — so stale author-asserted rows don't silently survive."""
    from mycelium import mention_worker

    conn = store.connect(":memory:")
    store.migrate(conn)  # fresh → v5
    # Simulate a pre-v5 corpus: an entity "result" (6 chars → suspect under the
    # new rules) and a statement hand-asserted to mention it.
    eid = store.create_entity(conn, None)
    nid = store.create_name(conn, "result", eid)
    sid = store.create_statement(conn, "state", "the result is cached")
    conn.execute(
        "INSERT INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        (sid, nid),
    )
    # Pretend this DB predates v5 so the migration's backfill branch runs.
    conn.execute("DELETE FROM mention_recompute_queue")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()

    migrations.apply_migrations(conn)

    # Every statement was enqueued for recompute.
    assert store.count_open_recompute(conn) == 1
    # Draining re-derives: "result" is suspect, so the stale auto-link is
    # removed and the occurrence is queued for review instead.
    mention_worker.drain(conn)
    assert store.get_mentions(conn, sid) == []
    assert [p["name"] for p in store.list_pending_mentions(conn)] == ["result"]
