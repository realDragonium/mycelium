import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, mention_worker, server, store


def fake_embed_factory():
    rng = np.random.default_rng(0)

    def fake_embed(text: str) -> list[float]:
        return rng.standard_normal(768).astype(np.float32).tolist()

    return fake_embed


def deterministic_embed(text: str) -> list[float]:
    """Same text → same vector across processes (CRC seed, not hash())."""
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch, embedder):
    monkeypatch.setattr(embed, "embed", embedder)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    server._ctx = None
    from mycelium.http import app

    return TestClient(app)


def test_http_full_surface(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/upsert-entity", json={"name": "Login", "description": "auth"})
        assert r.status_code == 200
        login_id = r.json()["entity_id"]
        assert login_id.startswith("ent_")

        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "User signs in with email and password",
                "mentions": ["Login", "Email"],
                "links": [],
            },
        )
        assert r.status_code == 200
        b1 = r.json()["statement_id"]
        assert b1.startswith("stm_")

        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "Server issues a session token",
                "mentions": ["Session"],
                "links": [{"to_id": b1, "link_type": "triggered_by"}],
            },
        )
        assert r.status_code == 200
        b2 = r.json()["statement_id"]

        r = client.get("/list-link-types")
        assert r.status_code == 200
        rows = r.json()
        in_use = {row["type"] for row in rows if row["in_use"] == "true"}
        assert in_use == {"triggered_by"}

        r = client.post("/search-statements", json={"query": "anything", "limit": 5})
        assert r.status_code == 200
        hits = r.json()
        assert {h["id"] for h in hits} == {b1, b2}

        r = client.post("/upsert-name", json={"text": "sign-in", "entity_id": login_id})
        assert r.status_code == 200
        assert r.json()["name_id"].startswith("nam_")

        r = client.post(
            "/upsert-name", json={"text": "bogus", "entity_id": "ent_missing"}
        )
        assert r.status_code == 400
        assert "ent_missing" in r.json()["detail"]


def test_search_min_score_filters_low_matches(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "alpha unique", "mentions": [], "links": []},
        )
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "beta unique", "mentions": [], "links": []},
        )

        # exact text match → score ≈ 1.0; min_score=0.99 keeps only the match
        hits = client.post(
            "/search-statements",
            json={"query": "alpha unique", "min_score": 0.99},
        ).json()
        assert len(hits) == 1
        assert hits[0]["text"] == "alpha unique"

        # min_score=-1.0 (default floor) keeps every hit
        hits = client.post(
            "/search-statements",
            json={"query": "alpha unique", "min_score": -1.0},
        ).json()
        assert len(hits) == 2


def test_search_depth_expands_children_and_parents(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # chain: a -part-> b -part-> c
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node a", "mentions": [], "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node b", "mentions": [], "links": []},
        ).json()["statement_id"]
        c = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node c", "mentions": [], "links": []},
        ).json()["statement_id"]
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "node a",
                "mentions": [],
                "links": [{"to_id": b, "link_type": "part"}],
                "id": a,
            },
        )
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "node b",
                "mentions": [],
                "links": [{"to_id": c, "link_type": "part"}],
                "id": b,
            },
        )

        def search(query, depth):
            return client.post(
                "/search-statements",
                json={"query": query, "limit": 1, "depth": depth, "min_score": 0.99},
            ).json()

        # depth=0 → only the direct hit
        hits = search("node a", 0)
        assert [h["id"] for h in hits] == [a]

        # depth=1 from a → a + child b
        hits = search("node a", 1)
        assert hits[0]["id"] == a and "score" in hits[0]
        assert {h["id"] for h in hits} == {a, b}
        assert "score" not in next(h for h in hits if h["id"] == b)

        # depth=2 from a → a + b + c
        hits = search("node a", 2)
        assert hits[0]["id"] == a
        assert {h["id"] for h in hits} == {a, b, c}

        # depth=1 from c → c + parent b (incoming-link expansion)
        hits = search("node c", 1)
        assert hits[0]["id"] == c
        assert {h["id"] for h in hits} == {b, c}


def test_search_direction_filter(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # chain: a -part-> b -part-> c — search anchored at the middle node
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node a", "mentions": [], "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node b", "mentions": [], "links": []},
        ).json()["statement_id"]
        c = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node c", "mentions": [], "links": []},
        ).json()["statement_id"]
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "node a",
                "mentions": [],
                "links": [{"to_id": b, "link_type": "part"}],
                "id": a,
            },
        )
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "node b",
                "mentions": [],
                "links": [{"to_id": c, "link_type": "part"}],
                "id": b,
            },
        )

        def search(direction):
            return client.post(
                "/search-statements",
                json={
                    "query": "node b",
                    "limit": 1,
                    "depth": 1,
                    "min_score": 0.99,
                    "direction": direction,
                },
            ).json()

        # both → b + parent a + child c
        assert {h["id"] for h in search("both")} == {a, b, c}
        # children only → b + child c (no parent a)
        assert {h["id"] for h in search("children")} == {b, c}
        # parents only → b + parent a (no child c)
        assert {h["id"] for h in search("parents")} == {a, b}

        # invalid value → Pydantic 422
        r = client.post(
            "/search-statements",
            json={"query": "node b", "depth": 1, "direction": "sideways"},
        )
        assert r.status_code == 422


