"""Knowledge health counts and lists, over in-memory databases."""

from __future__ import annotations

import json

import pytest

from mycelium import docs_store, drafts_store, knowledge_health, store


@pytest.fixture
def conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    rows = {
        "stm_a": ("event", "an invoice is exported"),
        "stm_b": ("state", "the export is queued"),
        "stm_c": ("rule", "an export must finish within an hour"),
        "stm_d": ("capability", "an admin can enable single sign-on"),
        "stm_e": ("state", "the workspace is on a paid plan"),
    }
    for sid, (kind, text) in rows.items():
        conn.execute(
            "INSERT INTO statements (id, kind, text) VALUES (?, ?, ?)",
            (sid, kind, text),
        )
    conn.execute(
        "INSERT INTO statement_links (from_statement_id, to_statement_id, "
        "link_type, when_hash) VALUES ('stm_a', 'stm_b', 'next', 'NONE')"
    )
    conn.execute(
        "INSERT INTO statement_links (from_statement_id, to_statement_id, "
        "link_type, when_hash) VALUES ('stm_a', 'stm_b', 'next', 'paid')"
    )
    conn.execute(
        "INSERT INTO when_nodes (link_id, statement_id, child_index) "
        "SELECT link_id, 'stm_e', 0 FROM statement_links WHERE when_hash = 'paid'"
    )
    conn.execute(
        "INSERT INTO entities (id, description) VALUES "
        "('ent_invoice', 'A bill sent to a customer'), ('ent_sso', ''), "
        "('ent_unused', NULL)"
    )
    conn.execute(
        "INSERT INTO names (id, text, entity_id) VALUES "
        "('nam_invoice', 'invoice', 'ent_invoice'), "
        "('nam_sso', 'single sign-on', 'ent_sso'), "
        "('nam_unused', 'workspace', 'ent_unused')"
    )
    conn.execute(
        "INSERT INTO statement_mentions VALUES ('stm_a', 'nam_invoice'), "
        "('stm_d', 'nam_sso')"
    )
    conn.execute(
        "INSERT INTO statement_audience_labels (statement_id, audiences, source, "
        "reason, labelled_at) VALUES ('stm_a', '[]', 'curator', 'r', 'now')"
    )
    conn.execute(
        "INSERT INTO audience_label_queue (statement_id, enqueued_at, last_error) "
        "VALUES ('stm_c', 'now', 'model timed out'), ('stm_d', 'now', NULL)"
    )
    conn.execute(
        "INSERT INTO knowledge_gaps (id, text, created_at) VALUES "
        "('gap_open', 'how are exports retried', 'now')"
    )
    conn.execute(
        "INSERT INTO knowledge_gaps (id, text, created_at, resolved_at) VALUES "
        "('gap_done', 'answered', 'now', 'later')"
    )
    return conn


@pytest.fixture
def drafts():
    conn = drafts_store.connect(":memory:")
    drafts_store.migrate(conn)
    docs_store.migrate(conn)
    return conn


def _draft(drafts, draft_id, *, decided=False, ops=()):
    drafts.execute(
        "INSERT INTO drafts (id, created_at, decided_at, decision) VALUES (?, 'now', ?, ?)",
        (draft_id, "later" if decided else None, "approved" if decided else None),
    )
    for seq, (kind, payload) in enumerate(ops, start=1):
        drafts.execute(
            "INSERT INTO draft_ops (id, draft_id, seq, kind, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'now')",
            (f"{draft_id}_{seq}", draft_id, seq, kind, json.dumps(payload)),
        )


def test_counts_each_kind_of_attention(conn, drafts):
    # stm_e has no link of its own but is the condition of one: not isolated.
    _draft(drafts, "drf_open")
    _draft(drafts, "drf_done", decided=True)

    counts = knowledge_health.counts(conn, drafts, lambda: conn)

    assert counts.model_dump() == {
        "statements": 5,
        "entities": 3,
        "isolated": 2,
        "unmentioned": 3,
        "undescribed": 2,
        "unused": 1,
        "unlabelled": 4,
        "labelling_failed": 1,
        "open_gaps": 1,
        "pending_drafts": 1,
        "out_of_date_documents": 0,
        "old_media": 0,
    }


