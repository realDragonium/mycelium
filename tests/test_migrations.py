"""Schema migration runner tests.

Covers: fresh DB fast-forwards to current; legacy DB (pre-versioning,
missing audit columns) runs v1; idempotency on re-run; rejection of
a future-version DB (downgrade safety).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mycelium import migrations, store
from mycelium.store import glossary


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


def test_connection_indexes_upgrade_existing_stores_without_changing_edges():
    conn = store.connect(":memory:")
    store.migrate(conn)
    indexes = {
        "statement_links_from_id",
        "statement_links_to_id",
        "when_nodes_statement_link",
    }
    for name in indexes:
        conn.execute(f"DROP INDEX {name}")
    a = store.create_statement(conn, "action", "Click Save.")
    b = store.create_statement(conn, "event", "The changes are saved.")
    store.insert_links(conn, [(a, b, "performs", None)])
    conn.execute("PRAGMA user_version = 11")
    conn.commit()

    migrations.apply_migrations(conn)

    installed = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert indexes <= installed
    assert store.get_links(conn, a) == [(b, "performs", None)]
    assert _user_version(conn) == migrations.CURRENT_VERSION
    conn.close()


def test_fresh_db_seeds_all_glossaries():
    conn = store.connect(":memory:")

    store.migrate(conn)

    assert store.get_statement_kind_glossary(conn, "event") is not None
    assert store.get_statement_link_type_glossary(conn, "contains") is not None
    assert store.get_entity_link_type_glossary(conn, "sub-type") is not None


def test_migrate_does_not_restore_deleted_glossary_rows():
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("DELETE FROM statement_kind_glossary WHERE kind = 'event'")
    conn.execute(
        "DELETE FROM statement_link_type_glossary WHERE link_type = 'triggers'"
    )
    conn.execute("DELETE FROM entity_link_type_glossary WHERE link_type = 'uses'")

    store.migrate(conn)

    assert store.get_statement_kind_glossary(conn, "event") is None
    assert store.get_statement_link_type_glossary(conn, "triggers") is None
    assert store.get_entity_link_type_glossary(conn, "uses") is None
    assert store.get_statement_kind_glossary(conn, "state") is not None
    assert store.get_statement_link_type_glossary(conn, "contains") is not None
    assert store.get_entity_link_type_glossary(conn, "sub-type") is not None


def test_migrate_keeps_an_existing_empty_glossary_empty():
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("DELETE FROM statement_kind_glossary")

    store.migrate(conn)

    assert store.list_statement_kind_glossary(conn) == []
    assert store.get_statement_link_type_glossary(conn, "contains") is not None
    assert store.get_entity_link_type_glossary(conn, "sub-type") is not None


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
    # removed. Ambiguity no longer creates a review task.
    mention_worker.drain(conn)
    assert store.get_mentions(conn, sid) == []
    assert conn.execute("SELECT * FROM pending_mentions").fetchall() == []


def _downgrade_names_to_case_sensitive(conn):
    """Rebuild `names` without the NOCASE collation, simulating a pre-v6
    DB so the v6 migration's merge actually runs (same rename-and-copy
    dance the migration itself uses)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "CREATE TABLE names_plain ("
        "id TEXT PRIMARY KEY, text TEXT NOT NULL UNIQUE, "
        "entity_id TEXT NOT NULL REFERENCES entities(id), "
        "generated_from_name_id TEXT REFERENCES names_plain(id), "
        "created_at TEXT, updated_at TEXT, created_by TEXT, updated_by TEXT)"
    )
    conn.execute("INSERT INTO names_plain SELECT * FROM names")
    conn.execute("DROP TABLE names")
    conn.execute("ALTER TABLE names_plain RENAME TO names")
    # The INSERT above opened sqlite3's implicit transaction, and FK
    # pragmas are no-ops while one is open — commit first, or the
    # re-enable is silently swallowed and everything after this helper
    # runs unenforced (which is exactly how the v6 FK bug slipped past
    # the first version of these tests).
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()


