"""History-log tests.

Every state-changing write records an event into the attached history DB.
Tests cover: (1) recording is a no-op when no history is attached, so the
existing in-memory test suite stays clean; (2) when attached, each kind of
write produces the expected event(s); (3) the recording uses the same
transaction as the main write (a rollback nukes both).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from mycelium import store


@pytest.fixture(autouse=True)
def _reset_actor():
    store.set_actor(None)
    yield
    store.set_actor(None)


def fresh_with_history(tmp_path):
    """Open a main DB + attached history DB on disk. In-memory ATTACH would
    require sharing the cache; on-disk is simpler and matches production."""
    main = tmp_path / "main.db"
    hist = tmp_path / "hist.db"
    conn = store.connect(main, history_path=hist)
    store.migrate(conn)
    return conn


def fresh_without_history():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def _events(conn, **filters):
    """Read every history event, newest last, with JSON pre-decoded."""
    sql = "SELECT * FROM history.history_events"
    where = []
    args = []
    for k, v in filters.items():
        where.append(f"{k} = ?")
        args.append(v)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY event_id"
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        for k in ("before_json", "after_json", "context_json"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


# --- no-history path -------------------------------------------------------


def test_no_history_attached_is_silent(tmp_path):
    """Without history_path, writes succeed and no history table exists."""
    conn = fresh_without_history()
    store.set_actor("alice")
    eid = store.create_entity(conn, "x")
    assert store.get_entity_by_id(conn, eid)["created_by"] == "alice"

    # No `history` schema attached, so referring to it errors out.
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT 1 FROM history.history_events")


def test_has_history_flag(tmp_path):
    no_hist = fresh_without_history()
    assert store.has_history(no_hist) is False
    with_hist = fresh_with_history(tmp_path)
    assert store.has_history(with_hist) is True


# --- entities --------------------------------------------------------------


def test_create_entity_records_event(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "x")

    events = _events(conn, target_id=eid)
    assert len(events) == 1
    e = events[0]
    assert e["op"] == "create"
    assert e["target_kind"] == "entity"
    assert e["actor"] == "alice"
    assert e["before_json"] is None
    assert e["after_json"]["description"] == "x"
    assert e["after_json"]["created_by"] == "alice"


def test_update_entity_records_before_and_after(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "old")
    store.set_actor("bob")
    store.update_entity_description(conn, eid, "new")

    events = _events(conn, target_id=eid)
    assert [e["op"] for e in events] == ["create", "update"]
    upd = events[1]
    assert upd["actor"] == "bob"
    assert upd["before_json"]["description"] == "old"
    assert upd["after_json"]["description"] == "new"


def test_delete_entity_records_before(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "doomed")
    store.delete_entity(conn, eid)

    events = _events(conn, target_id=eid)
    assert [e["op"] for e in events] == ["create", "delete"]
    delete = events[1]
    assert delete["before_json"]["description"] == "doomed"
    assert delete["after_json"] is None


# --- statements ------------------------------------------------------------


def test_statement_lifecycle_records_events(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    bid = store.create_statement(conn, "event", "user logs in")
    store.update_statement_text(conn, bid, "user authenticates")
    store.update_statement_kind(conn, bid, "state")

    events = _events(conn, target_id=bid)
    ops = [e["op"] for e in events]
    assert ops == ["create", "update", "update"]
    assert events[1]["before_json"]["text"] == "user logs in"
    assert events[1]["after_json"]["text"] == "user authenticates"
    assert events[2]["before_json"]["kind"] == "event"
    assert events[2]["after_json"]["kind"] == "state"


# --- names -----------------------------------------------------------------


def test_rename_name_records_context_reason(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, None)
    nid = store.create_name(conn, "Login", eid)
    store.rename_name(conn, nid, "Sign-in")

    events = _events(conn, target_id=nid)
    rename = next(e for e in events if e["op"] == "update")
    assert rename["context_json"]["reason"] == "rename_name"
    assert rename["before_json"]["text"] == "Login"
    assert rename["after_json"]["text"] == "Sign-in"


# --- statement links -------------------------------------------------------


def test_link_and_unlink_events(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    b1 = store.create_statement(conn, "event", "A")
    b2 = store.create_statement(conn, "event", "B")
    store.insert_links(conn, [(b1, b2, "triggers", None)])
    store.delete_links(conn, [(b1, b2, "triggers", None)])

    link_events = _events(conn, target_kind="statement_link")
    assert [e["op"] for e in link_events] == ["link", "unlink"]
    assert link_events[0]["after_json"]["from_id"] == b1
    assert link_events[0]["after_json"]["to_id"] == b2
    assert link_events[1]["before_json"]["link_type"] == "triggers"


# --- entity links -----------------------------------------------------------


def test_entity_link_events(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    e1 = store.create_entity(conn, None)
    e2 = store.create_entity(conn, None)
    store.insert_entity_links(conn, [(e1, e2, "contains")])
    store.delete_entity_links(conn, [(e1, e2, "contains")])

    events = _events(conn, target_kind="entity_link")
    assert [e["op"] for e in events] == ["link", "unlink"]


# --- transactional integrity ----------------------------------------------


def test_history_row_lands_in_same_transaction(tmp_path):
    """Sanity check: when the main row exists, the history event must
    exist too — rollback semantics are guaranteed by SQLite's ATTACH."""
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "x")
    main_count = conn.execute(
        "SELECT COUNT(*) AS n FROM entities WHERE id = ?", (eid,)
    ).fetchone()["n"]
    hist_count = conn.execute(
        "SELECT COUNT(*) AS n FROM history.history_events "
        "WHERE target_id = ? AND op = 'create'",
        (eid,),
    ).fetchone()["n"]
    assert main_count == 1 and hist_count == 1


