from __future__ import annotations

import contextlib
import zlib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from mycelium import embed, phrasing, server, store
from mycelium.server import indexes, runtime


def _vector(text: str) -> list[float]:
    seed = zlib.crc32(text.casefold().encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


def _init(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed", _vector)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    store.reset_substrate()
    runtime._ctx = None
    server.init(data_dir)


def _outage(text: str) -> list[float]:
    raise embed.EmbeddingError("embedding provider down")


def test_statement_search_keyword_fallback_ranks_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    server.upsert_entity("Invoice", "A workspace invoice")
    best = server.upsert_statement(
        kind="state",
        text="Workspace invoice exports include invoice line items",
        links=[],
    )["statement_id"]
    second = server.upsert_statement(
        kind="state", text="Workspace exports are available", links=[]
    )["statement_id"]
    server.upsert_statement(
        kind="event", text="Workspace invoice exports finish", links=[]
    )
    monkeypatch.setattr(embed, "embed", _outage)

    hits = server.search_statements(
        "workspace invoice exports", kind="state", name_boost=0.0
    )

    assert [hit["id"] for hit in hits[:2]] == [best, second]
    assert all(hit["kind"] == "state" for hit in hits)
    assert all(hit["retrieval"] == "keyword" for hit in hits)
    assert hits[0]["score"] == 1.0
    assert hits[1]["score"] == pytest.approx(2 / 3)
    mentioned = server.search_statements(
        "workspace exports", kind="state", mentions=["Invoice"], name_boost=0.0
    )
    assert [hit["id"] for hit in mentioned] == [best]


def test_entity_search_falls_back_to_keywords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    entity_id = server.upsert_entity("Workspace Login", "A login surface")["entity_id"]
    monkeypatch.setattr(embed, "embed", _outage)

    entities = server.search_entities("workspace", k=5)["entities"]
    exact_entities = server.search_entities("workspace login", k=5)["entities"]

    assert entities == [
        {
            "id": entity_id,
            "name": "Workspace Login",
            "matched_name": "Workspace Login",
            "score": 0.5,
            "description": "A login surface",
            "retrieval": "keyword",
        }
    ]
    assert exact_entities[0]["score"] == 1.0


def test_pending_statement_is_reembedded_after_provider_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(embed, "embed", _outage)

    response = server.upsert_statement(
        kind="state", text="Invoice exports are ready", links=[]
    )
    statement_id = response["statement_id"]

    assert response["embedding_pending"] is True
    assert response["near_duplicates"] == []
    assert store.get_vector_id(store.substrate_connection(), statement_id) is None

    monkeypatch.setattr(embed, "embed", _vector)
    assert indexes.reembed_pending() == 1
    assert store.get_vector_id(store.substrate_connection(), statement_id) is not None
    hits = server.search_statements("Invoice exports are ready", name_boost=0.0)
    assert hits[0]["id"] == statement_id
    assert "retrieval" not in hits[0]


def test_replace_text_outage_removes_stale_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    statement_id = server.upsert_statement(
        kind="state", text="Workspace login uses the old form", links=[]
    )["statement_id"]
    monkeypatch.setattr(embed, "embed", _outage)

    response = server.replace_text(statement_id, "Workspace login uses SSO")

    assert response["embedding_pending"] is True
    assert store.get_vector_id(store.substrate_connection(), statement_id) is None
    monkeypatch.setattr(embed, "embed", _vector)
    hits = server.search_statements("Workspace login uses the old form")
    assert statement_id not in {hit["id"] for hit in hits}


def test_pending_name_is_reembedded_after_provider_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(embed, "embed", _outage)

    entity_id = server.upsert_entity("Invoice Archive", "Stored invoices")["entity_id"]
    name = store.get_names_by_entity(store.substrate_connection(), entity_id)[0]
    assert store.get_name_vector_id(store.substrate_connection(), name["id"]) is None

    monkeypatch.setattr(embed, "embed", _vector)
    assert indexes.reembed_pending() >= 1
    assert (
        store.get_name_vector_id(store.substrate_connection(), name["id"]) is not None
    )


def test_reembed_pending_skips_text_changed_during_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(embed, "embed", _outage)
    statement_id = server.upsert_statement(
        kind="state", text="Exports use the current invoice format", links=[]
    )["statement_id"]

    monkeypatch.setattr(
        embed, "embed_many", lambda texts: [_vector(text) for text in texts]
    )
    persisted_index_write = indexes._persisted_index_write

    @contextlib.contextmanager
    def changing_write(
        *, statements: bool = False, names: bool = False
    ) -> Iterator[None]:
        with persisted_index_write(statements=statements, names=names):
            store.update_statement_text(
                store.substrate_connection(),
                statement_id,
                "Exports use the revised invoice format",
            )
            yield

    monkeypatch.setattr(indexes, "_persisted_index_write", changing_write)

    assert indexes.reembed_pending() == 0
    assert store.get_vector_id(store.substrate_connection(), statement_id) is None


def test_a_row_that_fails_alone_is_passed_over_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycelium import automation_stops, embedding_worker, product_settings
    from product_settings_helpers import set_product

    _init(tmp_path, monkeypatch)
    set_product(product_settings.AutomationSettings(embedding_retries=0))
    monkeypatch.setattr(embed, "embed", _outage)
    ids = [
        server.upsert_statement(kind="state", text=text, links=[])["statement_id"]
        for text in (
            "Invoices export as CSV",
            "Workspace exports are rejected by the provider",
            "Single sign-on uses the workspace domain",
        )
    ]
    bad = ids[1]

    def embed_many(texts):
        if any("rejected" in text for text in texts):
            raise embed.EmbeddingError("input rejected")
        return [_vector(text) for text in texts]

    monkeypatch.setattr(embed, "embed_many", embed_many)
    state = embedding_worker.Isolation()
    conn = store.substrate_connection()
    for _ in range(4):
        embedding_worker.run_pass(state)

    assert [store.get_vector_id(conn, sid) is not None for sid in ids] == [
        True,
        False,
        True,
    ]
    [stop] = automation_stops.stops(conn)
    assert (stop.kind, stop.item_id) == ("embedding", f"statement:{bad}")
    assert indexes.pending(10) == []

    store.update_statement_text(conn, bad, "Workspace exports finish")
    conn.commit()
    assert [row.id for row in indexes.pending(10)] == [bad]


def test_an_outage_counts_against_no_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycelium import automation_stops, embedding_worker

    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(embed, "embed", _outage)
    for text in ("Invoices export as CSV", "Workspace exports finish"):
        server.upsert_statement(kind="state", text=text, links=[])
    monkeypatch.setattr(embed, "embed_many", _outage)
    state = embedding_worker.Isolation()

    for _ in range(5):
        embedding_worker.run_pass(state)

    assert automation_stops.stops(store.substrate_connection()) == []
    assert len(state.suspects) == 2
