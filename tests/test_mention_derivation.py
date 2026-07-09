"""Integration tests for derived mentions: the sync statement-upsert path,
auto-plural generation, the suspect review queue, and the async recompute
worker. Exercises the real server functions with a stubbed embedder.
"""

from __future__ import annotations

import zlib

import numpy as np
import pytest

from mycelium import embed, mention_worker, server, store


def _embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    server._ctx = None
    server.init(tmp_path)  # worker disabled in tests (conftest); we drain by hand
    return server


def _mentions(sid: str) -> list[str]:
    return sorted(
        r["name"] for r in store.get_mentions(store.substrate_connection(), sid)
    )


def _pending(status: str = "open") -> list[str]:
    return sorted(
        p["name"]
        for p in store.list_pending_mentions(store.substrate_connection(), status)
    )


# ─── sync derivation ──────────────────────────────────────────────────────


def test_mentions_derived_from_text(srv):
    srv.upsert_entity(name="candidate", description="a job candidate")
    sid = srv.upsert_statement(
        kind="state", text="the candidate is screened", links=[]
    )["statement_id"]
    assert _mentions(sid) == ["candidate"]


def test_explicit_mention_tools_are_gone(srv):
    names = {t.__name__ for t in server.TOOLS}
    assert "add_mentions" not in names
    assert "remove_mentions" not in names
    import inspect

    params = set(inspect.signature(srv.upsert_statement).parameters)
    assert "mentions" not in params and "strict_mentions" not in params


def test_unknown_words_create_nothing(srv):
    # Statements no longer auto-create entities; an unmentioned word links nothing.
    sid = srv.upsert_statement(
        kind="state", text="something undefined happens", links=[]
    )["statement_id"]
    assert _mentions(sid) == []
    assert store.list_entities(store.substrate_connection()) == []


def test_editing_text_rederives(srv):
    srv.upsert_entity(name="dashboard", description="x")
    srv.upsert_entity(name="invoice", description="y")
    sid = srv.upsert_statement(kind="state", text="the dashboard loads", links=[])[
        "statement_id"
    ]
    assert _mentions(sid) == ["dashboard"]
    srv.replace_text(id=sid, text="the invoice loads")
    assert _mentions(sid) == ["invoice"]


# ─── suspect review queue ──────────────────────────────────────────────────


def test_suspect_name_is_queued_not_linked(srv):
    srv.upsert_entity(name="flow", description="a flow")  # 4 chars → suspect
    sid = srv.upsert_statement(kind="state", text="the flow halts", links=[])[
        "statement_id"
    ]
    assert _mentions(sid) == []
    assert _pending() == ["flow"]


def test_approving_pending_creates_the_mention(srv):
    srv.upsert_entity(name="flow", description="a flow")
    sid = srv.upsert_statement(kind="state", text="the flow halts", links=[])[
        "statement_id"
    ]
    pid = store.list_pending_mentions(store.substrate_connection())[0]["id"]
    assert store.approve_pending_mention(store.substrate_connection(), pid) is True
    assert _mentions(sid) == ["flow"]
    assert _pending("open") == []
    assert _pending("approved") == ["flow"]


def test_approved_mention_survives_unrelated_recompute(srv):
    # An approval is asserted truth: a recompute triggered by an UNRELATED
    # name change must not silently destroy it.
    srv.upsert_entity(name="flow", description="a flow")  # suspect
    srv.upsert_entity(name="dashboard", description="distinct")  # distinctive
    sid = srv.upsert_statement(
        kind="state", text="the flow drives the dashboard", links=[]
    )["statement_id"]
    assert _mentions(sid) == ["dashboard"]
    pid = store.list_pending_mentions(store.substrate_connection())[0]["id"]
    store.approve_pending_mention(store.substrate_connection(), pid)
    assert _mentions(sid) == ["dashboard", "flow"]
    # Unrelated name change anywhere → this statement gets recomputed.
    srv.upsert_entity(name="invoice", description="elsewhere")
    mention_worker.drain(store.substrate_connection())
    # The human-approved "flow" mention persists; nothing silently dropped.
    assert _mentions(sid) == ["dashboard", "flow"]
    assert _pending("approved") == ["flow"]
    assert _pending("open") == []


