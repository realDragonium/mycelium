"""Test alias persistence and curator-facing tool validation."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from mycelium import (
    auth_store,
    drafts_store,
    embed,
    migrations,
    server,
    store,
)
from mycelium.server import runtime


@pytest.fixture
def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def _app(tmp_path, monkeypatch):
    """Build an isolated server with a fake embedding client."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    from mycelium.http import create_app  # local import: avoid the server/http cycle

    return TestClient(create_app())


def test_migrate_seeds_once_without_resurrecting_deleted_alias(fresh_conn):
    before = [dict(row) for row in store.list_link_type_aliases(fresh_conn)]
    assert before
    assert store.seed_link_type_aliases(fresh_conn) == 0
    assert [dict(row) for row in store.list_link_type_aliases(fresh_conn)] == before

    assert store.delete_link_type_alias(fresh_conn, "contains", "includes") is True
    assert store.seed_link_type_aliases(fresh_conn) == 0
    aliases_for_contains = store.list_link_type_aliases(fresh_conn, "contains")
    assert "includes" not in {row["alias"] for row in aliases_for_contains}


def test_upsert_normalizes_and_updates_provenance(fresh_conn):
    created = store.upsert_link_type_alias(
        fresh_conn, "custom-fallback", "  Falls  Back TO "
    )
    assert created is True

    created = store.upsert_link_type_alias(
        fresh_conn,
        "custom-fallback",
        "falls back to",
        provenance="absorbed",
        score=0.75,
    )
    assert created is False
    row = store.list_link_type_aliases(fresh_conn, "custom-fallback")[0]
    assert row["alias"] == "falls back to"
    assert row["provenance"] == "absorbed"
    assert row["score"] == 0.75


def test_delete_alias_is_idempotent(fresh_conn):
    store.upsert_link_type_alias(fresh_conn, "custom", "discard me")

    assert store.delete_link_type_alias(fresh_conn, "custom", " DISCARD  ME ") is True
    assert store.delete_link_type_alias(fresh_conn, "custom", "discard me") is False


def test_list_aliases_filters_by_link_type(fresh_conn):
    rows = store.list_link_type_aliases(fresh_conn, "proceeds")
    assert rows
    assert {row["link_type"] for row in rows} == {"proceeds"}


def test_migration_v9_backfills_legacy_alias_tables():
    """A v8 table gets the column, every reverse flip, and the missing alias."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE link_type_aliases (
            link_type TEXT NOT NULL, alias TEXT NOT NULL, embedding BLOB,
            provenance TEXT NOT NULL DEFAULT 'seed', score REAL,
            created_at TEXT, created_by TEXT, PRIMARY KEY (link_type, alias));
        """
    )
    # A curator once re-upserted this seed row: provenance is no longer
    # 'seed', but no direction on v8 was ever a curator's choice.
    conn.execute(
        "INSERT INTO link_type_aliases (link_type, alias, provenance) "
        "VALUES ('requires', 'is required for', 'curator')"
    )
    # "is one of" was deliberately deleted by a curator on this DB: the
    # migration must not resurrect it.
    conn.execute(
        "INSERT INTO link_type_aliases (link_type, alias) VALUES ('cases', 'either')"
    )

    migrations._migration_v9_alias_direction(conn)

    rows = {
        (row["link_type"], row["alias"]): row["direction"]
        for row in conn.execute(
            "SELECT link_type, alias, direction FROM link_type_aliases"
        )
    }
    assert rows[("requires", "is required for")] == "reverse"
    assert ("cases", "is one of") not in rows
    # The alias the old seed lacked is inserted, since seeding never runs
    # again on a non-empty table.
    assert rows[("contains", "is part of")] == "reverse"


def test_migration_v9_leaves_an_unseeded_table_for_seeding():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE link_type_aliases (
            link_type TEXT NOT NULL, alias TEXT NOT NULL, embedding BLOB,
            provenance TEXT NOT NULL DEFAULT 'seed', score REAL,
            created_at TEXT, created_by TEXT, PRIMARY KEY (link_type, alias));
        """
    )

    migrations._migration_v9_alias_direction(conn)

    # Inserting into an empty table would stop seed_link_type_aliases from
    # ever running, leaving a one-alias vocabulary.
    assert conn.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0


def _v9_alias_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE link_type_aliases (
            link_type TEXT NOT NULL, alias TEXT NOT NULL, embedding BLOB,
            provenance TEXT NOT NULL DEFAULT 'seed', score REAL,
            direction TEXT NOT NULL DEFAULT 'forward',
            created_at TEXT, created_by TEXT, PRIMARY KEY (link_type, alias));
        """
    )
    return conn


def test_migration_v10_adds_only_missing_belongs_to_aliases():
    seeded = _v9_alias_conn()
    seeded.execute(
        "INSERT INTO link_type_aliases (link_type, alias) "
        "VALUES ('contains', 'includes')"
    )

    migrations._migration_v10_belongs_to_aliases(seeded)

    rows = seeded.execute(
        "SELECT link_type, alias, provenance, direction, created_at "
        "FROM link_type_aliases WHERE alias IN ('belongs to', 'is owned by') "
        "ORDER BY alias"
    ).fetchall()
    assert [
        (row["link_type"], row["alias"], row["provenance"], row["direction"])
        for row in rows
    ] == [
        ("contains", "belongs to", "seed", "reverse"),
        ("contains", "is owned by", "seed", "reverse"),
    ]
    assert all(row["created_at"] for row in rows)

    absorbed = _v9_alias_conn()
    absorbed.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES ('contains', 'includes', 'seed', NULL, 'forward', NULL, NULL), "
        "('contains', 'belongs to', 'auto', 0.91, 'forward', 'chosen-at', 'curator')"
    )

    migrations._migration_v10_belongs_to_aliases(absorbed)

    existing = absorbed.execute(
        "SELECT provenance, score, direction, created_at, created_by "
        "FROM link_type_aliases "
        "WHERE link_type = 'contains' AND alias = 'belongs to'"
    ).fetchone()
    assert tuple(existing) == ("auto", 0.91, "forward", "chosen-at", "curator")

    empty = _v9_alias_conn()
    migrations._migration_v10_belongs_to_aliases(empty)
    assert empty.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0


