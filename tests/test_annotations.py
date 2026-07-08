"""Annotation lifecycle tests against the HTTP transport.

Covers: create + retrieve, multi-attach to statements and entities,
update reconciles attachment sets, attach/detach idempotency, mentions
auto-create, near_duplicates response, delete_annotation cascades,
statement deletion leaves orphan annotation, merge_statements and
merge_entities move attachments, search filters by kind and mentions,
list filters compose.
"""

import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, server


def fake_embed_factory():
    rng = np.random.default_rng(0)

    def fake_embed(text: str) -> list[float]:
        return rng.standard_normal(768).astype(np.float32).tolist()

    return fake_embed


def deterministic_embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch, embedder):
    monkeypatch.setattr(embed, "embed", embedder)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    server._conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    from mycelium.http import app

    return TestClient(app)


def _bid(client, text, mentions=None):
    # These tests focus on annotation statement, not phrasing — bypass the
    # phrasing check so legacy filler texts ("An invite is created when…",
    # "Only recruiters can…", "Every invite has an email") still work.
    return client.post(
        "/upsert-statement",
        json={
            "kind": "event",
            "text": text,
            "mentions": mentions or [],
            "links": [],
            "allow_phrasing_violations": True,
        },
    ).json()["statement_id"]


def _eid(client, name, description=""):
    return client.post(
        "/upsert-entity", json={"name": name, "description": description}
    ).json()["entity_id"]


def test_annotation_attached_to_statement(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "An invite is created when a recruiter submits details")
        r = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Only recruiters can create invites",
                "statement_ids": [b],
                "mentions": ["Recruiter"],
            },
        )
        assert r.status_code == 200
        ann = r.json()["annotation_id"]
        assert ann.startswith("ann_")

        full = client.post("/get-annotation", json={"id": ann}).json()
        assert full["kind"] == "permission"
        assert full["text"] == "Only recruiters can create invites"
        assert [bv["id"] for bv in full["statements"]] == [b]
        assert full["entities"] == []
        assert {m["name"] for m in full["mentions"]} == {"Recruiter"}

        bh = client.post("/get-statements", json={"ids": [b]}).json()["statements"][0]
        assert [a["id"] for a in bh["annotations"]] == [ann]


def test_annotation_attached_to_entity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        e = _eid(client, "Recruiter", "internal user who creates invites")
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "fact",
                "text": "The Recruiter role is provisioned by HR",
                "entity_ids": [e],
            },
        ).json()["annotation_id"]

        en = client.post("/get-entity", json={"id": e}).json()
        assert [a["id"] for a in en["annotations"]] == [ann]


def test_annotation_attached_to_both_statement_and_entity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "An invite is created")
        e = _eid(client, "Recruiter", "")
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Only recruiters can create invites",
                "statement_ids": [b],
                "entity_ids": [e],
            },
        ).json()["annotation_id"]

        full = client.post("/get-annotation", json={"id": ann}).json()
        assert [bv["id"] for bv in full["statements"]] == [b]
        assert [ev["id"] for ev in full["entities"]] == [e]


def test_annotation_multi_attach_to_statements(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b1 = _bid(client, "An invite is created")
        b2 = _bid(client, "An invite is withdrawn")
        b3 = _bid(client, "An invite is edited")
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Only recruiters can manage invites",
                "statement_ids": [b1, b2, b3],
            },
        ).json()["annotation_id"]

        full = client.post("/get-annotation", json={"id": ann}).json()
        assert {bv["id"] for bv in full["statements"]} == {b1, b2, b3}


def test_upsert_with_id_reconciles_attachment_set(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b1 = _bid(client, "statement one")
        b2 = _bid(client, "statement two")
        b3 = _bid(client, "statement three")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "shared rule", "statement_ids": [b1, b2]},
        ).json()["annotation_id"]

        # Update wholesale: now attached only to b3.
        client.post(
            "/upsert-annotation",
            json={
                "kind": "fact",
                "text": "shared rule",
                "statement_ids": [b3],
                "id": ann,
            },
        )
        full = client.post("/get-annotation", json={"id": ann}).json()
        assert [bv["id"] for bv in full["statements"]] == [b3]


def test_attach_requires_exactly_one_target(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        e = _eid(client, "X", "")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "t", "statement_ids": [b]},
        ).json()["annotation_id"]

        # Both targets passed → 400
        r = client.post(
            "/attach-annotation",
            json={"annotation_id": ann, "statement_id": b, "entity_id": e},
        )
        assert r.status_code == 400

        # Neither target passed → 400
        r = client.post("/attach-annotation", json={"annotation_id": ann})
        assert r.status_code == 400


