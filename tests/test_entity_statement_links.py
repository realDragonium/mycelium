"""Mixed-endpoint links between entities and statements.

The new `entity_statement_links` table is exposed through the same
`add_links` / `remove_links` tools that handle statement↔statement edges
— externally there's no difference between the two flavors. These tests
cover the routing, the `when` round-trip, cascade on delete, and the
merge plumbing on both sides (entity and statement).
"""

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


# ─── routing ───────────────────────────────────────────────────────────────


def test_entity_to_statement_link_round_trips(tmp_path, monkeypatch):
    """An entity→statement edge goes in through `add_links` and surfaces
    in `get_entity.statement_links` and `get_statements.incoming_links`."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "the recruiter submits an invite")
        r = client.post(
            "/add-links",
            json={"links": [{"from_id": e, "to_id": s, "link_type": "performs"}]},
        ).json()
        assert r == {"inserted": 1}

        ent = client.post("/get-entity", json={"id": e}).json()
        assert ent["statement_links"] == [{"to_id": s, "link_type": "performs"}]
        assert ent["incoming_statement_links"] == []

        stm = client.post("/get-statements", json={"ids": [s]}).json()["statements"][0]
        assert stm["incoming_links"] == [{"from_id": e, "link_type": "performs"}]
        assert stm["links"] == []


def test_statement_to_entity_link_round_trips(tmp_path, monkeypatch):
    """A statement→entity edge surfaces on `get_statements.links` and on
    `get_entity.incoming_statement_links`."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Invite")
        s = _stmt(client, "the system mints a token")
        r = client.post(
            "/add-links",
            json={"links": [{"from_id": s, "to_id": e, "link_type": "produces"}]},
        ).json()
        assert r == {"inserted": 1}

        stm = client.post("/get-statements", json={"ids": [s]}).json()["statements"][0]
        assert stm["links"] == [{"to_id": e, "link_type": "produces"}]

        ent = client.post("/get-entity", json={"id": e}).json()
        assert ent["incoming_statement_links"] == [
            {"from_id": s, "link_type": "produces"}
        ]


def test_add_links_routes_each_pair_to_the_right_table(tmp_path, monkeypatch):
    """Statement↔statement, entity→statement, and statement→entity edges
    can be added in a single call; counts add up across both tables."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "User")
        s1, s2 = _stmt(client, "alpha"), _stmt(client, "beta")
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": s1, "to_id": s2, "link_type": "triggers"},
                    {"from_id": e, "to_id": s1, "link_type": "performs"},
                    {"from_id": s2, "to_id": e, "link_type": "produces"},
                ]
            },
        ).json()
        assert r == {"inserted": 3}


def test_entity_to_entity_via_add_links_is_rejected(tmp_path, monkeypatch):
    """Entity↔entity edges have their own vocabulary and tool —
    `add_links` rejects them so the link-type namespaces stay clean."""
    with _client(tmp_path, monkeypatch) as client:
        e1, e2 = _entity(client, "User"), _entity(client, "Session")
        r = client.post(
            "/add-links",
            json={"links": [{"from_id": e1, "to_id": e2, "link_type": "contains"}]},
        )
        assert r.status_code == 400


# ─── when expressions ──────────────────────────────────────────────────────


def test_entity_statement_link_with_when_round_trips(tmp_path, monkeypatch):
    """The same `when` grammar that statement_links use is available on
    entity↔statement edges; the tree round-trips through hydration."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "an invite is sent")
        cond = _stmt(client, "the recruiter is signed in")

        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": e,
                        "to_id": s,
                        "link_type": "performs",
                        "when": {"statement_id": cond},
                    }
                ]
            },
        )

        ent = client.post("/get-entity", json={"id": e}).json()
        link = ent["statement_links"][0]
        assert link["when"] == {"statement_id": cond}


