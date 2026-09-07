"""Statement link authoring rejects entity endpoints atomically."""

from __future__ import annotations

import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, server, store


def _embed(text: str) -> list[float]:
    rng = np.random.default_rng(zlib.crc32(text.encode()) & 0xFFFFFFFF)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    server._ctx = None
    from mycelium.http import app

    return TestClient(app)


def _stmt(client, text):
    return client.post(
        "/upsert-statement",
        json={
            "kind": "event",
            "text": text,
            "mentions": [],
            "links": [],
            "allow_phrasing_violations": True,
        },
    ).json()["statement_id"]


def _entity(client, name):
    return client.post("/upsert-entity", json={"name": name, "description": ""}).json()[
        "entity_id"
    ]


def test_add_links_rejects_mixed_batch_before_any_mutation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "User")
        s1, s2 = _stmt(client, "alpha"), _stmt(client, "beta")
        first = client.post(
            "/add-links",
            json={"links": [{"from_id": s1, "to_id": s2, "link_type": "triggers"}]},
        )
        assert first.json() == {"inserted": 1}
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": s1, "to_id": s2, "link_type": "triggers"},
                    {"from_id": e, "to_id": s1, "link_type": "performs"},
                ]
            },
        )
        assert r.status_code == 400
        assert "statement-to-statement" in r.json()["detail"]
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) AS n FROM statement_links")
            .fetchone()["n"]
            == 1
        )


def test_every_entity_endpoint_via_add_links_is_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        e1, e2 = _entity(client, "User"), _entity(client, "Session")
        for edge in (
            {"from_id": e1, "to_id": e2, "link_type": "contains"},
            {"from_id": e1, "to_id": "stm_missing", "link_type": "performs"},
            {"from_id": "stm_missing", "to_id": e2, "link_type": "produces"},
        ):
            r = client.post("/add-links", json={"links": [edge]})
            assert r.status_code == 400
            assert "add_entity_links" in r.json()["detail"]
