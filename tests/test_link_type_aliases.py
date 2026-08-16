import numpy as np
import pytest

from mycelium import alias_worker, embed, migrations, store
from mycelium.connect import aliases


@pytest.fixture
def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


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

    assert store.alias_lookup(fresh_conn)["shared cue"] == frozenset({"alpha", "beta"})
    assert store.aliases_by_type(fresh_conn)["ordering"] == (
        "a much longer cue",
        "equal a",
        "equal b",
        "short",
    )


def test_list_aliases_filters_and_exposes_embedding_state(fresh_conn):
    rows = store.list_link_type_aliases(fresh_conn, "proceeds")
    assert rows
    assert {row["link_type"] for row in rows} == {"proceeds"}
    assert all(row["embedded"] == 0 for row in rows)


def test_migrate_sets_alias_schema_version(fresh_conn):
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert migrations.CURRENT_VERSION == 8


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