def test_attach_detach_are_idempotent(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "t", "statement_ids": []},
        ).json()["annotation_id"]

        first = client.post(
            "/attach-annotation",
            json={"annotation_id": ann, "statement_id": b},
        ).json()
        second = client.post(
            "/attach-annotation",
            json={"annotation_id": ann, "statement_id": b},
        ).json()
        assert first["attached"] == 1
        assert second["attached"] == 0

        first_d = client.post(
            "/detach-annotation",
            json={"annotation_id": ann, "statement_id": b},
        ).json()
        second_d = client.post(
            "/detach-annotation",
            json={"annotation_id": ann, "statement_id": b},
        ).json()
        assert first_d["detached"] == 1
        assert second_d["detached"] == 0


def test_mentions_auto_create_entity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Only Boss can fire",
                "statement_ids": [b],
                "mentions": ["Boss"],  # entity does not exist yet
            },
        ).json()["annotation_id"]
        full = client.post("/get-annotation", json={"id": ann}).json()
        # Boss got auto-materialised
        assert any(m["name"] == "Boss" for m in full["mentions"])

        # strict mode rejects unknown
        r = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Anything",
                "statement_ids": [b],
                "mentions": ["UnknownPersonXYZ"],
                "strict_mentions": True,
            },
        )
        assert r.status_code == 400


def test_near_duplicates_warning(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        b = _bid(client, "x")
        client.post(
            "/upsert-annotation",
            json={
                "kind": "fact",
                "text": "exactly the same wording",
                "statement_ids": [b],
            },
        )
        r = client.post(
            "/upsert-annotation",
            json={
                "kind": "fact",
                "text": "exactly the same wording",
                "statement_ids": [b],
            },
        ).json()
        # Same text → cosine = 1.0 with deterministic embedder; should appear
        # in near_duplicates of the second insert.
        assert len(r["near_duplicates"]) == 1
        assert r["near_duplicates"][0]["score"] >= 0.99


def test_delete_annotation_clears_joins(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        e = _eid(client, "X", "")
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "rule",
                "statement_ids": [b],
                "entity_ids": [e],
                "mentions": ["X"],
            },
        ).json()["annotation_id"]

        r = client.post("/delete-annotation", json={"id": ann}).json()
        assert r["deleted"] is True
        assert r["statement_attachments_removed"] == 1
        assert r["entity_attachments_removed"] == 1
        assert r["mentions_removed"] == 1

        # Statement and entity survive, just no longer reference this annotation.
        bh = client.post("/get-statements", json={"ids": [b]}).json()["statements"][0]
        assert bh["annotations"] == []
        en = client.post("/get-entity", json={"id": e}).json()
        assert en["annotations"] == []

        r = client.post("/get-annotation", json={"id": ann})
        assert r.status_code == 400


def test_statement_deletion_leaves_orphan_annotation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "rule", "statement_ids": [b]},
        ).json()["annotation_id"]

        r = client.post("/delete-statement", json={"id": b}).json()
        assert r["deleted"] is True
        assert r["annotation_attachments_removed"] == 1

        # Annotation persists as orphan; its statements list is empty.
        full = client.post("/get-annotation", json={"id": ann}).json()
        assert full["statements"] == []


def test_merge_statements_moves_annotation_attachments(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        a = _bid(client, "duplicate A")
        b = _bid(client, "canonical B")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "rule", "statement_ids": [a]},
        ).json()["annotation_id"]

        r = client.post(
            "/merge-statements",
            json={"from_id": a, "into_id": b},
        ).json()
        assert r["annotation_attachments_moved"] == 1

        full = client.post("/get-annotation", json={"id": ann}).json()
        assert [bv["id"] for bv in full["statements"]] == [b]


def test_merge_entities_moves_annotation_attachments(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        e1 = _eid(client, "Recruiter", "")
        e2 = _eid(client, "TalentAcquisition", "")
        ann = client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "role rule", "entity_ids": [e1]},
        ).json()["annotation_id"]

        r = client.post(
            "/merge-entities",
            json={"from_entity_id": e1, "into_entity_id": e2},
        ).json()
        assert r["annotation_attachments_moved"] == 1

        full = client.post("/get-annotation", json={"id": ann}).json()
        assert [ev["id"] for ev in full["entities"]] == [e2]