def test_lists_statements_with_what_they_lack(conn, drafts):
    page = knowledge_health.statements(conn, drafts, "unlabelled")

    assert [(i.id, i.links, i.mentions, i.label_error) for i in page.items] == [
        ("stm_b", 2, [], None),
        ("stm_c", 0, [], "model timed out"),
        ("stm_d", 0, ["single sign-on"], None),
        ("stm_e", 0, [], None),
    ]
    assert page.next_after is None


def test_pages_statements_in_id_order(conn, drafts):
    first = knowledge_health.statements(conn, drafts, "unlabelled", limit=2)
    rest = knowledge_health.statements(
        conn, drafts, "unlabelled", after=first.next_after, limit=2
    )

    assert [i.id for i in first.items] == ["stm_b", "stm_c"]
    assert [i.id for i in rest.items] == ["stm_d", "stm_e"]
    assert rest.next_after is None


def test_skips_statements_an_undecided_draft_already_connects(conn, drafts):
    _draft(
        drafts,
        "drf_open",
        ops=[
            (
                "add_links",
                {"links": [{"from_id": "stm_c", "to_id": "stm_a", "link_type": "x"}]},
            )
        ],
    )
    _draft(
        drafts,
        "drf_done",
        decided=True,
        ops=[
            (
                "add_links",
                {"links": [{"from_id": "stm_d", "to_id": "stm_a", "link_type": "x"}]},
            )
        ],
    )

    marked = knowledge_health.statements(conn, drafts, "isolated")
    skipped = knowledge_health.statements(
        conn, drafts, "isolated", limit=1, to_connect=True
    )

    assert [(i.id, i.in_pending_draft) for i in marked.items] == [
        ("stm_c", True),
        ("stm_d", False),
    ]
    assert [i.id for i in skipped.items] == ["stm_d"]


def test_offers_a_looked_at_statement_again_once_it_or_its_neighbourhood_changes(
    conn, drafts
):
    def to_connect():
        page = knowledge_health.statements(conn, drafts, "isolated", to_connect=True)
        return [i.id for i in page.items]

    knowledge_health.record_attempts(conn, {"stm_c": ["stm_a"], "stm_d": []})
    conn.execute("UPDATE curation_attempts SET attempted_at = '2026-01-01'")
    listed = knowledge_health.statements(conn, drafts, "isolated")

    assert to_connect() == []
    assert [i.settled_at for i in listed.items] == ["2026-01-01", "2026-01-01"]

    conn.execute("UPDATE statements SET updated_at = '2026-02-01' WHERE id = 'stm_a'")
    assert to_connect() == ["stm_c"]

    knowledge_health.record_attempts(conn, {"stm_c": ["stm_a"]})
    conn.execute("UPDATE statements SET text = 'an export ends' WHERE id = 'stm_c'")
    assert to_connect() == ["stm_c"]

    conn.execute(
        "INSERT INTO statements (id, kind, text, created_at) "
        "VALUES ('stm_f', 'rule', 'single sign-on needs a domain', '2026-03-01')"
    )
    conn.execute("INSERT INTO statement_mentions VALUES ('stm_f', 'nam_sso')")
    assert to_connect() == ["stm_c", "stm_d", "stm_f"]


def test_knows_whether_a_statement_has_an_open_gap(conn):
    store.create_knowledge_gap(conn, "rephrase it", statement_id="stm_c")

    assert knowledge_health.has_open_gap(conn, "stm_c")
    assert not knowledge_health.has_open_gap(conn, "stm_d")


def test_lists_entities_by_their_shown_name(conn, drafts):
    page = knowledge_health.entities(conn, "undescribed", limit=1)

    assert [(i.id, i.name) for i in page.items] == [("ent_sso", "single sign-on")]
    assert page.next_after == "ent_sso"
    assert [i.id for i in knowledge_health.entities(conn, "unused").items] == [
        "ent_unused"
    ]


def test_targets_refuse_an_unknown_statement(conn):
    with pytest.raises(ValueError, match="not a statement: stm_missing"):
        knowledge_health.targets(conn, ["stm_a", "stm_missing"])

    [target] = knowledge_health.targets(conn, ["stm_d"])
    assert (target.text, target.mentions, target.links) == (
        "an admin can enable single sign-on",
        ("single sign-on",),
        0,
    )
