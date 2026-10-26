"""Tests for the async recompute worker's core (`mention_worker.drain`) and
the one-shot backfill script. Both are pure store-level (no embedder), so
they run without the server."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from mycelium import mention_worker, store

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "backfill_derived_mentions.py"
)


def _load_backfill_script():
    """Load the one-shot backfill script by file path (scripts/ isn't a
    package on sys.path)."""
    spec = importlib.util.spec_from_file_location("backfill_derived_mentions", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fresh(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    return conn


def _setup_corpus(conn):
    """Two distinctive entities and statements that mention them, with the
    derived mentions populated as the live path would."""
    e1 = store.create_entity(conn, None)
    store.create_name(conn, "dashboard", e1)
    e2 = store.create_entity(conn, None)
    store.create_name(conn, "invoice", e2)
    s1 = store.create_statement(conn, "state", "the dashboard renders")
    s2 = store.create_statement(conn, "state", "the invoice is paid")
    index = store.build_name_index(conn)
    store.derive_mentions(conn, s1, "the dashboard renders", index)
    store.derive_mentions(conn, s2, "the invoice is paid", index)
    return e1, e2, s1, s2


# ─── drain ─────────────────────────────────────────────────────────────────


def test_drain_statement_job_recomputes(tmp_path):
    conn = _fresh(tmp_path)
    _e1, _e2, s1, _s2 = _setup_corpus(conn)
    # Corrupt a stored mention, then enqueue a recompute and drain.
    conn.execute("DELETE FROM statement_mentions WHERE statement_id = ?", (s1,))
    conn.commit()
    store.enqueue_recompute_statements(conn, [s1])
    processed = mention_worker.drain(conn)
    assert processed == 1
    assert [r["name"] for r in store.get_mentions(conn, s1)] == ["dashboard"]
    assert store.count_open_recompute(conn) == 0


def test_drain_scan_job_finds_and_recomputes(tmp_path):
    conn = _fresh(tmp_path)
    # Statement exists before the entity does.
    sid = store.create_statement(conn, "state", "the workflow engine starts")
    e = store.create_entity(conn, None)
    store.create_name(conn, "workflow engine", e)
    store.enqueue_recompute_scan(conn, "workflow engine")
    mention_worker.drain(conn)
    assert [r["name"] for r in store.get_mentions(conn, sid)] == ["workflow engine"]


def test_drain_chunking_processes_everything(tmp_path):
    conn = _fresh(tmp_path)
    e = store.create_entity(conn, None)
    store.create_name(conn, "dashboard", e)
    sids = [
        store.create_statement(conn, "state", "the dashboard ticks") for _ in range(5)
    ]
    store.enqueue_recompute_statements(conn, sids)
    # chunk=1 forces 5 separate transactions; all must still be processed.
    processed = mention_worker.drain(conn, chunk=1)
    assert processed == 5
    assert store.count_open_recompute(conn) == 0
    for sid in sids:
        assert [r["name"] for r in store.get_mentions(conn, sid)] == ["dashboard"]


def test_reset_claimed_recompute_unclaims_stranded(tmp_path):
    conn = _fresh(tmp_path)
    _setup_corpus(conn)
    store.enqueue_recompute_scan(conn, "dashboard")
    # Simulate a crash mid-drain: rows claimed but never deleted.
    store.claim_recompute_batch(conn, 50)
    assert store.count_open_recompute(conn) == 0  # all claimed
    store.reset_claimed_recompute(conn)
    assert store.count_open_recompute(conn) == 1  # back to open, will retry


def test_drain_skips_deleted_statement(tmp_path):
    conn = _fresh(tmp_path)
    sid = store.create_statement(conn, "state", "the dashboard renders")
    store.enqueue_recompute_statements(conn, [sid])
    store.clear_derived_for_statement(conn, sid)
    conn.execute("DELETE FROM statements WHERE id = ?", (sid,))
    conn.commit()
    # The job references a now-deleted statement — drain must skip, not crash.
    mention_worker.drain(conn)
    assert store.count_open_recompute(conn) == 0


def test_a_failing_row_is_passed_over_and_stops_at_its_limit(tmp_path, monkeypatch):
    from mycelium import automation_stops, product_settings
    from product_settings_helpers import set_product

    set_product(product_settings.AutomationSettings(mention_retries=1))
    conn = _fresh(tmp_path)
    e = store.create_entity(conn, None)
    store.create_name(conn, "dashboard", e)
    bad, good = (
        store.create_statement(conn, "state", f"the dashboard {word}")
        for word in ("breaks", "renders")
    )
    store.enqueue_recompute_statements(conn, [bad, good])
    conn.commit()
    derive = store.derive_mentions

    def failing(conn, sid, text, index):
        if sid == bad:
            raise RuntimeError("cannot derive")
        derive(conn, sid, text, index)

    monkeypatch.setattr(store, "derive_mentions", failing)

    assert mention_worker.drain(conn) == 1
    assert [r["name"] for r in store.get_mentions(conn, good)] == ["dashboard"]
    assert automation_stops.stops(conn) == []
    mention_worker.drain(conn)
    [stop] = automation_stops.stops(conn)
    assert (stop.kind, stop.failures) == ("mention", 2)
    assert "cannot derive" in stop.reason
    assert store.claim_recompute_batch(conn, 50) == []

    monkeypatch.setattr(store, "derive_mentions", derive)
    store.reset_claimed_recompute(conn)
    automation_stops.retry(conn, "mention", stop.item_id)
    assert mention_worker.drain(conn) == 1
    assert store.count_open_recompute(conn) == 0
    assert automation_stops.stops(conn) == []


# ─── backfill script ─────────────────────────────────────────────────────────


def test_backfill_rebuilds_from_scratch(tmp_path, monkeypatch):
    conn = _fresh(tmp_path)
    _e1, _e2, s1, _s2 = _setup_corpus(conn)
    # Plant a stale/garbage mention the matcher would NOT produce.
    bad = store.create_entity(conn, None)
    bad_name = store.create_name(conn, "unrelated thing", bad)
    conn.execute(
        "INSERT INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        (s1, bad_name),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(sys, "argv", ["backfill", "--data-dir", str(tmp_path)])
    bf = _load_backfill_script()
    bf.main()

    conn2 = store.connect(tmp_path / "mycelium.db")
    # The garbage mention is gone; the real derived one remains.
    assert [r["name"] for r in store.get_mentions(conn2, s1)] == ["dashboard"]