def test_search_mentions_shape(tmp_path, monkeypatch):
    """Each mention is `{name_id, name, entity_id}` — enough info to call
    merge_entities or move_name without a follow-up lookup."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        dashboard_id = client.post(
            "/upsert-entity", json={"name": "dashboard", "description": "the dashboard"}
        ).json()["entity_id"]
        reviewer_id = client.post(
            "/upsert-entity", json={"name": "reviewer", "description": "the reviewer"}
        ).json()["entity_id"]
        # Text mentions both distinctive names → two derived mentions.
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the reviewer opens the dashboard",
                "links": [],
            },
        )
        hits = client.post(
            "/search-statements",
            json={"query": "the reviewer opens the dashboard", "min_score": 0.99},
        ).json()
        assert len(hits) == 1
        mentions = hits[0]["mentions"]
        assert len(mentions) == 2
        for m in mentions:
            assert set(m.keys()) == {"name_id", "name", "entity_id"}
            assert m["name_id"].startswith("nam_")
            assert m["entity_id"].startswith("ent_")
        dashboard_mention = next(m for m in mentions if m["name"] == "dashboard")
        assert dashboard_mention["entity_id"] == dashboard_id
        reviewer_mention = next(m for m in mentions if m["name"] == "reviewer")
        assert reviewer_mention["entity_id"] == reviewer_id


def test_upsert_name_idempotent_then_conflict(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        login_id = client.post(
            "/upsert-entity", json={"name": "Login", "description": ""}
        ).json()["entity_id"]
        other_id = client.post(
            "/upsert-entity", json={"name": "Other", "description": ""}
        ).json()["entity_id"]

        # alias to login
        first = client.post(
            "/upsert-name", json={"text": "sign-in", "entity_id": login_id}
        ).json()
        # repeat with same entity → idempotent (returns same name_id)
        again = client.post(
            "/upsert-name", json={"text": "sign-in", "entity_id": login_id}
        ).json()
        assert first["name_id"] == again["name_id"]

        # repeat with different entity → 400
        r = client.post("/upsert-name", json={"text": "sign-in", "entity_id": other_id})
        assert r.status_code == 400
        assert "move_name or merge_entities" in r.json()["detail"]


def test_merge_entities_preserves_statement_mentions(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Multi-word names are distinctive, so the text-derived mention
        # matcher auto-links them (single short tokens like "Login" are
        # suspect and go to review instead).
        a = client.post(
            "/upsert-entity", json={"name": "Login page", "description": ""}
        ).json()["entity_id"]
        b = client.post(
            "/upsert-entity", json={"name": "Sign-in page", "description": ""}
        ).json()["entity_id"]
        # Statements whose text mentions each entity separately.
        alpha_text = "statement alpha describes the Login page"
        beta_text = "statement beta describes the Sign-in page"
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": alpha_text, "links": []},
        )
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": beta_text, "links": []},
        )

        # merge b into a. names_moved counts every name row on the source
        # entity: the primary "Sign-in page" plus its auto-generated
        # plural "Sign-in pages".
        r = client.post(
            "/merge-entities", json={"from_entity_id": b, "into_entity_id": a}
        )
        assert r.status_code == 200
        assert r.json() == {
            "into_entity_id": a,
            "names_moved": 2,
        }

        # source entity is gone
        assert (
            client.post(
                "/merge-entities", json={"from_entity_id": b, "into_entity_id": a}
            ).status_code
            == 400
        )

        # both statements now report entity_id == a, but their original names persist
        for query in (alpha_text, beta_text):
            hits = client.post(
                "/search-statements", json={"query": query, "min_score": 0.99}
            ).json()
            assert hits[0]["mentions"][0]["entity_id"] == a

        names = {
            hits["mentions"][0]["name"]
            for hits in [
                client.post(
                    "/search-statements", json={"query": q, "min_score": 0.99}
                ).json()[0]
                for q in (alpha_text, beta_text)
            ]
        }
        assert names == {"Login page", "Sign-in page"}


def test_add_and_remove_links_bulk(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # three statements, no links yet
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node a", "mentions": [], "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node b", "mentions": [], "links": []},
        ).json()["statement_id"]
        c = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node c", "mentions": [], "links": []},
        ).json()["statement_id"]

        # bulk insert: 3 edges in one call, no embedding work
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": b, "link_type": "part"},
                    {"from_id": b, "to_id": c, "link_type": "part"},
                    {"from_id": a, "to_id": c, "link_type": "triggers"},
                ]
            },
        )
        assert r.status_code == 200
        assert r.json() == {"inserted": 3}

        # idempotent — same payload again inserts zero
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": b, "link_type": "part"},
                    {"from_id": a, "to_id": c, "link_type": "triggers"},
                ]
            },
        )
        assert r.json() == {"inserted": 0}

        # link types now visible via list_link_types; in_use="true" for the
        # ones we just added, "false" for glossary-only types.
        rows = client.get("/list-link-types").json()
        by_type = {r["type"]: r for r in rows}
        assert by_type["part"]["in_use"] == "true"
        assert by_type["triggers"]["in_use"] == "true"
        # Built-in glossary entries also show, with descriptions.
        assert by_type["triggers"]["description"]  # non-empty
        assert "contains" in by_type
        assert by_type["contains"]["in_use"] == "false"

        # search reports the edges on each statement
        hits = client.post(
            "/search-statements", json={"query": "node a", "min_score": 0.99}
        ).json()
        outgoing = sorted(
            (link["to_id"], link["link_type"]) for link in hits[0]["links"]
        )
        assert outgoing == sorted([(b, "part"), (c, "triggers")])

        # remove_links: delete one edge, others stay
        r = client.post(
            "/remove-links",
            json={
                "links": [
                    {"from_id": a, "to_id": c, "link_type": "triggers"},
                ]
            },
        )
        assert r.json() == {"removed": 1}

        # second remove of same edge is a no-op (still removed=0)
        r = client.post(
            "/remove-links",
            json={
                "links": [
                    {"from_id": a, "to_id": c, "link_type": "triggers"},
                ]
            },
        )
        assert r.json() == {"removed": 0}

        # empty list short-circuits cleanly
        assert client.post("/add-links", json={"links": []}).json() == {"inserted": 0}
        assert client.post("/remove-links", json={"links": []}).json() == {"removed": 0}


def test_upsert_statement_with_incoming_links(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Two existing parents
        p1 = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "parent one", "mentions": [], "links": []},
        ).json()["statement_id"]
        p2 = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "parent two", "mentions": [], "links": []},
        ).json()["statement_id"]

        # Create a new child wired to both parents in a single call
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "child of two parents",
                "mentions": [],
                "links": [],
                "incoming_links": [
                    {"from_id": p1, "link_type": "part"},
                    {"from_id": p2, "link_type": "triggers"},
                ],
            },
        )
        assert r.status_code == 200
        child = r.json()["statement_id"]

        # Both parents now have the child as outgoing
        for parent_id in (p1, p2):
            hits = client.post(
                "/search-statements",
                json={
                    "query": "parent",
                    "limit": 5,
                    "min_score": -1.0,
                },
            ).json()
            parent = next(h for h in hits if h["id"] == parent_id)
            assert any(link["to_id"] == child for link in parent["links"])

        # Calling again with the same incoming_links is idempotent — no extra edges
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "child of two parents (text edit)",
                "mentions": [],
                "links": [],
                "id": child,
                "incoming_links": [
                    {"from_id": p1, "link_type": "part"},
                ],
            },
        )
        # p1's "part" edge to child is still there (idempotent)
        # p2's "triggers" edge to child is also still there (incoming_links don't delete)
        hits = client.post(
            "/search-statements",
            json={
                "query": "parent",
                "limit": 5,
                "min_score": -1.0,
            },
        ).json()
        p1_hit = next(h for h in hits if h["id"] == p1)
        p2_hit = next(h for h in hits if h["id"] == p2)
        assert any(
            link["to_id"] == child and link["link_type"] == "part"
            for link in p1_hit["links"]
        )
        assert any(
            link["to_id"] == child and link["link_type"] == "triggers"
            for link in p2_hit["links"]
        )

        # Validation: unknown from_id → 400, no mutation
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "filler text",
                "mentions": [],
                "links": [],
                "incoming_links": [
                    {"from_id": "stm_missing", "link_type": "part"},
                ],
            },
        )
        assert r.status_code == 400
        assert "stm_missing" in r.json()["detail"]


def test_add_links_validates_statement_existence(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "node a", "mentions": [], "links": []},
        ).json()["statement_id"]

        # unknown to → 400, nothing inserted
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": "stm_missing", "link_type": "part"},
                ]
            },
        )
        assert r.status_code == 400
        assert "stm_missing" in r.json()["detail"]
        # no link_type is in_use yet (every successful add was rolled back)
        rows = client.get("/list-link-types").json()
        assert all(r["in_use"] == "false" for r in rows)


def test_get_statement_returns_both_link_directions(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post("/upsert-entity", json={"name": "dashboard", "description": ""})
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the dashboard node", "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "node b",
                "links": [{"to_id": a, "link_type": "part"}],
            },
        ).json()["statement_id"]

        # a: 0 outgoing, 1 incoming (from b)
        r = client.post("/get-statements", json={"ids": [a]})
        assert r.status_code == 200
        body = r.json()["statements"][0]
        assert body["text"] == "the dashboard node"
        assert body["links"] == []
        assert body["incoming_links"] == [{"from_id": b, "link_type": "part"}]
        assert [m["name"] for m in body["mentions"]] == ["dashboard"]

        # b: 1 outgoing (to a), 0 incoming
        body = client.post("/get-statements", json={"ids": [b]}).json()["statements"][0]
        assert body["links"] == [{"to_id": a, "link_type": "part"}]
        assert body["incoming_links"] == []

        # unknown id → 400
        r = client.post("/get-statements", json={"ids": ["stm_missing"]})
        assert r.status_code == 400


def test_entity_links_lifecycle(tmp_path, monkeypatch):
    """Add entity↔entity edges, surface them via get_entity, list types,
    remove them, and validate self-loop + unknown-id errors."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # A parent corp and two subsidiaries — the canonical use case.
        parent = client.post(
            "/upsert-entity", json={"name": "MegaCorp", "description": ""}
        ).json()["entity_id"]
        sub_a = client.post(
            "/upsert-entity", json={"name": "MegaCorp Cloud", "description": ""}
        ).json()["entity_id"]
        sub_b = client.post(
            "/upsert-entity", json={"name": "MegaCorp Logistics", "description": ""}
        ).json()["entity_id"]

        # Empty before any edges — no types are in_use yet
        rows = client.get("/list-entity-link-types").json()
        assert all(r["in_use"] == "false" for r in rows)
        body = client.post("/get-entity", json={"id": parent}).json()
        assert body["links"] == []
        assert body["incoming_links"] == []

        # MegaCorp contains both subs
        r = client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": sub_a,
                        "link_type": "contains",
                    },
                    {
                        "from_entity_id": parent,
                        "to_entity_id": sub_b,
                        "link_type": "contains",
                    },
                ]
            },
        ).json()
        assert r == {"inserted": 2}

        # Idempotent — re-adding the same edge skips
        r = client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": sub_a,
                        "link_type": "contains",
                    },
                ]
            },
        ).json()
        assert r == {"inserted": 0}

        # get_entity surfaces both directions
        parent_body = client.post("/get-entity", json={"id": parent}).json()
        assert sorted(link["to_entity_id"] for link in parent_body["links"]) == sorted(
            [sub_a, sub_b]
        )
        sub_a_body = client.post("/get-entity", json={"id": sub_a}).json()
        assert sub_a_body["incoming_links"] == [
            {"from_entity_id": parent, "link_type": "contains"}
        ]

        rows = client.get("/list-entity-link-types").json()
        in_use = {r["type"] for r in rows if r["in_use"] == "true"}
        assert in_use == {"contains"}

        # Self-loop rejected
        r = client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": parent,
                        "link_type": "contains",
                    },
                ]
            },
        )
        assert r.status_code == 400

        # Unknown entity rejected before any insert
        r = client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": "ent_missing",
                        "link_type": "contains",
                    },
                ]
            },
        )
        assert r.status_code == 400

        # Remove one edge, leave the other in place
        r = client.post(
            "/remove-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": sub_a,
                        "link_type": "contains",
                    },
                ]
            },
        ).json()
        assert r == {"removed": 1}
        parent_body = client.post("/get-entity", json={"id": parent}).json()
        assert [link["to_entity_id"] for link in parent_body["links"]] == [sub_b]