def test_v6_merges_case_variant_names_and_absorbs_empty_entities():
    """A pre-v6 DB where a case-variant upsert minted a duplicate entity:
    v6 merges the name rows onto the oldest, moves its mentions, absorbs
    the now-nameless duplicate entity (links repointed, duplicates
    dropped), and leaves the table case-insensitive."""
    conn = store.connect(":memory:")
    store.migrate(conn)
    _downgrade_names_to_case_sensitive(conn)

    ent_a = store.create_entity(conn, "the checklist feature")
    ent_b = store.create_entity(conn, None)  # minted by a variant upsert
    ent_c = store.create_entity(conn, "unrelated")
    keeper = store.create_name(conn, "Checklist", ent_a)
    variant = store.create_name(conn, "checklist", ent_b)
    store.create_name(conn, "Other", ent_c)

    sid = store.create_statement(conn, "state", "the checklist has items")
    conn.execute(
        "INSERT INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        (sid, variant),
    )
    # A statement reachable ONLY through a pending (suspect) row on the
    # variant — must still be enqueued for recompute when that row goes.
    pending_sid = store.create_statement(conn, "state", "checklist pending only")
    conn.execute(
        "INSERT INTO pending_mentions (statement_id, name_id, created_at) "
        "VALUES (?, ?, '2026-01-01T00:00:00.000Z')",
        (pending_sid, variant),
    )
    # ent_b carries links: one that duplicates an existing ent_a link
    # (dropped), one only it has (repointed onto ent_a).
    conn.execute(
        "INSERT INTO entity_links (from_entity_id, to_entity_id, link_type) "
        "VALUES (?, ?, 'relates-to'), (?, ?, 'relates-to'), (?, ?, 'contains')",
        (ent_a, ent_c, ent_b, ent_c, ent_b, ent_c),
    )
    conn.execute("DELETE FROM mention_recompute_queue")
    conn.commit()

    migrations.apply_migrations(conn)

    # One "Checklist" row survives, on the original entity.
    rows = conn.execute(
        "SELECT id, text, entity_id FROM names ORDER BY text"
    ).fetchall()
    assert [(r["id"], r["text"], r["entity_id"]) for r in rows] == [
        (keeper, "Checklist", ent_a),
        *[(r["id"], "Other", ent_c) for r in rows[1:]],
    ]
    # The variant's mention moved to the keeper; the statement is queued
    # for recompute.
    assert [
        r["name_id"]
        for r in conn.execute(
            "SELECT name_id FROM statement_mentions WHERE statement_id = ?", (sid,)
        )
    ] == [keeper]
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM mention_recompute_queue WHERE statement_id = ?",
            (sid,),
        ).fetchone()["n"]
        == 1
    )
    # The pending-only statement lost its review row but is queued to
    # re-derive it against the keeper.
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM pending_mentions WHERE statement_id = ?",
            (pending_sid,),
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM mention_recompute_queue WHERE statement_id = ?",
            (pending_sid,),
        ).fetchone()["n"]
        == 1
    )
    # The nameless duplicate entity is gone; its unique link moved, the
    # duplicate link was dropped rather than doubled.
    assert (
        conn.execute("SELECT 1 FROM entities WHERE id = ?", (ent_b,)).fetchone() is None
    )
    links = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type FROM entity_links "
        "ORDER BY link_type"
    ).fetchall()
    assert [
        (r["from_entity_id"], r["to_entity_id"], r["link_type"]) for r in links
    ] == [
        (ent_a, ent_c, "contains"),
        (ent_a, ent_c, "relates-to"),
    ]
    # Foreign-key enforcement survived the rebuild's pragma dance (an
    # OFF or ON swallowed by an open transaction would show up here).
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    # The rebuilt table enforces case-insensitive uniqueness.
    import pytest as _pytest

    with _pytest.raises(sqlite3.IntegrityError):
        store.create_name(conn, "CHECKLIST", ent_c)


