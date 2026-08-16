from __future__ import annotations

import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mycelium import embed, server, store
from mycelium.connect.funnel import BatchStatement, find_candidates
from mycelium.connect.substrate import HintedView, LiveSubstrate


def word_embed(text: str) -> list[float]:
    vec = np.zeros(768, dtype=np.float32)
    for word in text.lower().split():
        vec[zlib.crc32(word.encode()) % 768] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm:
        vec /= norm
    return vec.tolist()


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", word_embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    server._ctx = None
    from mycelium.http import app  # local import: initialize after configuring data

    return TestClient(app)


def _upsert_statement(kind: str, text: str) -> str:
    result = server.upsert_statement(kind=kind, text=text, links=[])
    assert "statement_id" in result, result
    return result["statement_id"]


def test_live_substrate_wires_embeddings_index_mentions_and_store(
    tmp_path, monkeypatch
):
    with _client(tmp_path, monkeypatch):
        entity_id = server.upsert_entity(
            name="Cobalt Orchard", description="an account namespace"
        )["entity_id"]
        text_a = "a user submits the login form"
        statement_a = _upsert_statement("event", text_a)
        mentioning = _upsert_statement("state", "the Cobalt Orchard account is active")
        _upsert_statement("event", "the server creates a user session")

        view = LiveSubstrate()
        vec = word_embed(text_a)
        neighbours = view.neighbours(vec, 5)

        assert statement_a in {statement_id for statement_id, _ in neighbours}
        assert all(-1.0 <= score <= 1.0 for _, score in neighbours)
        assert [score for _, score in neighbours] == sorted(
            (score for _, score in neighbours), reverse=True
        )
        neighbour_score = dict(neighbours)[statement_a]
        assert view.similarity(vec, statement_a) == pytest.approx(
            neighbour_score, abs=1e-6
        )
        assert view.similarity(vec, "no-vector") is None

        assert entity_id in view.entities_in(
            "a request reaches the Cobalt Orchard account"
        )
        assert view.statements_sharing(frozenset({entity_id})) == {
            mentioning: frozenset({entity_id})
        }
        assert view.statements_sharing(frozenset()) == {}
        assert view.kind_of(statement_a) == "event"
        assert view.kind_of("nope") is None

        result = find_candidates(
            [BatchStatement(0, "event", "a user submits the login form")],
            LiveSubstrate(),
        )
        candidate = next(
            item for item in result.candidates if item.statement_id == statement_a
        )
        assert 0.6 <= candidate.score <= 1.0


def test_statements_sharing_entities_deduplicates_aliases_and_chunks():
    conn = store.connect(":memory:")
    store.migrate(conn)
    entity_id = store.create_entity(conn, "shared identity")
    first_name = store.create_name(conn, "Cobalt Orchard", entity_id)
    second_name = store.create_name(conn, "Orchard Account", entity_id)
    first_statement = store.create_statement(conn, "state", "first")
    second_statement = store.create_statement(conn, "state", "second")
    store.replace_mentions(conn, first_statement, [first_name, second_name])
    store.replace_mentions(conn, second_statement, [second_name])
    entity_ids = [entity_id, *(f"ent_fake_{index}" for index in range(500))]

    rows = store.statements_sharing_entities(conn, entity_ids)

    assert set(rows) == {
        (first_statement, entity_id),
        (second_statement, entity_id),
    }
    assert len(rows) == 2
    assert store.statements_sharing_entities(conn, []) == []


def test_live_substrate_reads_kind_link_matrix(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        view = LiveSubstrate()

        known = view.admissible_link_types("event", "state")
        glossary_types = {
            row["link_type"]
            for row in store.list_statement_link_type_glossary(server._db())
        }
        vocabulary = frozenset(
            glossary_types | set(store.list_link_types(server._db()))
        )

        assert known
        assert "establishes" in known
        assert "teaches" not in known
        assert view.admissible_link_types("widget", "state") == vocabulary


def test_statements_sharing_entities_never_scans_the_mention_table():
    """The funnel runs this lookup once per entity-bearing batch item, so a
    plan that scans every materialized mention would make ingest cost
    O(batch x substrate)."""
    conn = store.connect(":memory:")
    store.migrate(conn)

    plan = conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT DISTINCT sm.statement_id, n.entity_id "
        "FROM statement_mentions sm "
        "JOIN names n ON n.id = sm.name_id "
        "WHERE n.entity_id IN (?, ?)",
        ("ent_one", "ent_two"),
    ).fetchall()

    steps = [row["detail"] for row in plan]
    assert any("names_entity" in step for step in steps), steps
    assert not any(step.startswith("SCAN") for step in steps), steps


def test_hinted_view_widens_funnel_entity_candidates_without_persisting():
    text = "the account accepts a recovery code"

    class FakeView:
        def embed(self, value: str) -> list[float]:
            return [1.0]

        def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
            return []

        def similarity(self, vec: list[float], statement_id: str) -> float | None:
            return 0.7 if statement_id == "stm_x" else None

        def entities_in(self, value: str) -> frozenset[str]:
            return frozenset()

        def statements_sharing(
            self, entity_ids: frozenset[str]
        ) -> dict[str, frozenset[str]]:
            if entity_ids == frozenset({"e"}):
                return {"stm_x": frozenset({"e"})}
            return {}

        def kind_of(self, statement_id: str) -> str | None:
            return "state" if statement_id == "stm_x" else None

        def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
            return frozenset({"requires"})

    batch = [BatchStatement(0, "event", text)]
    base = FakeView()

    assert find_candidates(batch, base).candidates == []

    hinted = HintedView(base, {text: frozenset({"e"})})
    candidates = find_candidates(batch, hinted).candidates

    assert len(candidates) == 1
    assert candidates[0].new_index == 0
    assert candidates[0].statement_id == "stm_x"
    assert candidates[0].score == 0.7
    assert candidates[0].via == frozenset({"mention"})
    assert candidates[0].shared_entities == frozenset({"e"})
