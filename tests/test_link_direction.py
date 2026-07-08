from __future__ import annotations

import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, server
from mycelium.link_rules import flip_error


def _embed(text: str) -> list[float]:
    rng = np.random.default_rng(zlib.crc32(text.encode()) & 0xFFFFFFFF)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    server._conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None
    from mycelium.http import app

    return TestClient(app)


def _stmt(client: TestClient, kind: str, text: str) -> str:
    r = client.post(
        "/upsert-statement",
        json={
            "kind": kind,
            "text": text,
            "links": [],
            "allow_phrasing_violations": True,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["statement_id"]


def _entity(client: TestClient, name: str) -> str:
    r = client.post("/upsert-entity", json={"name": name, "description": ""})
    assert r.status_code == 200, r.text
    return r.json()["entity_id"]


def test_flip_error_detects_only_provable_flips():
    err = flip_error("teaches", "capability", "procedure")
    assert err is not None
    assert "swap" in err

    assert flip_error("teaches", "procedure", "capability") is None
    assert flip_error("unknown", "capability", "procedure") is None
    assert flip_error("contains", "capability", "procedure") is None
    assert flip_error("teaches", "event", "event") is None

    err = flip_error("accepts", "property", "event")
    assert err is not None
    assert "swap" in err


def test_flip_error_detects_target_only_constraint_flips():
    err = flip_error("establishes", "state", "event")
    assert err is not None
    assert "swap" in err
    assert flip_error("establishes", "event", "state") is None

    err = flip_error("valued-by", "rule", "property")
    assert err is not None
    assert "swap" in err
    assert flip_error("valued-by", "property", "rule") is None

    err = flip_error("governed-by", "rule", "procedure")
    assert err is not None
    assert "swap" in err
    assert flip_error("governed-by", "procedure", "rule") is None


def test_add_links_rejects_flipped_teaches_with_ids(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        capability = _stmt(client, "capability", "the user can export reports")
        procedure = _stmt(client, "procedure", "export reports")

        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": capability, "to_id": procedure, "link_type": "teaches"},
                ]
            },
        )

        assert r.status_code == 400
        detail = r.json()["detail"]
        assert capability in detail
        assert procedure in detail
        assert "swap" in detail


def test_add_links_accepts_correct_teaches_direction(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        capability = _stmt(client, "capability", "the user can import results")
        procedure = _stmt(client, "procedure", "import results")

        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": procedure, "to_id": capability, "link_type": "teaches"},
                ]
            },
        )

        assert r.status_code == 200
        assert r.json() == {"inserted": 1}


def test_add_links_rejects_flipped_batch_without_inserting_anything(
    tmp_path, monkeypatch
):
    with _client(tmp_path, monkeypatch) as client:
        capability = _stmt(client, "capability", "the admin can schedule sync")
        procedure = _stmt(client, "procedure", "schedule sync")
        a = _stmt(client, "event", "sync starts")
        b = _stmt(client, "event", "sync finishes")

        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": capability, "to_id": procedure, "link_type": "teaches"},
                    {"from_id": a, "to_id": b, "link_type": "contains"},
                ]
            },
        )

        assert r.status_code == 400
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert body["links"] == []


def test_upsert_statement_rejects_flipped_incoming_link(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        capability = _stmt(client, "capability", "the user can diagnose login")

        r = client.post(
            "/upsert-statement",
            json={
                "kind": "procedure",
                "text": "diagnose login",
                "links": [],
                "incoming_links": [
                    {"from_id": capability, "link_type": "teaches"},
                ],
                "allow_phrasing_violations": True,
            },
        )

        assert r.status_code == 400
        assert "swap" in r.json()["detail"]


def test_upsert_statements_reports_flip_through_sibling_ref(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "capability",
                        "text": "the user can configure exports",
                        "links": [{"to_id": "@1", "link_type": "teaches"}],
                        "allow_phrasing_violations": True,
                    },
                    {
                        "kind": "procedure",
                        "text": "configure exports",
                        "links": [],
                        "allow_phrasing_violations": True,
                    },
                ]
            },
        )

        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["rejected"] is True
        assert "swap" in results[0]["errors"][0]
        assert results[1]["statement_id"].startswith("stm_")