def test_v6_adopts_description_and_prefers_human_authored_keeper():
    conn = store.connect(":memory:")
    store.migrate(conn)
    _downgrade_names_to_case_sensitive(conn)

    # Keeper preference: a human-authored variant wins over an OLDER
    # generated plural.
    ent_a = store.create_entity(conn, None)
    ent_b = store.create_entity(conn, "described by the variant")
    widget = store.create_name(conn, "Widget", ent_a)
    conn.execute(
        "INSERT INTO names (id, text, entity_id, generated_from_name_id) "
        "VALUES ('nam_gen', 'Widgets', ?, ?)",
        (ent_a, widget),
    )
    human = store.create_name(conn, "widgets", ent_b)
    conn.commit()

    migrations.apply_migrations(conn)

    rows = {
        r["text"]: r
        for r in conn.execute("SELECT id, text, entity_id FROM names").fetchall()
    }
    assert set(rows) == {"Widget", "widgets"}
    assert rows["widgets"]["id"] == human  # human-authored row won
    assert rows["widgets"]["entity_id"] == ent_b
    # ent_a kept "Widget", so it was NOT absorbed; both entities remain.
    assert conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"] == 2


def test_v6_description_adoption_on_absorb():
    conn = store.connect(":memory:")
    store.migrate(conn)
    _downgrade_names_to_case_sensitive(conn)

    ent_a = store.create_entity(conn, None)  # keeper entity, no description
    ent_b = store.create_entity(conn, "rich description from the duplicate")
    store.create_name(conn, "Gadget", ent_a)
    store.create_name(conn, "gadget", ent_b)
    conn.commit()

    migrations.apply_migrations(conn)

    assert (
        conn.execute("SELECT 1 FROM entities WHERE id = ?", (ent_b,)).fetchone() is None
    )
    assert (
        conn.execute(
            "SELECT description FROM entities WHERE id = ?", (ent_a,)
        ).fetchone()["description"]
        == "rich description from the duplicate"
    )


def test_v6_rebuild_keeps_the_name_entity_index():
    """The rebuild drops `names` with its indexes and SCHEMA has already run
    for this open, so an upgrading DB would otherwise lose `names_entity` —
    and with it the index the shared-mention lookup plans against."""
    conn = store.connect(":memory:")
    store.migrate(conn)
    _downgrade_names_to_case_sensitive(conn)

    migrations.apply_migrations(conn)

    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'names_entity'"
    ).fetchone()


def test_v18_drops_the_kind_link_matrix():
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("CREATE TABLE kind_link_matrix (from_kind TEXT)")
    conn.execute("PRAGMA user_version = 17")
    conn.commit()

    migrations.apply_migrations(conn)

    assert not migrations._has_table(conn, "kind_link_matrix")


def _v12_with_condition() -> tuple[sqlite3.Connection, str, str, str]:
    conn = store.connect(":memory:")
    store.migrate(conn)
    migrations._migration_v3_entity_statement_links(conn)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA user_version = 12")
    a = store.create_statement(conn, "action", "Click Save.")
    b = store.create_statement(conn, "event", "Changes are saved.")
    condition = store.create_statement(conn, "state", "The user is signed in.")
    store.insert_links(
        conn,
        [(a, b, "performs", {"op": "not", "of": [{"statement_id": condition}]})],
    )
    conn.commit()
    return conn, a, b, condition


def test_v14_preserves_condition_tree_and_restores_link_foreign_key():
    conn, a, b, condition = _v12_with_condition()
    before = [
        tuple(r)
        for r in conn.execute(
            "SELECT node_id, link_id, parent_id, op, statement_id, child_index FROM when_nodes"
        )
    ]
    conn.execute("UPDATE sqlite_sequence SET seq = 100 WHERE name = 'when_nodes'")
    conn.commit()
    store.migrate(conn)
    assert (
        conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'when_nodes'"
        ).fetchone()[0]
        == 100
    )
    assert not _has_column(conn, "when_nodes", "link_kind")
    assert [tuple(r) for r in conn.execute("SELECT * FROM when_nodes")] == before
    assert store.get_links(conn, a) == [
        (b, "performs", {"op": "not", "of": [{"statement_id": condition}]})
    ]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute("DELETE FROM statement_links")
    assert conn.execute("SELECT COUNT(*) FROM when_nodes").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO when_nodes (link_id, statement_id, child_index) VALUES (?, ?, 0)",
            (999, condition),
        )
    conn.close()