def test_when_references_includes_entity_statement_edges(tmp_path, monkeypatch):
    """A condition state on an entity↔statement edge surfaces in
    `get_statements.when_references` alongside statement-link refs."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "the recruiter submits an invite")
        cond = _stmt(client, "the recruiter is signed in")

        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": e,
                        "to_id": s,
                        "link_type": "performs",
                        "when": {"statement_id": cond},
                    }
                ]
            },
        )

        body = client.post("/get-statements", json={"ids": [cond]}).json()
        refs = body["statements"][0]["when_references"]
        assert refs == [
            {
                "from_id": e,
                "to_id": s,
                "link_type": "performs",
                "when": {"statement_id": cond},
            }
        ]


# ─── remove ────────────────────────────────────────────────────────────────


def test_remove_links_idempotent_across_kinds(tmp_path, monkeypatch):
    """remove_links on a mixed-endpoint edge is idempotent — the second
    call with the same payload removes zero rows."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "invite is sent")
        client.post(
            "/add-links",
            json={"links": [{"from_id": e, "to_id": s, "link_type": "performs"}]},
        )

        r = client.post(
            "/remove-links",
            json={"links": [{"from_id": e, "to_id": s, "link_type": "performs"}]},
        ).json()
        assert r == {"removed": 1}

        r = client.post(
            "/remove-links",
            json={"links": [{"from_id": e, "to_id": s, "link_type": "performs"}]},
        ).json()
        assert r == {"removed": 0}


# ─── cascade ───────────────────────────────────────────────────────────────


def test_delete_statement_cascades_entity_statement_links(tmp_path, monkeypatch):
    """When a statement is deleted, its mixed-endpoint edges go away —
    both endpoint-of and condition-leaf-of relationships."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "invite is sent")
        cond = _stmt(client, "recruiter is signed in")

        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": e,
                        "to_id": s,
                        "link_type": "performs",
                        "when": {"statement_id": cond},
                    }
                ]
            },
        )

        # Deleting `s` drops the edge (s is the endpoint).
        r = client.post("/delete-statement", json={"id": s}).json()
        assert r["entity_statement_links_removed"] >= 1
        ent = client.post("/get-entity", json={"id": e}).json()
        assert ent["statement_links"] == []


def test_delete_statement_used_as_when_leaf_drops_entity_statement_link(
    tmp_path, monkeypatch
):
    """Deleting the statement referenced in a `when` leaf of an
    entity↔statement edge removes the edge — same cascade as
    statement_links."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s = _stmt(client, "invite is sent")
        cond = _stmt(client, "recruiter is signed in")

        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": e,
                        "to_id": s,
                        "link_type": "performs",
                        "when": {"statement_id": cond},
                    }
                ]
            },
        )

        client.post("/delete-statement", json={"id": cond})
        ent = client.post("/get-entity", json={"id": e}).json()
        assert ent["statement_links"] == []


def test_delete_entity_cascades_entity_statement_links(tmp_path, monkeypatch):
    """Deleting an entity removes every entity↔statement edge anchored
    on it — both directions."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s1, s2 = _stmt(client, "alpha"), _stmt(client, "beta")

        client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": e, "to_id": s1, "link_type": "performs"},
                    {"from_id": s2, "to_id": e, "link_type": "produces"},
                ]
            },
        )

        r = client.post("/delete-entity", json={"id": e}).json()
        assert r["entity_statement_links_removed"] == 2

        stm = client.post("/get-statements", json={"ids": [s1, s2]}).json()
        assert all(b["incoming_links"] == [] for b in stm["statements"])
        assert all(b["links"] == [] for b in stm["statements"])


# ─── merge ─────────────────────────────────────────────────────────────────


def test_merge_entities_rewrites_entity_statement_links(tmp_path, monkeypatch):
    """Mixed-endpoint edges anchored on the source entity move onto the
    target entity in a merge."""
    with _client(tmp_path, monkeypatch) as client:
        source = _entity(client, "Login")
        target = _entity(client, "Sign-in")
        s = _stmt(client, "the user signs in")

        client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": source, "to_id": s, "link_type": "performs"},
                ]
            },
        )

        client.post(
            "/merge-entities",
            json={
                "from_entity_id": source,
                "into_entity_id": target,
            },
        )

        ent = client.post("/get-entity", json={"id": target}).json()
        assert ent["statement_links"] == [{"to_id": s, "link_type": "performs"}]


def test_merge_statements_rewrites_entity_statement_link_endpoint(
    tmp_path, monkeypatch
):
    """Merging a source statement into a target moves any mixed-endpoint
    edges that pointed at the source onto the target."""
    with _client(tmp_path, monkeypatch) as client:
        e = _entity(client, "Recruiter")
        s_source = _stmt(client, "draft of the invite event")
        s_target = _stmt(client, "the recruiter submits an invite")

        client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": e, "to_id": s_source, "link_type": "performs"},
                ]
            },
        )

        client.post(
            "/merge-statements",
            json={
                "from_id": s_source,
                "into_id": s_target,
            },
        )

        ent = client.post("/get-entity", json={"id": e}).json()
        assert ent["statement_links"] == [{"to_id": s_target, "link_type": "performs"}]