def test_migration_v11_adds_only_missing_passive_by_aliases():
    seeded = _v9_alias_conn()
    seeded.execute(
        "INSERT INTO link_type_aliases (link_type, alias) "
        "VALUES ('contains', 'includes')"
    )

    migrations._migration_v11_passive_by_aliases(seeded)

    rows = seeded.execute(
        "SELECT link_type, alias, provenance, direction, created_at "
        "FROM link_type_aliases "
        "WHERE alias IN ('is limited by', 'is bounded by', 'is locked by', "
        "'is capped by', 'is disabled by', 'is frozen by', 'is suspended by', "
        "'is enabled by', 'is unlocked by') ORDER BY link_type, alias"
    ).fetchall()
    assert [
        (row["link_type"], row["alias"], row["provenance"], row["direction"])
        for row in rows
    ] == [
        ("enables", "is enabled by", "seed", "reverse"),
        ("enables", "is unlocked by", "seed", "reverse"),
        ("restricts", "is bounded by", "seed", "reverse"),
        ("restricts", "is capped by", "seed", "reverse"),
        ("restricts", "is disabled by", "seed", "reverse"),
        ("restricts", "is frozen by", "seed", "reverse"),
        ("restricts", "is limited by", "seed", "reverse"),
        ("restricts", "is locked by", "seed", "reverse"),
        ("restricts", "is suspended by", "seed", "reverse"),
    ]
    assert all(row["created_at"] for row in rows)

    absorbed = _v9_alias_conn()
    absorbed.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES ('contains', 'includes', 'seed', NULL, 'forward', NULL, NULL), "
        "('restricts', 'is locked by', 'auto', 0.91, 'forward', "
        "'chosen-at', 'curator')"
    )

    migrations._migration_v11_passive_by_aliases(absorbed)

    existing = absorbed.execute(
        "SELECT provenance, score, direction, created_at, created_by "
        "FROM link_type_aliases "
        "WHERE link_type = 'restricts' AND alias = 'is locked by'"
    ).fetchone()
    assert tuple(existing) == ("auto", 0.91, "forward", "chosen-at", "curator")

    empty = _v9_alias_conn()
    migrations._migration_v11_passive_by_aliases(empty)
    assert empty.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0


def test_migrate_sets_alias_schema_version(fresh_conn):
    assert (
        fresh_conn.execute("PRAGMA user_version").fetchone()[0]
        == migrations.CURRENT_VERSION
    )


def test_tool_stores_automatic_provenance_and_score(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        result = server.upsert_link_type_alias(
            "proceeds",
            "then after",
            provenance="auto",
            score=0.83,
        )

        assert result == {
            "link_type": "proceeds",
            "alias": "then after",
            "provenance": "auto",
            "score": 0.83,
            "direction": "forward",
            "created": True,
        }
        row = next(
            row
            for row in store.list_link_type_aliases(server._db(), "proceeds")
            if row["alias"] == "then after"
        )
        assert row["provenance"] == "auto"
        assert row["score"] == 0.83


@pytest.mark.parametrize("provenance", ["seed", "whatever"])
def test_tool_rejects_unassertable_provenance(tmp_path, monkeypatch, provenance):
    with _app(tmp_path, monkeypatch):
        with pytest.raises(ValueError):
            server.upsert_link_type_alias(
                "proceeds",
                "then after",
                provenance=provenance,
            )


@pytest.mark.parametrize("score", [1.5, -2.0])
def test_tool_rejects_score_outside_cosine_range(tmp_path, monkeypatch, score):
    with _app(tmp_path, monkeypatch):
        with pytest.raises(ValueError):
            server.upsert_link_type_alias(
                "proceeds",
                "then after",
                provenance="auto",
                score=score,
            )


def test_tool_accepts_none_score(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        result = server.upsert_link_type_alias(
            "proceeds",
            "then after",
            score=None,
        )

        assert result["score"] is None


def test_curator_reassertion_retags_automatic_alias(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        server.upsert_link_type_alias(
            "proceeds",
            "then after",
            provenance="auto",
            score=0.83,
        )

        result = server.upsert_link_type_alias("proceeds", "then after")

        assert result["created"] is False
        assert result["provenance"] == "curator"
        assert result["score"] is None
        row = next(
            row
            for row in store.list_link_type_aliases(server._db(), "proceeds")
            if row["alias"] == "then after"
        )
        assert row["provenance"] == "curator"
        assert row["score"] is None


@pytest.mark.parametrize("provenance", ["auto", "auto:low-confidence"])
def test_tool_requires_a_score_for_automatic_provenance(
    tmp_path, monkeypatch, provenance
):
    with _app(tmp_path, monkeypatch):
        with pytest.raises(ValueError):
            server.upsert_link_type_alias(
                "proceeds",
                "then after",
                provenance=provenance,
            )