def test_approved_mention_dropped_when_text_no_longer_matches(srv):
    # If the statement is edited so the approved name no longer appears, the
    # mention correctly goes away (it reflects the text, not a frozen vote).
    srv.upsert_entity(name="flow", description="a flow")
    sid = srv.upsert_statement(kind="state", text="the flow halts", links=[])[
        "statement_id"
    ]
    pid = store.list_pending_mentions(store.substrate_connection())[0]["id"]
    store.approve_pending_mention(store.substrate_connection(), pid)
    assert _mentions(sid) == ["flow"]
    srv.replace_text(id=sid, text="the system halts")  # "flow" gone from text
    assert _mentions(sid) == []
    assert store.count_pending_mentions(store.substrate_connection(), "all") == 0


# ─── auto-plurals ──────────────────────────────────────────────────────────


def test_plural_auto_generated_and_matches(srv):
    srv.upsert_entity(name="candidate", description="x")
    plural = store.get_name_by_text(store.substrate_connection(), "candidates")
    assert plural is not None and plural["generated_from_name_id"] is not None
    sid = srv.upsert_statement(kind="event", text="five candidates applied", links=[])[
        "statement_id"
    ]
    # Matched via the generated plural; deduped to one mention for the entity.
    rows = store.get_mentions(store.substrate_connection(), sid)
    assert [r["name"] for r in rows] == ["candidates"]


def test_plural_collision_is_skipped(srv):
    # "status" has no confident plural → no generated child, no crash.
    srv.upsert_entity(name="status", description="x")
    assert (
        store.get_generated_children(
            store.substrate_connection(),
            store.get_name_by_text(store.substrate_connection(), "status")["id"],
        )
        == []
    )


# ─── async recompute worker ────────────────────────────────────────────────


def test_new_name_recomputes_existing_statement(srv):
    sid = srv.upsert_statement(kind="state", text="the dashboard is ready", links=[])[
        "statement_id"
    ]
    assert _mentions(sid) == []  # no such entity yet
    srv.upsert_entity(name="dashboard", description="x")  # enqueues a scan
    assert store.count_open_recompute(store.substrate_connection()) > 0
    mention_worker.drain(store.substrate_connection())
    assert _mentions(sid) == ["dashboard"]
    assert store.count_open_recompute(store.substrate_connection()) == 0


def test_delete_name_recomputes_shadowed_entity(srv):
    # "machine learning" (distinctive) shadows "learning" by maximal munch;
    # deleting it should let "learning" surface on recompute. (Both names are
    # long enough to be distinctive, not suspect.)
    srv.upsert_entity(name="machine learning", description="x")
    srv.upsert_entity(name="learning", description="y")
    sid = srv.upsert_statement(
        kind="state", text="the machine learning pipeline ships", links=[]
    )["statement_id"]
    assert _mentions(sid) == ["machine learning"]
    ml = store.get_name_by_text(store.substrate_connection(), "machine learning")["id"]
    srv.delete_name(name_id=ml)
    mention_worker.drain(store.substrate_connection())
    assert _mentions(sid) == ["learning"]


def test_merge_entities_recomputes(srv):
    srv.upsert_entity(name="recruiter", description="x")
    srv.upsert_entity(name="hiring manager", description="y")
    s_r = srv.upsert_statement(kind="state", text="the recruiter approves", links=[])[
        "statement_id"
    ]
    s_h = srv.upsert_statement(
        kind="state", text="the hiring manager approves", links=[]
    )["statement_id"]
    r_eid = store.get_name_by_text(store.substrate_connection(), "recruiter")[
        "entity_id"
    ]
    h_eid = store.get_name_by_text(store.substrate_connection(), "hiring manager")[
        "entity_id"
    ]
    srv.merge_entities(from_entity_id=r_eid, into_entity_id=h_eid)
    mention_worker.drain(store.substrate_connection())
    # Both statements now resolve their mention to the surviving entity.
    assert (
        store.get_mentions(store.substrate_connection(), s_r)[0]["entity_id"] == h_eid
    )
    assert (
        store.get_mentions(store.substrate_connection(), s_h)[0]["entity_id"] == h_eid
    )


def test_delete_statement_clears_derived_rows(srv):
    srv.upsert_entity(name="flow", description="x")  # suspect → pending
    srv.upsert_entity(name="dashboard", description="y")  # distinctive → mention
    sid = srv.upsert_statement(
        kind="state", text="the dashboard and the flow", links=[]
    )["statement_id"]
    assert _mentions(sid) == ["dashboard"]
    assert _pending() == ["flow"]
    srv.delete_statement(id=sid)
    assert store.get_mentions(store.substrate_connection(), sid) == []
    assert store.count_pending_mentions(store.substrate_connection()) == 0