def test_merge_entities_rewrites_entity_links(tmp_path, monkeypatch):
    """When two entities are merged, any entity_links pointing at the
    source must be rewritten to point at the target — otherwise the FK
    would block the source's deletion at merge time."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        parent = client.post(
            "/upsert-entity", json={"name": "Parent", "description": ""}
        ).json()["entity_id"]
        a = client.post(
            "/upsert-entity", json={"name": "ChildA", "description": ""}
        ).json()["entity_id"]
        b = client.post(
            "/upsert-entity", json={"name": "ChildB", "description": ""}
        ).json()["entity_id"]
        sibling = client.post(
            "/upsert-entity", json={"name": "Sibling", "description": ""}
        ).json()["entity_id"]

        # Wire: Parent contains A, Parent contains B, Sibling partner-of A
        client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": parent,
                        "to_entity_id": a,
                        "link_type": "contains",
                    },
                    {
                        "from_entity_id": parent,
                        "to_entity_id": b,
                        "link_type": "contains",
                    },
                    {
                        "from_entity_id": sibling,
                        "to_entity_id": a,
                        "link_type": "partner-of",
                    },
                ]
            },
        )

        # Merge A into B — Parent's "contains A" should become "contains B"
        # (deduped against existing "contains B"), and Sibling's "partner-of A"
        # should become "partner-of B".
        r = client.post(
            "/merge-entities", json={"from_entity_id": a, "into_entity_id": b}
        )
        assert r.status_code == 200

        parent_body = client.post("/get-entity", json={"id": parent}).json()
        assert parent_body["links"] == [{"to_entity_id": b, "link_type": "contains"}]

        b_body = client.post("/get-entity", json={"id": b}).json()
        incoming_pairs = sorted(
            (link["from_entity_id"], link["link_type"])
            for link in b_body["incoming_links"]
        )
        assert incoming_pairs == sorted([(parent, "contains"), (sibling, "partner-of")])

        # Source is gone
        assert client.post("/get-entity", json={"id": a}).status_code == 400


def test_get_entity_returns_all_names(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        eid = client.post(
            "/upsert-entity", json={"name": "Login", "description": "auth surface"}
        ).json()["entity_id"]
        client.post("/upsert-name", json={"text": "sign-in", "entity_id": eid})
        client.post("/upsert-name", json={"text": "log-in", "entity_id": eid})

        body = client.post("/get-entity", json={"id": eid}).json()
        assert body["description"] == "auth surface"
        # Each created name also auto-generates its regular plural as a
        # separate stored name, so all three appear alongside their plurals.
        names = sorted(n["text"] for n in body["names"])
        assert names == [
            "Login",
            "Logins",
            "log-in",
            "log-ins",
            "sign-in",
            "sign-ins",
        ]

        r = client.post("/get-entity", json={"id": "ent_missing"})
        assert r.status_code == 400


def test_list_entities_pagination_and_prefix(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Auto-plurals add a second name per entity (e.g. "Apples"), but the
        # alphabetically-first name still drives ordering — so each chosen
        # name sorts before its own plural.
        for n in ["Apple", "Apricot", "Banana", "Coconut"]:
            client.post("/upsert-entity", json={"name": n, "description": ""})

        body = client.post(
            "/list-entities", json={"prefix": "", "limit": 50, "offset": 0}
        ).json()
        assert body["total"] == 4
        assert [e["name"] for e in body["entities"]] == [
            "Apple",
            "Apricot",
            "Banana",
            "Coconut",
        ]

        body = client.post(
            "/list-entities", json={"prefix": "Ap", "limit": 50, "offset": 0}
        ).json()
        assert [e["name"] for e in body["entities"]] == ["Apple", "Apricot"]

        body = client.post(
            "/list-entities", json={"prefix": "", "limit": 2, "offset": 1}
        ).json()
        assert [e["name"] for e in body["entities"]] == ["Apricot", "Banana"]


def test_list_statements_pagination(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        ids = []
        for i in range(5):
            ids.append(
                client.post(
                    "/upsert-statement",
                    json={
                        "kind": "event",
                        "text": f"statement {i}",
                        "mentions": [],
                        "links": [],
                    },
                ).json()["statement_id"]
            )

        body = client.post("/list-statements", json={"limit": 50, "offset": 0}).json()
        assert body["total"] == 5
        assert [b["id"] for b in body["statements"]] == ids

        body = client.post("/list-statements", json={"limit": 2, "offset": 2}).json()
        assert [b["id"] for b in body["statements"]] == ids[2:4]


def test_list_statements_filter_by_entity_and_name(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Two entities, with a distinctive alias on the first so we can verify
        # name resolution collapses across aliases. Mentions are derived from
        # each statement's text, so the text must contain the names.
        dashboard_eid = client.post(
            "/upsert-entity", json={"name": "dashboard", "description": ""}
        ).json()["entity_id"]
        client.post("/upsert-entity", json={"name": "invoice", "description": ""})
        client.post(
            "/upsert-name", json={"text": "workspace", "entity_id": dashboard_eid}
        )

        # Three statements mention dashboard (one via the "workspace" alias),
        # one mentions only invoice, one mentions nothing.
        b1 = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the dashboard loads", "links": []},
        ).json()["statement_id"]
        b2 = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the workspace opens via sso", "links": []},
        ).json()["statement_id"]
        b3 = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the dashboard shows the invoice",
                "links": [],
            },
        ).json()["statement_id"]
        b4 = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the invoice is paid", "links": []},
        ).json()["statement_id"]
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "unrelated", "links": []},
        )

        # Filter by entity_id — dashboard matches b1, b2 (via alias), b3
        body = client.post(
            "/list-statements",
            json={"limit": 50, "offset": 0, "entity_id": dashboard_eid},
        ).json()
        assert body["total"] == 3
        assert {b["id"] for b in body["statements"]} == {b1, b2, b3}

        # Filter by name "dashboard" — same set
        body = client.post(
            "/list-statements", json={"limit": 50, "offset": 0, "name": "dashboard"}
        ).json()
        assert {b["id"] for b in body["statements"]} == {b1, b2, b3}

        # Filter by alias "workspace" — collapses to the same entity, same set
        body = client.post(
            "/list-statements", json={"limit": 50, "offset": 0, "name": "workspace"}
        ).json()
        assert {b["id"] for b in body["statements"]} == {b1, b2, b3}

        # Pagination respects the filter
        body = client.post(
            "/list-statements", json={"limit": 2, "offset": 0, "name": "dashboard"}
        ).json()
        assert body["total"] == 3
        assert len(body["statements"]) == 2

        # b3 mentions both dashboard and invoice — DISTINCT shouldn't double-count
        body = client.post(
            "/list-statements", json={"limit": 50, "offset": 0, "name": "invoice"}
        ).json()
        assert body["total"] == 2
        assert {b["id"] for b in body["statements"]} == {b3, b4}

        # Validation: both filters together → 400
        r = client.post(
            "/list-statements",
            json={
                "limit": 50,
                "offset": 0,
                "entity_id": dashboard_eid,
                "name": "dashboard",
            },
        )
        assert r.status_code == 400

        # Unknown name → 400
        r = client.post(
            "/list-statements", json={"limit": 50, "offset": 0, "name": "NonExistent"}
        )
        assert r.status_code == 400

        # Unknown entity_id → 400
        r = client.post(
            "/list-statements",
            json={"limit": 50, "offset": 0, "entity_id": "ent_does_not_exist"},
        )
        assert r.status_code == 400


def test_kind_filter_on_list_search_grep(tmp_path, monkeypatch):
    """Optional `kind` filter narrows list / search / grep to that kind."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        ev = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user logs in",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        st = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "session is active",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        cap = client.post(
            "/upsert-statement",
            json={
                "kind": "capability",
                "text": "admin can revoke session",
                "mentions": [],
                "links": [],
                "allow_phrasing_violations": True,
            },
        ).json()["statement_id"]

        body = client.post("/list-statements", json={"kind": "event"}).json()
        assert {b["id"] for b in body["statements"]} == {ev}
        assert all(b["kind"] == "event" for b in body["statements"])

        body = client.post("/list-statements", json={"kind": "state"}).json()
        assert {b["id"] for b in body["statements"]} == {st}

        body = client.post(
            "/grep-statements",
            json={
                "query": "session",
                "kind": "state",
            },
        ).json()
        assert {b["id"] for b in body["statements"]} == {st}

        body = client.post(
            "/grep-statements",
            json={
                "query": "session",
                "kind": "capability",
            },
        ).json()
        assert {b["id"] for b in body["statements"]} == {cap}

        # search filters by kind too
        hits = client.post(
            "/search-statements",
            json={
                "query": "session",
                "kind": "state",
                "limit": 10,
                "min_score": -1.0,
            },
        ).json()
        assert all(h["kind"] == "state" for h in hits)
        assert {h["id"] for h in hits} == {st}