@pytest.mark.parametrize("legacy_condition_only", [False, True])
def test_v14_refuses_unrescued_knowledge_without_changing_database(
    legacy_condition_only,
):
    conn, a, _b, condition = _v12_with_condition()
    entity = store.create_entity(conn, "Reviewer")
    if legacy_condition_only:
        conn.execute(
            "INSERT INTO when_nodes (link_id, link_kind, statement_id, child_index) "
            "VALUES (999, 'entity_statement', ?, 0)",
            (condition,),
        )
    else:
        conn.execute(
            "INSERT INTO entity_statement_links "
            "(entity_id, statement_id, direction, link_type, when_hash) "
            "VALUES (?, ?, 'es', 'performs', 'NONE')",
            (entity, a),
        )
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(RuntimeError, match="completed knowledge rescue"):
        store.migrate(conn)
    assert list(conn.iterdump()) == before
    assert _user_version(conn) == 12
    conn.close()


def test_v14_failed_rebuild_rolls_back_schema_and_tree():
    conn, _a, _b, _condition = _v12_with_condition()
    conn.execute("UPDATE when_nodes SET link_id = 999")
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(RuntimeError, match="condition tree integrity failed"):
        migrations.apply_migrations(conn)
    assert list(conn.iterdump()) == before
    assert _user_version(conn) == 13
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def _v14_with_alias_embeddings() -> sqlite3.Connection:
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("ALTER TABLE link_type_aliases ADD COLUMN embedding BLOB")
    conn.execute(
        "CREATE TABLE link_type_alias_embed_queue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, link_type TEXT NOT NULL, "
        "alias TEXT NOT NULL, enqueued_at TEXT NOT NULL, claimed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, embedding, provenance, score, direction, "
        "created_at, created_by) "
        "VALUES ('contains', 'is housed in', x'00ff', 'auto', 0.91, 'reverse', "
        "'chosen-at', 'curator')"
    )
    conn.execute(
        "INSERT INTO link_type_alias_embed_queue (link_type, alias, enqueued_at) "
        "VALUES ('contains', 'is housed in', 'chosen-at')"
    )
    conn.execute("PRAGMA user_version = 14")
    conn.commit()
    return conn


def _aliases(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT link_type, alias, provenance, score, direction, created_at, "
            "created_by FROM link_type_aliases ORDER BY link_type, alias"
        )
    ]


def test_v15_drops_alias_embeddings_and_keeps_every_alias():
    conn = _v14_with_alias_embeddings()
    before = _aliases(conn)

    store.migrate(conn)

    assert _user_version(conn) == migrations.CURRENT_VERSION
    assert not _has_column(conn, "link_type_aliases", "embedding")
    assert not migrations._has_table(conn, "link_type_alias_embed_queue")
    assert _aliases(conn) == before
    assert ("contains", "is housed in", "auto", 0.91, "reverse") in [
        row[:5] for row in before
    ]
    conn.close()


def test_v15_failed_rebuild_rolls_back():
    conn = _v14_with_alias_embeddings()
    # The rename refuses while a view names the dropped table.
    conn.execute("CREATE VIEW alias_texts AS SELECT alias FROM link_type_aliases")
    conn.commit()
    before = list(conn.iterdump())

    with pytest.raises(sqlite3.OperationalError):
        migrations.apply_migrations(conn)

    assert list(conn.iterdump()) == before
    assert _user_version(conn) == 14
    conn.close()


