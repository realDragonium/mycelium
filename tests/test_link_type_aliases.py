"""Test alias persistence, embedding, and curator-facing tool validation."""

from __future__ import annotations

import logging
import sqlite3
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mycelium import (
    alias_worker,
    auth_store,
    drafts_store,
    embed,
    migrations,
    server,
    store,
)
from mycelium.connect import aliases


@pytest.fixture
def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def _app(tmp_path, monkeypatch):
    """Build an isolated server with a fake embedding client."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    server._ctx = None
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    from mycelium.http import app  # local import: avoid the server/http cycle

    return TestClient(app)


def test_migrate_seeds_once_without_resurrecting_deleted_alias(fresh_conn):
    before = [dict(row) for row in store.list_link_type_aliases(fresh_conn)]
    assert before
    assert store.seed_link_type_aliases(fresh_conn) == 0
    assert [dict(row) for row in store.list_link_type_aliases(fresh_conn)] == before

    assert store.delete_link_type_alias(fresh_conn, "contains", "includes") is True
    assert store.seed_link_type_aliases(fresh_conn) == 0
    aliases_for_contains = store.list_link_type_aliases(fresh_conn, "contains")
    assert "includes" not in {row["alias"] for row in aliases_for_contains}


def test_every_seeded_alias_is_enqueued(fresh_conn):
    seeded_count = len(store.list_link_type_aliases(fresh_conn))
    assert store.count_open_alias_embeddings(fresh_conn) == seeded_count


def test_upsert_normalizes_enqueues_once_and_updates_provenance(fresh_conn):
    before = store.count_open_alias_embeddings(fresh_conn)

    created = store.upsert_link_type_alias(
        fresh_conn, "custom-fallback", "  Falls  Back TO "
    )
    assert created is True
    assert store.count_open_alias_embeddings(fresh_conn) == before + 1

    created = store.upsert_link_type_alias(
        fresh_conn,
        "custom-fallback",
        "falls back to",
        provenance="absorbed",
        score=0.75,
    )
    assert created is False
    assert store.count_open_alias_embeddings(fresh_conn) == before + 1
    row = store.list_link_type_aliases(fresh_conn, "custom-fallback")[0]
    assert row["alias"] == "falls back to"
    assert row["provenance"] == "absorbed"
    assert row["score"] == 0.75


def test_delete_alias_is_idempotent_and_removes_open_jobs(fresh_conn):
    before = store.count_open_alias_embeddings(fresh_conn)
    store.upsert_link_type_alias(fresh_conn, "custom", "discard me")
    assert store.count_open_alias_embeddings(fresh_conn) == before + 1

    assert store.delete_link_type_alias(fresh_conn, "custom", " DISCARD  ME ") is True
    assert store.count_open_alias_embeddings(fresh_conn) == before
    assert store.delete_link_type_alias(fresh_conn, "custom", "discard me") is False


def test_alias_lookup_and_longest_first_grouping(fresh_conn):
    store.upsert_link_type_alias(fresh_conn, "alpha", "shared cue")
    store.upsert_link_type_alias(fresh_conn, "beta", "shared cue")
    store.upsert_link_type_alias(fresh_conn, "ordering", "short")
    store.upsert_link_type_alias(fresh_conn, "ordering", "a much longer cue")
    store.upsert_link_type_alias(fresh_conn, "ordering", "equal a")
    store.upsert_link_type_alias(fresh_conn, "ordering", "equal b")

    assert store.alias_lookup(fresh_conn)["shared cue"] == frozenset(
        {("alpha", "forward"), ("beta", "forward")}
    )
    assert store.aliases_by_type(fresh_conn)["ordering"] == (
        "a much longer cue",
        "equal a",
        "equal b",
        "short",
    )


def test_seed_aliases_match_fresh_install(fresh_conn):
    assert store.seed_aliases_by_type() == store.aliases_by_type(fresh_conn)


def test_list_aliases_filters_and_exposes_embedding_state(fresh_conn):
    rows = store.list_link_type_aliases(fresh_conn, "proceeds")
    assert rows
    assert {row["link_type"] for row in rows} == {"proceeds"}
    assert all(row["embedded"] == 0 for row in rows)


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
        CREATE TABLE link_type_alias_embed_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, link_type TEXT NOT NULL,
            alias TEXT NOT NULL, enqueued_at TEXT, claimed_at TEXT);
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
    # The alias the old seed lacked is inserted with an embedding job, since
    # seeding never runs again on a non-empty table.
    assert rows[("contains", "is part of")] == "reverse"
    queued = conn.execute(
        "SELECT link_type, alias FROM link_type_alias_embed_queue"
    ).fetchall()
    assert [(row["link_type"], row["alias"]) for row in queued] == [
        ("contains", "is part of")
    ]


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
        CREATE TABLE link_type_alias_embed_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, link_type TEXT NOT NULL,
            alias TEXT NOT NULL, enqueued_at TEXT, claimed_at TEXT);
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
    assert [
        (row["link_type"], row["alias"])
        for row in seeded.execute(
            "SELECT link_type, alias FROM link_type_alias_embed_queue ORDER BY alias"
        )
    ] == [
        ("contains", "belongs to"),
        ("contains", "is owned by"),
    ]

    absorbed = _v9_alias_conn()
    absorbed.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES ('contains', 'includes', 'seed', NULL, 'forward', NULL, NULL), "
        "('contains', 'belongs to', 'auto', 0.91, 'forward', 'chosen-at', 'curator')"
    )
    absorbed.execute(
        "INSERT INTO link_type_alias_embed_queue "
        "(link_type, alias, enqueued_at) "
        "VALUES ('contains', 'belongs to', 'chosen-at')"
    )

    migrations._migration_v10_belongs_to_aliases(absorbed)

    existing = absorbed.execute(
        "SELECT provenance, score, direction, created_at, created_by "
        "FROM link_type_aliases "
        "WHERE link_type = 'contains' AND alias = 'belongs to'"
    ).fetchone()
    assert tuple(existing) == ("auto", 0.91, "forward", "chosen-at", "curator")
    queued = absorbed.execute(
        "SELECT alias FROM link_type_alias_embed_queue ORDER BY id"
    ).fetchall()
    assert [row["alias"] for row in queued] == ["belongs to", "is owned by"]

    empty = _v9_alias_conn()
    migrations._migration_v10_belongs_to_aliases(empty)
    assert empty.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0
    assert (
        empty.execute("SELECT COUNT(*) FROM link_type_alias_embed_queue").fetchone()[0]
        == 0
    )


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
    assert [
        (row["link_type"], row["alias"])
        for row in seeded.execute(
            "SELECT link_type, alias FROM link_type_alias_embed_queue "
            "ORDER BY link_type, alias"
        )
    ] == [
        ("enables", "is enabled by"),
        ("enables", "is unlocked by"),
        ("restricts", "is bounded by"),
        ("restricts", "is capped by"),
        ("restricts", "is disabled by"),
        ("restricts", "is frozen by"),
        ("restricts", "is limited by"),
        ("restricts", "is locked by"),
        ("restricts", "is suspended by"),
    ]

    absorbed = _v9_alias_conn()
    absorbed.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES ('contains', 'includes', 'seed', NULL, 'forward', NULL, NULL), "
        "('restricts', 'is locked by', 'auto', 0.91, 'forward', "
        "'chosen-at', 'curator')"
    )
    absorbed.execute(
        "INSERT INTO link_type_alias_embed_queue "
        "(link_type, alias, enqueued_at) "
        "VALUES ('restricts', 'is locked by', 'chosen-at')"
    )

    migrations._migration_v11_passive_by_aliases(absorbed)

    existing = absorbed.execute(
        "SELECT provenance, score, direction, created_at, created_by "
        "FROM link_type_aliases "
        "WHERE link_type = 'restricts' AND alias = 'is locked by'"
    ).fetchone()
    assert tuple(existing) == ("auto", 0.91, "forward", "chosen-at", "curator")
    queued = absorbed.execute(
        "SELECT link_type, alias FROM link_type_alias_embed_queue ORDER BY id"
    ).fetchall()
    assert [(row["link_type"], row["alias"]) for row in queued] == [
        ("restricts", "is locked by"),
        ("restricts", "is limited by"),
        ("restricts", "is bounded by"),
        ("restricts", "is capped by"),
        ("restricts", "is disabled by"),
        ("restricts", "is frozen by"),
        ("restricts", "is suspended by"),
        ("enables", "is enabled by"),
        ("enables", "is unlocked by"),
    ]

    empty = _v9_alias_conn()
    migrations._migration_v11_passive_by_aliases(empty)
    assert empty.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0
    assert (
        empty.execute("SELECT COUNT(*) FROM link_type_alias_embed_queue").fetchone()[0]
        == 0
    )


def test_migration_v12_adds_only_missing_cases_level_aliases():
    seeded = _v9_alias_conn()
    seeded.execute(
        "INSERT INTO link_type_aliases (link_type, alias) "
        "VALUES ('contains', 'includes')"
    )

    migrations._migration_v12_cases_level_aliases(seeded)

    rows = seeded.execute(
        "SELECT link_type, alias, provenance, direction, created_at "
        "FROM link_type_aliases "
        "WHERE alias IN ('is low for', 'is medium for', 'is high for', "
        "'is extra high for', 'is none for', 'is positive for', "
        "'is negative for') ORDER BY alias"
    ).fetchall()
    assert [
        (row["link_type"], row["alias"], row["provenance"], row["direction"])
        for row in rows
    ] == [
        ("cases", "is extra high for", "seed", "reverse"),
        ("cases", "is high for", "seed", "reverse"),
        ("cases", "is low for", "seed", "reverse"),
        ("cases", "is medium for", "seed", "reverse"),
        ("cases", "is negative for", "seed", "reverse"),
        ("cases", "is none for", "seed", "reverse"),
        ("cases", "is positive for", "seed", "reverse"),
    ]
    assert all(row["created_at"] for row in rows)
    assert [
        (row["link_type"], row["alias"])
        for row in seeded.execute(
            "SELECT link_type, alias FROM link_type_alias_embed_queue ORDER BY alias"
        )
    ] == [
        ("cases", "is extra high for"),
        ("cases", "is high for"),
        ("cases", "is low for"),
        ("cases", "is medium for"),
        ("cases", "is negative for"),
        ("cases", "is none for"),
        ("cases", "is positive for"),
    ]

    absorbed = _v9_alias_conn()
    absorbed.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES ('contains', 'includes', 'seed', NULL, 'forward', NULL, NULL), "
        "('cases', 'is high for', 'auto', 0.91, 'forward', "
        "'chosen-at', 'curator')"
    )
    absorbed.execute(
        "INSERT INTO link_type_alias_embed_queue "
        "(link_type, alias, enqueued_at) "
        "VALUES ('cases', 'is high for', 'chosen-at')"
    )

    migrations._migration_v12_cases_level_aliases(absorbed)

    existing = absorbed.execute(
        "SELECT provenance, score, direction, created_at, created_by "
        "FROM link_type_aliases "
        "WHERE link_type = 'cases' AND alias = 'is high for'"
    ).fetchone()
    assert tuple(existing) == ("auto", 0.91, "forward", "chosen-at", "curator")
    queued = absorbed.execute(
        "SELECT link_type, alias FROM link_type_alias_embed_queue ORDER BY id"
    ).fetchall()
    assert [(row["link_type"], row["alias"]) for row in queued] == [
        ("cases", "is high for"),
        ("cases", "is low for"),
        ("cases", "is medium for"),
        ("cases", "is extra high for"),
        ("cases", "is none for"),
        ("cases", "is positive for"),
        ("cases", "is negative for"),
    ]

    empty = _v9_alias_conn()
    migrations._migration_v12_cases_level_aliases(empty)
    assert empty.execute("SELECT COUNT(*) FROM link_type_aliases").fetchone()[0] == 0
    assert (
        empty.execute("SELECT COUNT(*) FROM link_type_alias_embed_queue").fetchone()[0]
        == 0
    )


def test_templated_cue_slots_take_forward_aliases_only(fresh_conn):
    store.upsert_link_type_alias(
        fresh_conn, "contains", "belongs to", direction="reverse"
    )

    grouped = store.aliases_by_type(fresh_conn)

    assert "belongs to" not in grouped.get("contains", ())
    assert "is part of" not in grouped.get("contains", ())
    assert "includes" in grouped["contains"]


def test_migrate_sets_alias_schema_version(fresh_conn):
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 12
    assert migrations.CURRENT_VERSION == 12


def test_carrier_embedding_drain_round_trips_and_skips_deleted_target(fresh_conn):
    seen: list[str] = []

    def fake_embed(text: str) -> list[float]:
        seen.append(text)
        return [float(len(text)), float(sum(text.encode()) % 101), 1.25]

    expected = store.count_open_alias_embeddings(fresh_conn)
    assert aliases.carrier_text("then") == "X then Y"
    assert (
        aliases.drain_alias_embeddings(fresh_conn, embed_text=fake_embed, chunk=7)
        == expected
    )
    assert store.count_open_alias_embeddings(fresh_conn) == 0
    assert "X then Y" in seen
    assert all(text.startswith("X ") and text.endswith(" Y") for text in seen)

    loaded = aliases.alias_vectors(fresh_conn)
    then = next(
        row for row in loaded if row.link_type == "proceeds" and row.alias == "then"
    )
    assert np.array_equal(
        then.vector,
        np.asarray(fake_embed("X then Y"), dtype=np.float32),
    )
    assert aliases.drain_alias_embeddings(fresh_conn, embed_text=fake_embed) == 0

    store.upsert_link_type_alias(fresh_conn, "vanishing", "gone soon")
    fresh_conn.execute(
        "DELETE FROM link_type_aliases WHERE link_type = ? AND alias = ?",
        ("vanishing", "gone soon"),
    )
    assert aliases.drain_alias_embeddings(fresh_conn, embed_text=fake_embed) == 0
    assert store.count_open_alias_embeddings(fresh_conn) == 0


def test_nearest_aliases_orders_by_cosine_and_handles_zero_vectors():
    vectors = [
        aliases.AliasVector("zeta", "same", np.asarray([1.0, 0.0])),
        aliases.AliasVector("alpha", "same", np.asarray([1.0, 0.0])),
        aliases.AliasVector("middle", "orthogonal", np.asarray([0.0, 1.0])),
        aliases.AliasVector("zero", "empty", np.asarray([0.0, 0.0])),
    ]

    nearest = aliases.nearest_aliases(np.asarray([1.0, 0.0]), vectors)
    assert [(link_type, alias) for link_type, alias, _score in nearest] == [
        ("alpha", "same"),
        ("zeta", "same"),
        ("middle", "orthogonal"),
        ("zero", "empty"),
    ]
    assert [score for _type, _alias, score in nearest] == [1.0, 1.0, 0.0, 0.0]

    zero_query = aliases.nearest_aliases(np.asarray([0.0, 0.0]), vectors)
    assert all(score == 0.0 for _type, _alias, score in zero_query)
    assert [(link_type, alias) for link_type, alias, _score in zero_query] == sorted(
        (row.link_type, row.alias) for row in vectors
    )


def test_alias_worker_drain_uses_embed_client(fresh_conn, monkeypatch):
    seen: list[str] = []

    def fake_embed(text: str) -> list[float]:
        seen.append(text)
        return [1.0, 2.0, 3.0]

    monkeypatch.setattr(embed, "embed", fake_embed)
    expected = store.count_open_alias_embeddings(fresh_conn)
    assert alias_worker.drain(fresh_conn, chunk=9) == expected
    assert len(seen) == expected
    assert store.count_open_alias_embeddings(fresh_conn) == 0


def test_failed_drain_reopens_its_claimed_jobs(fresh_conn, monkeypatch):
    def unavailable_embed(text: str) -> list[float]:
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(embed, "embed", unavailable_embed)
    open_before = store.count_open_alias_embeddings(fresh_conn)

    with pytest.raises(RuntimeError):
        alias_worker.drain(fresh_conn, chunk=5)
    assert store.count_open_alias_embeddings(fresh_conn) < open_before

    alias_worker._reopen_claimed(fresh_conn)
    assert store.count_open_alias_embeddings(fresh_conn) == open_before


def test_stop_keeps_a_slow_worker_and_start_refuses_a_second(
    tmp_path, monkeypatch, caplog
):
    """A join that times out must not orphan the running worker.

    Clearing `_thread` there would let the next `start` run a second worker
    beside the first; both reset claims on the same queue.
    """
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    conn.close()

    entered = threading.Event()
    release = threading.Event()

    def blocking_drain(_conn, *, chunk: int = alias_worker.CHUNK) -> int:
        entered.set()
        release.wait(10.0)
        return 0

    monkeypatch.setattr(alias_worker, "drain", blocking_drain)
    try:
        alias_worker.start(tmp_path)
        worker = alias_worker._thread
        assert entered.wait(10.0)

        with caplog.at_level(logging.WARNING, logger="mycelium.alias_worker"):
            alias_worker.stop(timeout=0.05)
        assert "did not stop" in caplog.text
        assert alias_worker._thread is worker
        assert worker.is_alive()

        alias_worker.start(tmp_path)
        assert alias_worker._thread is worker
    finally:
        release.set()
        alias_worker.stop(timeout=10.0)
    assert alias_worker._thread is None


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


def test_complete_alias_vectors_waits_for_the_last_embedding(fresh_conn):
    assert store.complete_alias_vectors(fresh_conn) == []

    aliases.drain_alias_embeddings(
        fresh_conn,
        embed_text=lambda text: [float(len(text))] * 4,
        chunk=200,
    )
    seeded = len(store.list_link_type_aliases(fresh_conn))
    assert len(store.complete_alias_vectors(fresh_conn)) == seeded

    with store.transaction(fresh_conn):
        store.upsert_link_type_alias(fresh_conn, "proceeds", "then after")

    # One alias added and not yet drained hides every other alias too.
    assert store.complete_alias_vectors(fresh_conn) == []