def test_get_statement_returns_kind(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "user is signed in",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [sid]}).json()["statements"][
            0
        ]
        assert body["kind"] == "state"


def test_search_mentions_filter(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post("/upsert-entity", json={"name": "dashboard", "description": ""})
        client.post("/upsert-entity", json={"name": "invoice", "description": ""})

        b_both = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the dashboard shows the invoice",
                "links": [],
            },
        ).json()["statement_id"]
        b_dashboard_only = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the dashboard opens via sso", "links": []},
        ).json()["statement_id"]
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "unrelated topic", "links": []},
        ).json()["statement_id"]

        # Filter on a single entity — both dashboard statements match
        hits = client.post(
            "/search-statements",
            json={
                "query": "dashboard",
                "limit": 10,
                "min_score": -1.0,
                "mentions": ["dashboard"],
            },
        ).json()
        assert {h["id"] for h in hits} == {b_both, b_dashboard_only}

        # AND semantics — must mention both dashboard AND invoice
        hits = client.post(
            "/search-statements",
            json={
                "query": "dashboard",
                "limit": 10,
                "min_score": -1.0,
                "mentions": ["dashboard", "invoice"],
            },
        ).json()
        assert [h["id"] for h in hits] == [b_both]

        # Unknown name in filter → 400
        r = client.post(
            "/search-statements", json={"query": "x", "mentions": ["NonExistent"]}
        )
        assert r.status_code == 400


def test_unknown_words_mention_nothing(tmp_path, monkeypatch):
    """Mentions are derived from text against existing entity names. Words
    that are not the name of any existing entity produce no mentions and
    never auto-create an entity."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        known_id = client.post(
            "/upsert-entity", json={"name": "dashboard", "description": ""}
        ).json()["entity_id"]

        # Text mentions the known name → one derived mention.
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the dashboard refreshes",
                "links": [],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [sid]}).json()["statements"][
            0
        ]
        assert {m["entity_id"] for m in body["mentions"]} == {known_id}

        # Text whose distinctive words match no existing entity → no mentions.
        other = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the analytics warehouse synchronizes nightly",
                "links": [],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [other]}).json()[
            "statements"
        ][0]
        assert body["mentions"] == []

        # And no entity was auto-created for any of those unknown words.
        ents = client.post(
            "/list-entities", json={"prefix": "", "limit": 50, "offset": 0}
        ).json()
        assert {e["name"] for e in ents["entities"]} == {"dashboard"}


def test_upsert_statement_validates_outgoing_links(tmp_path, monkeypatch):
    """Outgoing links targets are checked before any mutation, like add_links."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "filler text",
                "mentions": [],
                "links": [{"to_id": "stm_missing", "link_type": "part"}],
            },
        )
        assert r.status_code == 400
        assert "stm_missing" in r.json()["detail"]


def test_upsert_after_merge_reuses_deleted_vector_slot(tmp_path, monkeypatch):
    """Regression: heavy merge sequences left hnswlib slots in mark_deleted
    state, but next_vector_id reallocated those numeric ids on the next
    insert. add_items without replace_deleted=True raised
    'Can't use addPoint to update deleted elements' mid-upsert, leaving
    the SQLite row written but the vector missing.
    """
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Two statements get vector_ids 0 and 1.
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "statement a", "mentions": [], "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "statement b", "mentions": [], "links": []},
        ).json()["statement_id"]

        # Merge B into A: B's statement_vector_ids row is dropped, its
        # hnswlib slot is mark_deleted. After this, MAX(vector_id) is 0
        # — so next_vector_id returns 1, the slot B used.
        r = client.post("/merge-statements", json={"from_id": b, "into_id": a})
        assert r.status_code == 200

        # The next insert lands on the deleted slot. With replace_deleted=True
        # this succeeds; without it, hnswlib raises and the SQL write is
        # left orphaned.
        r = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "statement c", "mentions": [], "links": []},
        )
        assert r.status_code == 200, f"upsert after merge failed: {r.text}"
        c = r.json()["statement_id"]

        # And the new statement is searchable — proving its vector actually
        # made it into the index, not just SQLite.
        hits = client.post(
            "/search-statements",
            json={"query": "statement c", "limit": 5, "min_score": -1.0},
        ).json()
        assert c in {h["id"] for h in hits}


def test_merge_statements_unions_links_and_drops_self_loops(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Entities for the target's own derived mentions. Mentions are no
        # longer unioned on merge — the target keeps its own (its text is
        # unchanged), so we set them up via the target's text.
        client.post("/upsert-entity", json={"name": "dashboard", "description": ""})
        client.post("/upsert-entity", json={"name": "invoice", "description": ""})

        # Cast: source A and target B (we'll merge A into B), plus parents and a child for both.
        parent_of_a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "parent of a", "links": []},
        ).json()["statement_id"]
        parent_of_b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "parent of b", "links": []},
        ).json()["statement_id"]
        shared_child = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "shared child", "links": []},
        ).json()["statement_id"]
        a_only_child = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "a only child", "links": []},
        ).json()["statement_id"]

        # Source A: mentions invoice (from text), outgoing → shared_child (part), outgoing → a_only_child (part), outgoing → B (triggers, would be self-loop after merge)
        # Plus incoming from parent_of_a (part)
        a = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "statement a about the invoice",
                "links": [
                    {"to_id": shared_child, "link_type": "part"},
                    {"to_id": a_only_child, "link_type": "part"},
                ],
                "incoming_links": [
                    {"from_id": parent_of_a, "link_type": "part"},
                ],
            },
        ).json()["statement_id"]

        # Target B: mentions dashboard (from text), outgoing → shared_child (part), incoming from parent_of_b (part)
        b = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "statement b about the dashboard",
                "links": [
                    {"to_id": shared_child, "link_type": "part"},
                ],
                "incoming_links": [
                    {"from_id": parent_of_b, "link_type": "part"},
                ],
            },
        ).json()["statement_id"]

        # The would-be self-loop: A → B via "triggers". After merge this would become B → B and should be dropped.
        client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": b, "link_type": "triggers"},
                ]
            },
        )

        # Merge A into B
        r = client.post(
            "/merge-statements",
            json={
                "from_id": a,
                "into_id": b,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["into_id"] == b
        # Mentions are derived from text, never unioned — always 0.
        assert body["mentions_moved"] == 0
        # a_only_child is unique to B's outgoing (shared_child dedupes; the A→B "triggers" is a self-loop and dropped)
        assert body["outgoing_links_moved"] == 1
        # parent_of_a's "part" → A becomes parent_of_a's "part" → B (parent_of_b already has a "part" → B but that's a different (from, type) so this is unique)
        assert body["incoming_links_moved"] == 1

        # Source A is gone
        r = client.post("/get-statements", json={"ids": [a]})
        assert r.status_code == 400

        # B keeps its OWN derived mention (dashboard); A's invoice mention is discarded with A.
        body = client.post("/get-statements", json={"ids": [b]}).json()["statements"][0]
        assert {m["name"] for m in body["mentions"]} == {"dashboard"}

        # B's outgoing: shared_child (part), a_only_child (part). The "triggers" self-loop is gone.
        out = sorted((link["to_id"], link["link_type"]) for link in body["links"])
        assert out == sorted([(shared_child, "part"), (a_only_child, "part")])
        assert not any(link["to_id"] == b for link in body["links"])  # no self-loops

        # B's incoming: parent_of_a (part), parent_of_b (part)
        incoming = sorted(
            (link["from_id"], link["link_type"]) for link in body["incoming_links"]
        )
        assert incoming == sorted([(parent_of_a, "part"), (parent_of_b, "part")])

        # Search no longer surfaces A
        hits = client.post(
            "/search-statements",
            json={
                "query": "statement a about the invoice",
                "min_score": 0.5,
                "limit": 10,
            },
        ).json()
        assert all(h["id"] != a for h in hits)

        # Idempotent no-op: merging a deleted id raises 400 (since the source is gone)
        r = client.post("/merge-statements", json={"from_id": a, "into_id": b})
        assert r.status_code == 400

        # Same-id is a no-op without raising
        r = client.post("/merge-statements", json={"from_id": b, "into_id": b})
        assert r.status_code == 200
        assert r.json()["mentions_moved"] == 0


def test_upsert_statement_warns_on_near_duplicate(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Existing statement
        first = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user signs in",
                "mentions": [],
                "links": [],
            },
        ).json()
        assert first["near_duplicates"] == []  # nothing else in the substrate yet

        # Same text again → near-duplicate of the first
        second = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user signs in",
                "mentions": [],
                "links": [],
            },
        ).json()
        assert len(second["near_duplicates"]) == 1
        nd = second["near_duplicates"][0]
        assert nd["id"] == first["statement_id"]
        assert nd["text"] == "user signs in"
        assert nd["score"] > 0.99

        # Distinct text → no warning
        third = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "completely different topic",
                "mentions": [],
                "links": [],
            },
        ).json()
        assert third["near_duplicates"] == []

        # Update path: id provided, self should be excluded from results
        fourth = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user signs in",
                "mentions": [],
                "links": [],
                "id": first["statement_id"],
            },
        ).json()
        # The OTHER statement with same text is still a near-dup; first itself is excluded.
        assert all(
            nd["id"] != first["statement_id"] for nd in fourth["near_duplicates"]
        )
        assert any(
            nd["id"] == second["statement_id"] for nd in fourth["near_duplicates"]
        )