def test_v17_rewrites_only_an_untouched_rule_definition():
    def at_v16(description: str, when_to_use: str) -> sqlite3.Connection:
        conn = store.connect(":memory:")
        store.migrate(conn)
        conn.execute(
            "UPDATE statement_kind_glossary SET description = ?, when_to_use = ? "
            "WHERE kind = 'rule'",
            (description, when_to_use),
        )
        conn.execute("PRAGMA user_version = 16")
        conn.commit()
        return conn

    def rule(conn: sqlite3.Connection) -> str:
        return conn.execute(
            "SELECT description FROM statement_kind_glossary WHERE kind = 'rule'"
        ).fetchone()[0]

    seeded = at_v16(*migrations._V16_RULE_DEFINITION)
    curated = at_v16("Our own wording.", "Whenever.")

    store.migrate(seeded)
    store.migrate(curated)

    assert rule(seeded).startswith("An obligation or permission")
    assert rule(curated) == "Our own wording."


def test_v19_rewrites_only_an_untouched_sub_type_definition():
    # The v18 fixture holds the old seed, whose text stays out of the source.
    v18 = Path(__file__).parent / "migration_fixtures/v18-c9b30c9/mycelium.sql"

    def at_v18(description: str | None) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(v18.read_text())
        if description is not None:
            conn.execute(
                "UPDATE entity_link_type_glossary SET description = ? "
                "WHERE link_type = 'sub-type'",
                (description,),
            )
        conn.commit()
        return conn

    def sub_type(conn: sqlite3.Connection) -> str:
        return conn.execute(
            "SELECT description FROM entity_link_type_glossary "
            "WHERE link_type = 'sub-type'"
        ).fetchone()[0]

    seeded = at_v18(None)
    curated = at_v18("Our own wording.")

    migrations.apply_migrations(seeded)
    migrations.apply_migrations(curated)

    assert sub_type(seeded) == glossary._ENTITY_LINK_TYPE_SEED["sub-type"]
    assert sub_type(curated) == "Our own wording."


def test_v24_keeps_the_connect_pass_looks_as_curation_attempts():
    conn = store.connect(":memory:")
    store.migrate(conn)
    sid = store.create_statement(conn, "event", "An invoice is exported.")
    conn.execute("DROP TABLE curation_attempts")
    conn.execute("DROP TABLE curation_claims")
    migrations._migration_v23_connect_attempts(conn)
    conn.execute(
        "INSERT INTO connect_attempts VALUES (?, 'An invoice is exported.', '[]', "
        "'2026-08-01T00:00:00Z')",
        (sid,),
    )
    conn.execute("PRAGMA user_version = 23")
    conn.commit()

    migrations.apply_migrations(conn)

    row = conn.execute("SELECT * FROM curation_attempts").fetchone()
    assert (row["item_id"], row["outcome"], row["attempted_by"]) == (
        sid,
        "looked",
        None,
    )
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "connect_attempts" not in tables


def test_v28_adds_the_automatic_stop_ledger():
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("DROP TABLE automation_stops")
    conn.execute("PRAGMA user_version = 27")
    conn.commit()

    migrations.apply_migrations(conn)

    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(automation_stops)")
    }
    assert columns == {
        "kind",
        "item_id",
        "inputs",
        "failures",
        "stopped",
        "reason",
        "updated_at",
    }


def test_v29_keeps_stops_and_takes_the_new_kinds():
    conn = store.connect(":memory:")
    store.migrate(conn)
    conn.execute("DROP TABLE automation_stops")
    migrations._migration_v28_automation_stops(conn)
    conn.execute(
        "INSERT INTO automation_stops VALUES ('connect', 'stm_1', 't', 3, 1, 'r', 'now')"
    )
    conn.execute("PRAGMA user_version = 28")
    conn.commit()

    migrations.apply_migrations(conn)
    conn.execute(
        "INSERT INTO automation_stops VALUES ('mention', '7', 's', 1, 0, 'r', 'now')"
    )

    assert [
        tuple(row) for row in conn.execute("SELECT kind, item_id FROM automation_stops")
    ] == [("connect", "stm_1"), ("mention", "7")]