def test_list_annotations_filters_compose(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b1 = _bid(client, "statement one")
        b2 = _bid(client, "statement two")
        e = _eid(client, "Entity", "")

        client.post(
            "/upsert-annotation",
            json={"kind": "permission", "text": "p1", "statement_ids": [b1]},
        )
        client.post(
            "/upsert-annotation",
            json={"kind": "invariant", "text": "i1", "statement_ids": [b1]},
        )
        client.post(
            "/upsert-annotation",
            json={"kind": "permission", "text": "p2", "statement_ids": [b2]},
        )
        client.post(
            "/upsert-annotation",
            json={"kind": "fact", "text": "f1", "entity_ids": [e]},
        )

        # all annotations
        r = client.post("/list-annotations", json={}).json()
        assert r["total"] == 4

        # filter by statement
        r = client.post("/list-annotations", json={"statement_id": b1}).json()
        assert r["total"] == 2

        # filter by entity
        r = client.post("/list-annotations", json={"entity_id": e}).json()
        assert r["total"] == 1

        # filter by kind
        r = client.post("/list-annotations", json={"kind": "permission"}).json()
        assert r["total"] == 2

        # combined: statement + kind
        r = client.post(
            "/list-annotations",
            json={"statement_id": b1, "kind": "permission"},
        ).json()
        assert r["total"] == 1


def test_list_annotation_kinds_enumerates_in_use(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        client.post(
            "/upsert-annotation",
            json={"kind": "permission", "text": "p", "statement_ids": [b]},
        )
        client.post(
            "/upsert-annotation",
            json={"kind": "invariant", "text": "i", "statement_ids": [b]},
        )
        client.post(
            "/upsert-annotation",
            json={"kind": "permission", "text": "p2", "statement_ids": [b]},
        )

        kinds = client.get("/list-annotation-kinds").json()
        assert kinds == ["invariant", "permission"]


def test_starting_vocabulary_round_trips(tmp_path, monkeypatch):
    """Each starting-vocabulary kind (definition, default, example, note)
    inserts and reads back; list_annotation_kinds enumerates them all."""
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "anchor statement for attachments")
        for kind, body in [
            ("definition", "an invite is a one-time access grant"),
            ("default", "invite expiry defaults to 7 days"),
            ("example", "alice@example.com received invite #42"),
            ("note", "the 7-day default predates the audit project"),
        ]:
            r = client.post(
                "/upsert-annotation",
                json={"kind": kind, "text": body, "statement_ids": [b]},
            ).json()
            aid = r["annotation_id"]
            got = client.post("/get-annotation", json={"id": aid}).json()
            assert got["kind"] == kind
            assert got["text"] == body
        kinds = client.get("/list-annotation-kinds").json()
        assert kinds == ["default", "definition", "example", "note"]


def test_annotation_kind_rejected_when_null(tmp_path, monkeypatch):
    """Substrate enforces NOT NULL on annotation kind."""
    import sqlite3

    from mycelium import store as st

    with _client(tmp_path, monkeypatch, fake_embed_factory()):
        # Use the live connection to attempt a NULL-kind insert directly.
        from mycelium import server

        try:
            st.create_annotation(server._conn, None, "missing kind")  # type: ignore[arg-type]
        except sqlite3.IntegrityError as exc:
            assert "NOT NULL" in str(exc) or "kind" in str(exc)
        else:
            raise AssertionError("expected NOT NULL failure on annotation kind")


def test_grep_statements_literal_substring(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        _bid(client, "An invite is created with email")
        _bid(client, "A token is issued for the session")
        _bid(client, "An EMAIL is required for invites")

        # case-insensitive default — both 'email' and 'EMAIL' match
        r = client.post("/grep-statements", json={"query": "email"}).json()
        assert r["total"] == 2
        assert all("email" in b["text"].lower() for b in r["statements"])

        # case-sensitive
        r = client.post(
            "/grep-statements",
            json={"query": "EMAIL", "case_sensitive": True},
        ).json()
        assert r["total"] == 1
        assert "EMAIL" in r["statements"][0]["text"]


def test_grep_escapes_like_metacharacters(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        _bid(client, "match 100% complete")
        _bid(client, "match a_b_c identifier")
        _bid(client, "no special chars here")

        # `%` in query treated literally — only matches the row that contains it
        r = client.post("/grep-statements", json={"query": "100%"}).json()
        assert r["total"] == 1
        assert "100%" in r["statements"][0]["text"]

        # `_` in query treated literally
        r = client.post("/grep-statements", json={"query": "a_b_c"}).json()
        assert r["total"] == 1
        assert "a_b_c" in r["statements"][0]["text"]


def test_grep_statements_empty_query_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/grep-statements", json={"query": ""})
        assert r.status_code == 400


def test_grep_statements_filter_by_entity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        # Mentions are derived from text now, so the names must appear in the
        # statement text — and be distinctive (not short/common) to auto-link.
        _eid(client, "recruiter", "")
        _eid(client, "administrator", "")
        _bid(client, "the recruiter created an invite")
        _bid(client, "the administrator approved an invite")

        r = client.post(
            "/grep-statements",
            json={"query": "invite", "name": "recruiter"},
        ).json()
        assert r["total"] == 1
        assert "created" in r["statements"][0]["text"]


def test_get_entity_includes_mentioning_annotations(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        b = _bid(client, "x")
        e = _eid(client, "Recruiter", "")
        # Annotation attached to statement, but mentions Recruiter — should
        # surface under mentioning_annotations on the entity.
        ann = client.post(
            "/upsert-annotation",
            json={
                "kind": "permission",
                "text": "Only Recruiter can do X",
                "statement_ids": [b],
                "mentions": ["Recruiter"],
            },
        ).json()["annotation_id"]

        en = client.post("/get-entity", json={"id": e}).json()
        # Direct attachments empty (we only attached via mention)
        assert en["annotations"] == []
        # Mentioning annotations populated
        assert [a["id"] for a in en["mentioning_annotations"]] == [ann]