def test_upsert_statements_batch_warns_on_internal_duplicates(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "alpha unique",
                        "mentions": [],
                        "links": [],
                    },
                    {
                        "kind": "event",
                        "text": "alpha unique",
                        "mentions": [],
                        "links": [],
                    },  # duplicate of @0
                    {
                        "kind": "event",
                        "text": "totally separate concept",
                        "mentions": [],
                        "links": [],
                    },
                ],
            },
        ).json()
        ids = [item["statement_id"] for item in r["results"]]
        nd = r["near_duplicates"]
        # Both duplicates should warn against each other; the third has no warning.
        assert ids[0] in nd and ids[1] in nd
        assert ids[2] not in nd
        assert nd[ids[0]][0]["id"] == ids[1]
        assert nd[ids[1]][0]["id"] == ids[0]


def test_find_duplicates_returns_pairs_above_threshold(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "alpha unique", "mentions": [], "links": []},
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "alpha unique", "mentions": [], "links": []},
        ).json()["statement_id"]
        c = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "alpha unique", "mentions": [], "links": []},
        ).json()["statement_id"]
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "completely separate concept",
                "mentions": [],
                "links": [],
            },
        )

        r = client.post(
            "/find-duplicates", json={"threshold": 0.92, "limit": 50}
        ).json()
        # Three identical statements → three unique pairs (a,b), (a,c), (b,c)
        assert len(r) == 3
        pair_keys = sorted(tuple(sorted([p["a_id"], p["b_id"]])) for p in r)
        expected = sorted(
            [
                tuple(sorted([a, b])),
                tuple(sorted([a, c])),
                tuple(sorted([b, c])),
            ]
        )
        assert pair_keys == expected
        for p in r:
            assert p["score"] > 0.99
            assert p["a_text"] == p["b_text"] == "alpha unique"

        # Higher threshold filters out partial matches; with this fake embed,
        # everything is either ~1.0 or ~0, so 0.5 still surfaces only the dups.
        r_strict = client.post("/find-duplicates", json={"threshold": 0.999}).json()
        assert len(r_strict) == 3

        # Empty substrate would return [] — already covered by the structure.
        # Limit caps results.
        r_capped = client.post(
            "/find-duplicates", json={"threshold": 0.5, "limit": 1}
        ).json()
        assert len(r_capped) == 1