# --- history_feed read model ------------------------------------------------
# The read model that powers /api/history. Unlike the live-table activity_feed,
# it reads the audit log, so deletes and superseded updates survive.


def _feed(conn, *, ops=frozenset(), kinds=frozenset(), query="", limit=100, offset=0):
    return store.history_feed(
        conn,
        limit=limit,
        offset=offset,
        ops=set(ops),
        kinds=set(kinds),
        query=query,
    )


def test_history_feed_includes_deletes(tmp_path):
    """A deleted entity is gone from the live tables but present in the feed —
    this is the whole reason the feed reads the audit log."""
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "doomed")
    store.delete_entity(conn, eid)

    rows, total = _feed(conn, kinds={"entity"})
    ops = [r["op"] for r in rows]
    assert "delete" in ops
    assert total == len(rows)
    delete_row = next(r for r in rows if r["op"] == "delete")
    assert delete_row["target_id"] == eid
    assert json.loads(delete_row["before_json"])["description"] == "doomed"


def test_history_feed_keeps_superseded_updates(tmp_path):
    """Two updates to the same statement both appear — the live-table feed
    would only ever show the latest updated_at."""
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    sid = store.create_statement(conn, "event", "user logs in")
    store.update_statement_text(conn, sid, "user signs in")
    store.update_statement_text(conn, sid, "user authenticates")

    rows, _ = _feed(conn, ops={"update"}, query=sid)
    assert len(rows) == 2  # both historical updates survive


def test_history_feed_newest_first_and_paginates(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    first = store.create_entity(conn, "first")
    last = store.create_entity(conn, "last")

    page1, total = _feed(conn, kinds={"entity"}, limit=1, offset=0)
    assert total == 2
    assert page1[0]["target_id"] == last  # newest first
    page2, _ = _feed(conn, kinds={"entity"}, limit=1, offset=1)
    assert page2[0]["target_id"] == first


def test_history_feed_filters_by_op_and_kind(tmp_path):
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, "x")
    store.update_entity_description(conn, eid, "y")

    creates, _ = _feed(conn, ops={"create"}, kinds={"entity"})
    assert [r["op"] for r in creates] == ["create"]


def test_history_feed_returns_context(tmp_path):
    """context_json rides along so the endpoint can surface audit reasons
    (rename/merge/reassignment) — not just before/after."""
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    eid = store.create_entity(conn, None)
    nid = store.create_name(conn, "Login", eid)
    store.rename_name(conn, nid, "Sign-in")

    rows, _ = _feed(conn, ops={"update"}, kinds={"name"})
    assert json.loads(rows[0]["context_json"])["reason"] == "rename_name"


def test_history_feed_query_treats_wildcards_literally(tmp_path):
    """A `%` in the query must match a literal percent, not act as a LIKE
    wildcard — otherwise `q` silently over-matches."""
    conn = fresh_with_history(tmp_path)
    store.set_actor("alice")
    plain = store.create_entity(conn, "plain")  # id has no '%'
    # No target_id contains a literal '%', so a literal search finds nothing;
    # if '%' were an unescaped wildcard it would match everything.
    rows, total = _feed(conn, query="%")
    assert total == 0 and rows == []
    # Sanity: a real substring of a real id still matches.
    rows, _ = _feed(conn, query=plain[:4])
    assert any(r["target_id"] == plain for r in rows)