def test_upsert_statements_cascades_rejection_from_flipped_sibling_ref(
    tmp_path, monkeypatch
):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "capability",
                        "text": "the user can configure notifications",
                        "links": [{"to_id": "@1", "link_type": "teaches"}],
                        "allow_phrasing_violations": True,
                    },
                    {
                        "kind": "procedure",
                        "text": "configure notifications",
                        "links": [],
                        "allow_phrasing_violations": True,
                    },
                    {
                        "kind": "event",
                        "text": "notification settings are reviewed",
                        "links": [{"to_id": "@0", "link_type": "contains"}],
                        "allow_phrasing_violations": True,
                    },
                ]
            },
        )

        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["rejected"] is True
        assert "swap" in results[0]["errors"][0]

        survivor_id = results[1]["statement_id"]
        assert survivor_id.startswith("stm_")

        assert results[2] == {
            "rejected": True,
            "reason": "depends_on_rejected",
            "depends_on": [0],
        }
        assert "statement_id" not in results[2]

        listed = client.post("/list-statements", json={}).json()
        assert listed["total"] == 1
        assert listed["statements"] == [
            {
                "id": survivor_id,
                "kind": "procedure",
                "text": "configure notifications",
            },
        ]


def test_upsert_statement_kind_change_uses_new_kind_for_flip_check(
    tmp_path, monkeypatch
):
    with _client(tmp_path, monkeypatch) as client:
        capability = _stmt(client, "capability", "the user can rotate keys")
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "procedure",
                "text": "rotate keys",
                "links": [{"to_id": capability, "link_type": "teaches"}],
                "allow_phrasing_violations": True,
            },
        )
        assert r.status_code == 200, r.text
        procedure = r.json()["statement_id"]

        r = client.post(
            "/upsert-statement",
            json={
                "id": capability,
                "kind": "procedure",
                "text": "prepare key rotation",
                "links": [],
                "allow_phrasing_violations": True,
            },
        )
        assert r.status_code == 200, r.text

        r = client.post(
            "/upsert-statement",
            json={
                "id": procedure,
                "kind": "capability",
                "text": "the user can rotate keys",
                "links": [{"to_id": capability, "link_type": "teaches"}],
                "allow_phrasing_violations": True,
            },
        )

        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "swap" in detail
        assert procedure in detail
        assert capability in detail


def test_upsert_statement_accepts_unconstrained_self_link(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        statement_id = _stmt(client, "event", "the workflow records itself")

        r = client.post(
            "/upsert-statement",
            json={
                "id": statement_id,
                "kind": "event",
                "text": "the workflow records itself",
                "links": [{"to_id": statement_id, "link_type": "contains"}],
                "allow_phrasing_violations": True,
            },
        )

        assert r.status_code == 200, r.text
        assert r.json()["statement_id"] == statement_id

        body = client.post(
            "/get-statements",
            json={"ids": [statement_id]},
        ).json()["statements"][0]
        assert body["links"] == [
            {"to_id": statement_id, "link_type": "contains"},
        ]


def test_entity_touching_edges_are_not_direction_checked(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        prop = _stmt(client, "property", "Export format")
        entity = _entity(client, "Report")

        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": prop, "to_id": entity, "link_type": "accepts"},
                ]
            },
        )

        assert r.status_code == 200
        assert r.json() == {"inserted": 1}


def test_contains_between_events_is_unaffected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _stmt(client, "event", "the workflow starts")
        b = _stmt(client, "event", "the workflow continues")

        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": b, "link_type": "contains"},
                ]
            },
        )

        assert r.status_code == 200
        assert r.json() == {"inserted": 1}


def test_list_link_types_includes_teaches_direction(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        rows = client.post("/list-link-types", json={}).json()
        teaches = next(row for row in rows if row["link_type"] == "teaches")
        assert teaches["direction"]["source_kinds"] == ["procedure"]


def test_plan_batch_decides_flip_and_cascade_without_writing(monkeypatch):
    """`_plan_batch` is pure planning: it computes the flip/cascade decision
    from the input and read-only lookups, no embedding or write transaction.
    A `capability --teaches--> procedure` edge flips (procedure teaches
    capability), so item 0 is rejected; item 2 references @0 and cascades."""
    from mycelium import store

    conn = store.connect(":memory:")
    store.migrate(conn)
    monkeypatch.setattr(server, "_conn", conn)

    plan = server._plan_batch(
        [
            {
                "kind": "capability",
                "text": "the user can configure notifications",
                "links": [{"to_id": "@1", "link_type": "teaches"}],
                "allow_phrasing_violations": True,
            },
            {
                "kind": "procedure",
                "text": "configure notifications",
                "links": [],
                "allow_phrasing_violations": True,
            },
            {
                "kind": "event",
                "text": "notification settings are reviewed",
                "links": [{"to_id": "@0", "link_type": "contains"}],
                "allow_phrasing_violations": True,
            },
        ]
    )

    assert plan.item_errors[0] and "swap" in plan.item_errors[0][0]
    assert plan.rejected == {0, 2}
    assert 0 in plan.direct_rejected  # flip promotes to a direct rejection
    assert 1 not in plan.rejected  # the procedure survives
    assert plan.cascade_reasons[2] == [0]