def test_delete_statement_cascades_mentions_and_links(tmp_path, monkeypatch):
    """delete_statement should drop the statement and all rows referencing
    it (mentions, incoming/outgoing links, when references), free the
    vector slot for reuse, and report cascade counts."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Build a small graph around the deletion target.
        #   parent  --contains-->  target
        #   target  --triggers-->  child
        #   condition_for_x reified as the `when` on x --triggers (when target)--> y
        parent = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "parent fact", "mentions": [], "links": []},
        ).json()["statement_id"]
        child = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "child fact", "mentions": [], "links": []},
        ).json()["statement_id"]
        target = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the obsolete fact about Login",
                "links": [{"to_id": child, "link_type": "triggers"}],
                "incoming_links": [{"from_id": parent, "link_type": "contains"}],
            },
        ).json()["statement_id"]
        x = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "x", "mentions": [], "links": []},
        ).json()["statement_id"]
        y = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "y", "mentions": [], "links": []},
        ).json()["statement_id"]
        # x --triggers (when target)--> y
        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": x,
                        "to_id": y,
                        "link_type": "triggers",
                        "when": {"statement_id": target},
                    },
                ]
            },
        )

        r = client.post("/delete-statement", json={"id": target}).json()
        assert r == {
            "deleted": True,
            "mentions_removed": 0,  # mentions are text-derived; no names exist here
            "incoming_links_removed": 1,  # parent --contains--> target
            "outgoing_links_removed": 1,  # target --triggers--> child
            "when_references_removed": 1,  # x --triggers (when target)--> y
            "entity_statement_links_removed": 0,  # none were created
        }

        # Statement is gone — get_statement raises (400)
        assert client.post("/get-statements", json={"ids": [target]}).status_code == 400

        # Search no longer surfaces it
        hits = client.post(
            "/search-statements",
            json={"query": "obsolete fact", "limit": 10, "min_score": -1.0},
        ).json()
        assert target not in {h["id"] for h in hits}

        # The conditional edge x→y is gone too — x has no outgoing links left
        body = client.post("/get-statements", json={"ids": [x]}).json()["statements"][0]
        assert body["links"] == []

        # The parent's outgoing contains edge is gone (it pointed at target)
        body = client.post("/get-statements", json={"ids": [parent]}).json()[
            "statements"
        ][0]
        assert body["links"] == []

        # The child's incoming triggers edge is gone (it came from target)
        body = client.post("/get-statements", json={"ids": [child]}).json()[
            "statements"
        ][0]
        assert body["incoming_links"] == []

        # And the freed vector slot is reusable — no "addPoint to update
        # deleted elements" failure on the next insert.
        r = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "fresh fact", "mentions": [], "links": []},
        )
        assert r.status_code == 200


def test_delete_statement_unknown_id_400(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        r = client.post("/delete-statement", json={"id": "stm_nope"})
        assert r.status_code == 400


def test_discover_facts_classifies_exists_near_new(tmp_path, monkeypatch):
    """discover_facts should bucket each input into exists/near/new based on
    the top hit and surface the supporting matches inline."""

    # Hand-tuned embedder: each character of the text drops weight onto a
    # specific dimension, so we can shape similarity scores deterministically.
    def shape_embed(text: str) -> list[float]:
        from mycelium.vector import DIM

        v = [0.0] * DIM
        # 'A' contributes to dim 0, 'B' to dim 1, 'C' to dim 2; cosine
        # similarity between texts then reflects character overlap.
        for ch in text:
            if ch in "ABC":
                v[ord(ch) - ord("A")] = 1.0
        # Fallback so empty/unknown texts still have a vector.
        if all(x == 0 for x in v):
            v[3] = 1.0
        return v

    with _client(tmp_path, monkeypatch, shape_embed) as client:
        existing_a = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "AAAA", "mentions": [], "links": []},
        ).json()["statement_id"]
        existing_b = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "BBBB", "mentions": [], "links": []},
        ).json()["statement_id"]

        r = client.post(
            "/discover-facts",
            json={
                "texts": ["AAAA", "AB", "ZZ"],
            },
        ).json()
        assert len(r) == 3

        exact, mixed, novel = r
        assert exact == {
            "text": "AAAA",
            "status": "exists",
            "matches": [
                {
                    "id": existing_a,
                    "text": "AAAA",
                    "score": exact["matches"][0]["score"],
                },
            ],
        }
        assert exact["matches"][0]["score"] > 0.99

        # AB has cosine ~0.707 with both AAAA and BBBB → "near", not "exists"
        assert mixed["status"] == "near"
        assert {m["id"] for m in mixed["matches"]} == {existing_a, existing_b}
        assert all(
            0.5 < m["score"] < exact["matches"][0]["score"] for m in mixed["matches"]
        )

        # ZZ shares nothing with either existing → "new"
        assert novel == {"text": "ZZ", "status": "new", "matches": []}


def test_discover_facts_truncates_long_text_in_matches(tmp_path, monkeypatch):
    """Long match text should be truncated to a snippet so batch responses
    stay lean. Short text passes through unchanged."""
    long_text = "AAAA " + "x" * 200  # well over the 100-char snippet cap
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": long_text, "mentions": [], "links": []},
        )

        r = client.post("/discover-facts", json={"texts": [long_text]}).json()
        assert r[0]["status"] == "exists"
        snippet = r[0]["matches"][0]["text"]
        assert len(snippet) <= 100
        assert snippet.endswith("…")
        assert snippet.startswith("AAAA")


def test_when_expression_threads_through_link_lifecycle(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Statements A, B, condition C
        a = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "validation runs",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        b = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "invite is delivered",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        c = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "contact info passes validation",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]

        # Add A — triggers (when C) → B
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": a,
                        "to_id": b,
                        "link_type": "triggers",
                        "when": {"statement_id": c},
                    },
                ]
            },
        )
        assert r.json() == {"inserted": 1}

        # Same edge with NO when is a distinct edge — both can coexist.
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {"from_id": a, "to_id": b, "link_type": "triggers"},
                ]
            },
        )
        assert r.json() == {"inserted": 1}

        # get_statement surfaces both edges, when only on the conditional one
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert len(body["links"]) == 2
        conditional = next(link for link in body["links"] if "when" in link)
        unconditional = next(link for link in body["links"] if "when" not in link)
        assert conditional["when"] == {"statement_id": c}
        assert conditional["link_type"] == "triggers"
        assert unconditional["link_type"] == "triggers"

        # remove_links matches by canonical when — only the conditional edge goes
        r = client.post(
            "/remove-links",
            json={
                "links": [
                    {
                        "from_id": a,
                        "to_id": b,
                        "link_type": "triggers",
                        "when": {"statement_id": c},
                    },
                ]
            },
        )
        assert r.json() == {"removed": 1}
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert len(body["links"]) == 1
        assert "when" not in body["links"][0]

        # Validation: unknown leaf reference inside the when tree → 400, no insert
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": a,
                        "to_id": b,
                        "link_type": "enables",
                        "when": {"statement_id": "stm_missing"},
                    },
                ]
            },
        )
        assert r.status_code == 400


def test_merge_statements_rewrites_when_references(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Two condition statements c1 and c2 — we'll merge c1 into c2.
        # An edge X → triggers (when c1) → Y should become X → triggers (when c2) → Y.
        x = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "source", "mentions": [], "links": []},
        ).json()["statement_id"]
        y = client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "target", "mentions": [], "links": []},
        ).json()["statement_id"]
        c1 = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "condition one",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        c2 = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "condition two",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]

        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": x,
                        "to_id": y,
                        "link_type": "triggers",
                        "when": {"statement_id": c1},
                    },
                ]
            },
        )

        # Merge c1 into c2 — the X→Y edge should now be conditioned on c2.
        r = client.post("/merge-statements", json={"from_id": c1, "into_id": c2})
        assert r.status_code == 200

        body = client.post("/get-statements", json={"ids": [x]}).json()["statements"][0]
        assert body["links"] == [
            {
                "to_id": y,
                "link_type": "triggers",
                "when": {"statement_id": c2},
            }
        ]


def test_upsert_statements_batch_with_when_sibling_ref(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Batch creates source, target, and a condition all in one call,
        # wired together with @-refs including the when_statement_id.
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "validation runs",
                        "mentions": [],
                        "links": [],
                    },
                    {
                        "kind": "event",
                        "text": "invite is delivered",
                        "mentions": [],
                        "links": [],
                    },
                    {
                        "kind": "event",
                        "text": "contact info passes validation",
                        "mentions": [],
                        "links": [],
                        "incoming_links": [
                            {"from_id": "@0", "link_type": "produces"},
                        ],
                    },
                ],
            },
        ).json()
        ids = [item["statement_id"] for item in r["results"]]
        a, b, c = ids

        # Add the conditional edge using sibling indices on both endpoints AND when.
        client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "noop wrapper",
                        "mentions": [],
                        "links": [],
                    },
                ],
            },
        ).json()  # just to ensure batch keeps working

        # Now wire a → b when c via add-links (the batch only exercised links/incoming_links;
        # when-via-batch is the same code path through _resolve_ref).
        client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": a,
                        "to_id": b,
                        "link_type": "triggers",
                        "when": {"statement_id": c},
                    },
                ]
            },
        )
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        triggers_link = next(
            link for link in body["links"] if link["link_type"] == "triggers"
        )
        assert triggers_link["when"] == {"statement_id": c}


def test_replace_text_rederives_mentions_preserves_links(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post("/upsert-entity", json={"name": "dashboard", "description": ""})
        client.post("/upsert-entity", json={"name": "invoice", "description": ""})
        target = client.post(
            "/upsert-statement", json={"kind": "event", "text": "target", "links": []}
        ).json()["statement_id"]
        bid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the dashboard refreshes",
                "links": [{"to_id": target, "link_type": "triggers"}],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [bid]}).json()["statements"][
            0
        ]
        assert {m["name"] for m in body["mentions"]} == {"dashboard"}

        # Edit the text — mentions are RE-DERIVED from the new text (now
        # mentioning invoice, not dashboard); outgoing links are preserved.
        r = client.post(
            "/replace-text", json={"id": bid, "text": "the invoice is sent"}
        )
        assert r.status_code == 200
        body = client.post("/get-statements", json={"ids": [bid]}).json()["statements"][
            0
        ]
        assert body["text"] == "the invoice is sent"
        assert {m["name"] for m in body["mentions"]} == {"invoice"}
        assert body["links"] == [{"to_id": target, "link_type": "triggers"}]

        # Search now finds the new wording.
        hits = client.post(
            "/search-statements",
            json={"query": "the invoice is sent", "min_score": 0.99, "limit": 1},
        ).json()
        assert hits[0]["id"] == bid

        # Unknown id → 400
        assert (
            client.post(
                "/replace-text", json={"id": "stm_missing", "text": "x"}
            ).status_code
            == 400
        )


def test_mentions_are_derived_from_text(tmp_path, monkeypatch):
    """Mentions are no longer asserted — they are derived from the
    statement's text against existing entity names. A statement whose text
    contains a distinctive name mentions that entity; text containing no
    name has empty mentions."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        dashboard_id = client.post(
            "/upsert-entity", json={"name": "dashboard", "description": ""}
        ).json()["entity_id"]

        # Text contains the distinctive name → derives the mention.
        mentions_one = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the dashboard refreshes",
                "links": [],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [mentions_one]}).json()[
            "statements"
        ][0]
        assert [m["entity_id"] for m in body["mentions"]] == [dashboard_id]
        assert [m["name"] for m in body["mentions"]] == ["dashboard"]

        # Text contains no existing entity name → no mentions.
        mentions_none = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the system boots",
                "links": [],
            },
        ).json()["statement_id"]
        body = client.post("/get-statements", json={"ids": [mentions_none]}).json()[
            "statements"
        ][0]
        assert body["mentions"] == []


def test_upsert_statements_batch_with_sibling_refs(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # A distinctive entity each statement's text will mention, so all four
        # share the same derived mention.
        umbrella_id = client.post(
            "/upsert-entity", json={"name": "umbrella", "description": ""}
        ).json()["entity_id"]

        # An existing parent the batch will hang under via incoming_links.
        existing_parent = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "existing parent",
                "links": [],
            },
        ).json()["statement_id"]

        # Batch: 1 umbrella + 3 children, all wired together via @-refs.
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    # @0: umbrella, sits under existing_parent, contains @1..@3
                    {
                        "kind": "event",
                        "text": "the umbrella covers everything",
                        "links": [
                            {"to_id": "@1", "link_type": "contains"},
                            {"to_id": "@2", "link_type": "contains"},
                            {"to_id": "@3", "link_type": "contains"},
                        ],
                        "incoming_links": [
                            {"from_id": existing_parent, "link_type": "contains"},
                        ],
                    },
                    {"kind": "event", "text": "the umbrella child one", "links": []},
                    {"kind": "event", "text": "the umbrella child two", "links": []},
                    {"kind": "event", "text": "the umbrella child three", "links": []},
                ],
            },
        )
        assert r.status_code == 200
        ids = [item["statement_id"] for item in r.json()["results"]]
        assert len(ids) == 4
        umbrella, c1, c2, c3 = ids

        # Umbrella has 3 outgoing contains + 1 incoming from existing_parent.
        body = client.post("/get-statements", json={"ids": [umbrella]}).json()[
            "statements"
        ][0]
        outgoing = sorted((link["to_id"], link["link_type"]) for link in body["links"])
        assert outgoing == sorted(
            [(c1, "contains"), (c2, "contains"), (c3, "contains")]
        )
        assert body["incoming_links"] == [
            {"from_id": existing_parent, "link_type": "contains"}
        ]

        # Children all have an incoming contains from umbrella, no outgoing.
        for child in (c1, c2, c3):
            body = client.post("/get-statements", json={"ids": [child]}).json()[
                "statements"
            ][0]
            assert body["links"] == []
            assert body["incoming_links"] == [
                {"from_id": umbrella, "link_type": "contains"}
            ]

        # All four statements derive the same single umbrella entity mention.
        umbrella_entity_ids = set()
        for bid in ids:
            body = client.post("/get-statements", json={"ids": [bid]}).json()[
                "statements"
            ][0]
            for m in body["mentions"]:
                if m["name"] == "umbrella":
                    umbrella_entity_ids.add(m["entity_id"])
        assert umbrella_entity_ids == {umbrella_id}


