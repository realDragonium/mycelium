"""End-to-end tests for the new when-expression shape on links.

Covers what's new about the model — AND/OR trees on links, distinct
conditional pathways between the same statements, canonicalization on
write, cascade detection through when-tree leaves in batch upsert,
delete-statement cascading through when references, and merge_statements
rewriting leaves transitively. Round-trip is intentionally not
structure-preserving — these tests assert canonical equality, not
verbatim shape.
"""

import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, server, when_expression as we


def deterministic_embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", deterministic_embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    server._conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    from mycelium.http import app
    return TestClient(app)


def _bid(client, text):
    return client.post(
        "/upsert-statement",
        json={"kind": "event", "text": text, "mentions": [], "links": [], "allow_phrasing_violations": True},
    ).json()["statement_id"]


# ─── AND / OR round-trip ────────────────────────────────────────────────────


def test_and_tree_round_trips(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha")
        b = _bid(client, "beta")
        x = _bid(client, "first condition")
        y = _bid(client, "second condition")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [{"statement_id": x}, {"statement_id": y}]},
        }]})
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert len(body["links"]) == 1
        link = body["links"][0]
        assert link["when"]["op"] == "and"
        assert {c["statement_id"] for c in link["when"]["of"]} == {x, y}


def test_not_tree_round_trips(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha")
        b = _bid(client, "beta")
        y = _bid(client, "absent condition")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "not", "of": [{"statement_id": y}]},
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert link["when"] == {"op": "not", "of": [{"statement_id": y}]}


def test_and_with_not_child_round_trips(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha")
        b = _bid(client, "beta")
        x = _bid(client, "must hold")
        y = _bid(client, "must not hold")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [
                {"statement_id": x},
                {"op": "not", "of": [{"statement_id": y}]},
            ]},
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert link["when"]["op"] == "and"
        kids = link["when"]["of"]
        assert len(kids) == 2
        plain = next(c for c in kids if "statement_id" in c)
        negated = next(c for c in kids if c.get("op") == "not")
        assert plain == {"statement_id": x}
        assert negated == {"op": "not", "of": [{"statement_id": y}]}


def test_or_tree_round_trips(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha")
        b = _bid(client, "beta")
        x = _bid(client, "first condition")
        y = _bid(client, "second condition")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "or", "of": [{"statement_id": x}, {"statement_id": y}]},
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert link["when"]["op"] == "or"
        assert {c["statement_id"] for c in link["when"]["of"]} == {x, y}


def test_nested_tree_round_trips(tmp_path, monkeypatch):
    """(A AND B) OR (C AND D) — exactly the case the flat-combinator
    proposal couldn't represent."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "source")
        b = _bid(client, "target")
        ca = _bid(client, "cA")
        cb = _bid(client, "cB")
        cc = _bid(client, "cC")
        cd = _bid(client, "cD")

        tree = {"op": "or", "of": [
            {"op": "and", "of": [{"statement_id": ca}, {"statement_id": cb}]},
            {"op": "and", "of": [{"statement_id": cc}, {"statement_id": cd}]},
        ]}
        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers", "when": tree,
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert we.hash_canonical(link["when"]) == we.hash_canonical(tree)


# ─── canonicalization on write ──────────────────────────────────────────────


def test_canonicalization_makes_reordered_when_the_same_link(tmp_path, monkeypatch):
    """AND(X, Y) and AND(Y, X) hash to the same when_hash, so the second
    insert is silently deduped."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta")
        x = _bid(client, "x"); y = _bid(client, "y")

        r1 = client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [{"statement_id": x}, {"statement_id": y}]},
        }]}).json()
        assert r1 == {"inserted": 1}

        r2 = client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [{"statement_id": y}, {"statement_id": x}]},
        }]}).json()
        assert r2 == {"inserted": 0}  # same edge after canonicalization

        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert len(body["links"]) == 1


def test_nested_same_op_flattens_on_write(tmp_path, monkeypatch):
    """AND(X, AND(Y, Z)) stores as AND(X, Y, Z)."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta")
        x = _bid(client, "x"); y = _bid(client, "y"); z = _bid(client, "z")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [
                {"statement_id": x},
                {"op": "and", "of": [{"statement_id": y}, {"statement_id": z}]},
            ]},
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert link["when"]["op"] == "and"
        assert {c["statement_id"] for c in link["when"]["of"]} == {x, y, z}


def test_single_child_internal_collapses_to_leaf(tmp_path, monkeypatch):
    """AND(X) stores as just X — equivalent and avoids a degenerate node."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta"); x = _bid(client, "x")
        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [{"statement_id": x}]},
        }]})
        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        assert link["when"] == {"statement_id": x}


# ─── distinct conditional pathways ──────────────────────────────────────────


def test_same_endpoints_different_when_are_distinct_links(tmp_path, monkeypatch):
    """Two different when-trees on the same (from, to, link_type) coexist
    as distinct conditional pathways."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta")
        x = _bid(client, "x"); y = _bid(client, "y"); z = _bid(client, "z")

        client.post("/add-links", json={"links": [
            {
                "from_id": a, "to_id": b, "link_type": "triggers",
                "when": {"op": "and", "of": [{"statement_id": x}, {"statement_id": y}]},
            },
            {
                "from_id": a, "to_id": b, "link_type": "triggers",
                "when": {"statement_id": z},
            },
        ]})
        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert len(body["links"]) == 2


# ─── delete_statement cascade through when-trees ────────────────────────────


def test_delete_statement_drops_links_referencing_it_in_when_tree(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta")
        x = _bid(client, "leaf x"); y = _bid(client, "leaf y")

        # Link with x AND y in its when-tree
        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "and", "of": [{"statement_id": x}, {"statement_id": y}]},
        }]})

        r = client.post("/delete-statement", json={"id": x}).json()
        assert r["when_references_removed"] == 1

        body = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]
        assert body["links"] == []


# ─── merge_statements transitive rewrite ────────────────────────────────────


def test_merge_rewrites_leaf_inside_nested_tree(tmp_path, monkeypatch):
    """Merging a leaf-referenced statement rewrites the leaf inside any
    when-tree, then re-canonicalizes the resulting tree."""
    with _client(tmp_path, monkeypatch) as client:
        a = _bid(client, "alpha"); b = _bid(client, "beta")
        c1 = _bid(client, "c1"); c2 = _bid(client, "c2"); other = _bid(client, "other")

        client.post("/add-links", json={"links": [{
            "from_id": a, "to_id": b, "link_type": "triggers",
            "when": {"op": "or", "of": [
                {"op": "and", "of": [{"statement_id": c1}, {"statement_id": other}]},
                {"statement_id": c1},
            ]},
        }]})

        client.post("/merge-statements", json={"from_id": c1, "into_id": c2})

        link = client.post("/get-statements", json={"ids": [a]}).json()["statements"][0]["links"][0]
        # After substitution, the tree should reference c2 wherever c1 was.
        # OR( AND(c2, other), c2 ) — the bare leaf c2 dominates the AND in OR
        # logic, but our canonicalization is purely structural (no semantic
        # absorption), so both branches survive.
        assert c1 not in we.leaves(link["when"])
        assert c2 in we.leaves(link["when"])