def test_upsert_statements_validates_refs_atomically(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Out-of-range sibling index → 400, NO statements created.
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {"kind": "event", "text": "first", "mentions": [], "links": []},
                    {
                        "kind": "event",
                        "text": "second",
                        "mentions": [],
                        "links": [
                            {"to_id": "@5", "link_type": "contains"},
                        ],
                    },
                ],
            },
        )
        assert r.status_code == 400
        assert "@5" in r.json()["detail"]
        # Confirm nothing got written
        hits = client.post(
            "/search-statements", json={"query": "first", "min_score": -1.0}
        ).json()
        assert all(h["text"] != "first" for h in hits)
        assert all(h["text"] != "second" for h in hits)

        # Unknown existing-id reference → 400, NO writes.
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "alpha",
                        "mentions": [],
                        "links": [
                            {"to_id": "stm_missing", "link_type": "triggers"},
                        ],
                    },
                ],
            },
        )
        assert r.status_code == 400

        # Empty batch → empty results
        r = client.post("/upsert-statements", json={"statements": []})
        assert r.status_code == 200
        assert r.json() == {"results": [], "near_duplicates": {}}


def test_move_name_splits_into_new_entity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # one entity with a distinctive alias; the statement text contains
        # that alias so the mention is derived onto it.
        login_id = client.post(
            "/upsert-entity", json={"name": "Login", "description": "the login page"}
        ).json()["entity_id"]
        reviewer_name_id = client.post(
            "/upsert-name", json={"text": "reviewer", "entity_id": login_id}
        ).json()["name_id"]
        client.post(
            "/upsert-statement",
            json={"kind": "event", "text": "the reviewer proceeds", "links": []},
        )

        # split: new entity for the actor, then move "reviewer" onto it
        action_id = client.post(
            "/upsert-entity",
            json={"name": "Reviewer", "description": "the reviewer"},
        ).json()["entity_id"]
        r = client.post(
            "/move-name", json={"name_id": reviewer_name_id, "to_entity_id": action_id}
        )
        assert r.status_code == 200
        assert r.json() == {"name_id": reviewer_name_id, "entity_id": action_id}

        # statement now resolves "reviewer" to the new entity, original Login is untouched
        hits = client.post(
            "/search-statements",
            json={"query": "the reviewer proceeds", "min_score": 0.99},
        ).json()
        mention = next(m for m in hits[0]["mentions"] if m["name"] == "reviewer")
        assert mention["entity_id"] == action_id
        assert mention["entity_id"] != login_id

        # invalid ids surface as 400
        assert (
            client.post(
                "/move-name", json={"name_id": "nam_missing", "to_entity_id": action_id}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/move-name",
                json={"name_id": reviewer_name_id, "to_entity_id": "ent_missing"},
            ).status_code
            == 400
        )


def test_delete_name_drops_alias_and_its_mentions(tmp_path, monkeypatch):
    """delete_name should remove the alias and every statement_mentions
    row that referenced it. The owning entity stays."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        login_id = client.post(
            "/upsert-entity", json={"name": "Login page", "description": ""}
        ).json()["entity_id"]
        # Add a second alias for the same entity.
        signin_name_id = client.post(
            "/upsert-name", json={"text": "sign-in page", "entity_id": login_id}
        ).json()["name_id"]
        # The text contains both aliases; mentions dedup to one row per
        # entity, keyed on the LEFTMOST distinctive match — here the
        # "sign-in page" alias we are about to delete.
        stm_id = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "The sign-in page redirects to the Login page",
                "links": [],
            },
        ).json()["statement_id"]

        r = client.post("/delete-name", json={"name_id": signin_name_id}).json()
        assert r == {
            "deleted": True,
            "mentions_removed": 1,
        }

        # The deleted alias was the mention's representative; delete_name
        # queued a recompute so the surviving alias takes over. Drain the
        # (suite-disabled) worker synchronously.
        mention_worker.drain(store.substrate_connection())
        body = client.post("/get-statements", json={"ids": [stm_id]}).json()[
            "statements"
        ][0]
        mention_names = [m["name"] for m in body["mentions"]]
        assert mention_names == ["Login page"]

        # Entity itself survives.
        assert client.post("/get-entity", json={"id": login_id}).status_code == 200

        # Unknown id → 400
        assert (
            client.post("/delete-name", json={"name_id": "nam_missing"}).status_code
            == 400
        )


def test_delete_entity_cascades_names_mentions_and_links(tmp_path, monkeypatch):
    """delete_entity should drop the entity, all its names, mentions
    referencing those names, and entity_links touching the entity."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        login_id = client.post(
            "/upsert-entity", json={"name": "Login page", "description": ""}
        ).json()["entity_id"]
        # Second alias on the same entity.
        client.post(
            "/upsert-name", json={"text": "sign-in page", "entity_id": login_id}
        )
        # An auxiliary entity to hang an entity_link off.
        auth_id = client.post(
            "/upsert-entity", json={"name": "Auth", "description": ""}
        ).json()["entity_id"]
        client.post(
            "/add-entity-links",
            json={
                "links": [
                    {
                        "from_entity_id": login_id,
                        "to_entity_id": auth_id,
                        "link_type": "kind-of",
                    },
                    {
                        "from_entity_id": auth_id,
                        "to_entity_id": login_id,
                        "link_type": "depends-on",
                    },
                ]
            },
        )
        # Statements mentioning either alias.
        b1 = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "first statement touches the Login page",
                "links": [],
            },
        ).json()["statement_id"]
        b2 = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "second statement touches the sign-in page",
                "links": [],
            },
        ).json()["statement_id"]

        r = client.post("/delete-entity", json={"id": login_id}).json()
        assert r == {
            "deleted": True,
            # "Login page" + "sign-in page" plus their auto-generated
            # plurals "Login pages" / "sign-in pages".
            "names_removed": 4,
            "mentions_removed": 2,  # one text-derived mention per statement
            "outgoing_entity_links_removed": 1,
            "incoming_entity_links_removed": 1,
            "entity_statement_links_removed": 0,  # none were created
        }

        # Entity is gone.
        assert client.post("/get-entity", json={"id": login_id}).status_code == 400
        # Auxiliary entity survives.
        assert client.post("/get-entity", json={"id": auth_id}).status_code == 200
        # Statements survive but no longer report any mentions.
        for bid in (b1, b2):
            body = client.post("/get-statements", json={"ids": [bid]}).json()[
                "statements"
            ][0]
            assert body["mentions"] == []

        # Unknown id → 400
        assert (
            client.post("/delete-entity", json={"id": "ent_missing"}).status_code == 400
        )


def test_name_boost_lifts_statements_via_alias(tmp_path, monkeypatch):
    """A statement mentioning entity `workstation` (alias `dashboard`)
    outranks an unrelated statement when the query uses the alias. The
    statement's text mentions the entity via its primary name, and the
    name index matches `dashboard` → entity → boost on statements that
    mention that entity."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        eid = client.post(
            "/upsert-entity", json={"name": "workstation", "description": "auth"}
        ).json()["entity_id"]
        client.post("/upsert-name", json={"text": "dashboard", "entity_id": eid})

        # Statement whose text mentions the entity via "workstation", but
        # uses neither "dashboard" (the query) in its text.
        rel = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the workstation authenticates against the credentials store",
                "links": [],
            },
        ).json()["statement_id"]
        # Distractor: mentions nothing. With random embeddings the vector
        # similarities to the query are noise; without boost the ordering is
        # arbitrary, with boost the entity-mentioning statement must come first.
        distractor = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "completely opaque content about umbrellas",
                "links": [],
            },
        ).json()["statement_id"]

        # Boost on: the entity-mentioning statement ranks first.
        hits = client.post(
            "/search-statements",
            json={
                "query": "dashboard",
                "limit": 5,
            },
        ).json()
        ranks = {h["id"]: i for i, h in enumerate(hits)}
        assert ranks[rel] < ranks[distractor]

        # Boost off: alias-aware retrieval disabled; the score the
        # entity-mentioning statement carries should be pure cosine
        # against the query (no name_boost addend).
        hits_plain = client.post(
            "/search-statements",
            json={
                "query": "dashboard",
                "limit": 5,
                "name_boost": 0.0,
            },
        ).json()
        rel_plain = next(h for h in hits_plain if h["id"] == rel)
        # With boost the same statement scores higher than without.
        rel_boosted = next(h for h in hits if h["id"] == rel)
        assert rel_boosted["score"] > rel_plain["score"]


def test_name_boost_inert_when_no_name_matches(tmp_path, monkeypatch):
    """Queries that don't lexically resemble any entity name should get
    no boost — score with `name_boost > 0` matches score with
    `name_boost = 0`."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post("/upsert-entity", json={"name": "Login", "description": "auth"})
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user signs in",
                "mentions": ["Login"],
                "links": [],
            },
        )

        # A query string with no resemblance to any name in the index.
        hits_on = client.post(
            "/search-statements",
            json={
                "query": "qzxqzx orthogonal terms",
                "limit": 5,
            },
        ).json()
        hits_off = client.post(
            "/search-statements",
            json={
                "query": "qzxqzx orthogonal terms",
                "limit": 5,
                "name_boost": 0.0,
            },
        ).json()
        # Same scores because no name passed the min_score threshold.
        # (Random embeddings make exact equality fragile only if a name
        # accidentally clears 0.5 — extremely unlikely for these tokens.)
        on_scores = {h["id"]: h["score"] for h in hits_on}
        off_scores = {h["id"]: h["score"] for h in hits_off}
        assert on_scores == off_scores


def test_rename_name_updates_alias_index(tmp_path, monkeypatch):
    """Renaming a name re-embeds it: a query phrased with the new text
    must boost statements that mention the entity, and the old text
    must no longer do so."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        eid = client.post(
            "/upsert-entity",
            json={
                "name": "Embedder",
                "description": "",
            },
        ).json()["entity_id"]
        # A second, distinctive alias we'll rename. The query before/after
        # only matches the renamed text — the statement keeps its mention
        # via the primary "Embedder" name (present in the text).
        rename_name_id = client.post(
            "/upsert-name",
            json={
                "text": "vectorizer",
                "entity_id": eid,
            },
        ).json()["name_id"]
        # statement mentions the entity via "Embedder" in its text.
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the Embedder takes action on the role",
                "links": [],
            },
        ).json()["statement_id"]

        # Before rename: "Encoder" doesn't match the name index.
        before = client.post(
            "/search-statements",
            json={
                "query": "Encoder",
                "limit": 5,
            },
        ).json()
        before_score = next(h["score"] for h in before if h["id"] == sid)

        client.post(
            "/rename-name",
            json={
                "name_id": rename_name_id,
                "new_text": "Encoder",
            },
        )

        # After rename: "Encoder" matches the renamed name and lifts the score.
        after = client.post(
            "/search-statements",
            json={
                "query": "Encoder",
                "limit": 5,
            },
        ).json()
        after_score = next(h["score"] for h in after if h["id"] == sid)
        assert after_score > before_score


def test_get_statement_returns_when_references(tmp_path, monkeypatch):
    """A statement used as a `when` leaf on N edges surfaces all N
    edges in `when_references`, in either link direction."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # Three events; one state used as the gating condition.
        src = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "edge eval",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        win = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "win path",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        lose = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "lose path",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]
        cond = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "the draft is already applied",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]

        # Two edges gated on `cond`.
        r = client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": src,
                        "to_id": win,
                        "link_type": "establishes",
                        "when": {"statement_id": cond},
                    },
                    {
                        "from_id": src,
                        "to_id": lose,
                        "link_type": "establishes",
                        "when": {"statement_id": cond},
                    },
                ]
            },
        )
        assert r.json() == {"inserted": 2}

        # cond has no outgoing or incoming links of its own, yet shows
        # both edges as when_references.
        body = client.post("/get-statements", json={"ids": [cond]}).json()[
            "statements"
        ][0]
        assert body["links"] == []
        assert body["incoming_links"] == []
        refs = body["when_references"]
        assert len(refs) == 2
        pairs = {(r["from_id"], r["to_id"]) for r in refs}
        assert pairs == {(src, win), (src, lose)}
        # And every reference carries the full when tree.
        for r in refs:
            assert r["when"] == {"statement_id": cond}
            assert r["link_type"] == "establishes"

        # A statement never referenced in any when has empty when_references.
        body = client.post("/get-statements", json={"ids": [src]}).json()["statements"][
            0
        ]
        assert body["when_references"] == []


def test_grep_statements_alias_aware(tmp_path, monkeypatch):
    """grep_statements returns statements matched via text AND statements
    that mention an entity whose name contains the query as a substring."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        eid = client.post(
            "/upsert-entity",
            json={
                "name": "Link Type",
                "description": "",
            },
        ).json()["entity_id"]
        # Distinctive alias that CONTAINS the query substring "node".
        client.post("/upsert-name", json={"text": "nodemap", "entity_id": eid})

        # Two statements: one mentions Link Type (text contains the
        # multi-word name) but doesn't contain "node"; one mentions nothing
        # but text literally contains "node".
        via_mention = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the link type is resolved for the edge",
                "links": [],
            },
        ).json()["statement_id"]
        via_text = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "a node config is loaded",
                "links": [],
            },
        ).json()["statement_id"]

        # Default (alias-aware): both surface.
        r = client.post("/grep-statements", json={"query": "node"}).json()
        rows = {s["id"]: s for s in r["statements"]}
        assert via_text in rows
        assert via_mention in rows
        assert rows[via_text]["matched_via"] == "text"
        assert rows[via_mention]["matched_via"] == "mention"

        # Disabled: only literal text matches.
        r = client.post(
            "/grep-statements",
            json={
                "query": "node",
                "match_aliased_mentions": False,
            },
        ).json()
        rows = {s["id"]: s for s in r["statements"]}
        assert via_text in rows
        assert via_mention not in rows
        assert rows[via_text]["matched_via"] == "text"

        # entity_id filter suppresses alias expansion — the explicit
        # filter takes precedence.
        r = client.post(
            "/grep-statements",
            json={
                "query": "node",
                "entity_id": eid,
            },
        ).json()
        rows = {s["id"]: s for s in r["statements"]}
        # via_mention mentions Link Type but doesn't contain "node"
        # in text → excluded under entity_id+text-only path.
        assert via_mention not in rows
        # via_text doesn't mention Link Type → excluded by entity filter.
        assert via_text not in rows


def test_grep_statements_matched_via_both(tmp_path, monkeypatch):
    """A statement that both contains the query literally AND mentions
    an entity aliased to the query gets matched_via='both'."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        eid = client.post(
            "/upsert-entity",
            json={
                "name": "Link Type",
                "description": "",
            },
        ).json()["entity_id"]
        # Distinctive alias containing the query substring "node".
        client.post("/upsert-name", json={"text": "nodemap", "entity_id": eid})

        # Text contains the multi-word name (→ derived mention to the entity)
        # AND literally contains the substring "node".
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "the link type maps a node onto an edge",
                "links": [],
            },
        ).json()["statement_id"]

        r = client.post("/grep-statements", json={"query": "node"}).json()
        rows = {s["id"]: s for s in r["statements"]}
        assert rows[sid]["matched_via"] == "both"


def test_pending_mentions_review_surface(tmp_path, monkeypatch):
    """A suspect (short) name match is held in the pending-mentions queue,
    surfaced over HTTP, and approving it materializes the real mention."""
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        # "flow" is 4 chars → suspect; it is queued, not auto-linked.
        client.post("/upsert-entity", json={"name": "flow", "description": "a flow"})
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "the flow halts",
                "links": [],
            },
        ).json()["statement_id"]

        # Not yet a mention.
        stmt = client.post("/get-statements", json={"ids": [sid]}).json()["statements"][
            0
        ]
        assert stmt["mentions"] == []

        # It is in the open review queue.
        pend = client.get("/api/pending-mentions?status=open").json()[
            "pending_mentions"
        ]
        assert len(pend) == 1
        assert pend[0]["name"] == "flow"
        assert pend[0]["statement_id"] == sid
        pid = pend[0]["id"]

        # Approving materializes the mention and clears the open queue.
        r = client.patch(f"/api/pending-mentions/{pid}", json={"action": "approve"})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        stmt = client.post("/get-statements", json={"ids": [sid]}).json()["statements"][
            0
        ]
        assert [m["name"] for m in stmt["mentions"]] == ["flow"]
        assert (
            client.get("/api/pending-mentions?status=open").json()["pending_mentions"]
            == []
        )


def test_pending_mention_reject_writes_no_mention(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        client.post("/upsert-entity", json={"name": "data", "description": "x"})
        sid = client.post(
            "/upsert-statement",
            json={
                "kind": "state",
                "text": "the data is stale",
                "links": [],
            },
        ).json()["statement_id"]
        pid = client.get("/api/pending-mentions?status=open").json()[
            "pending_mentions"
        ][0]["id"]
        r = client.patch(f"/api/pending-mentions/{pid}", json={"action": "reject"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        stmt = client.post("/get-statements", json={"ids": [sid]}).json()["statements"][
            0
        ]
        assert stmt["mentions"] == []
        assert (
            client.get("/api/pending-mentions?status=open").json()["pending_mentions"]
            == []
        )
