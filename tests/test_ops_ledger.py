"""Operation-ledger unit tests: classification, redaction, append/query,
retention, and the graceful-degradation guarantee (a broken ledger never
raises into the caller)."""

from __future__ import annotations

import sqlite3

import pytest

from mycelium import ops_ledger, timestamps


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Neutralise ledger env the host may have set, so tests start from the
    documented defaults regardless of the runner's environment."""
    monkeypatch.delenv("MYCELIUM_OPS_LEDGER", raising=False)
    monkeypatch.delenv("MYCELIUM_OPS_CAPTURE", raising=False)


@pytest.fixture
def ledger():
    """An in-memory ledger pinned on this thread."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ops_ledger.use_connection(conn)
    ops_ledger.migrate(conn)
    yield conn
    ops_ledger.reset()


# --- classification (pure) --------------------------------------------------


def test_classify_from_response_envelope():
    assert ops_ledger.classify({"statement_id": "stm_1"}, None) == "succeeded"
    assert ops_ledger.classify({"rejected": True, "violations": []}, None) == "rejected"
    assert ops_ledger.classify({"results": []}, None) == "no_hit"
    assert ops_ledger.classify({"results": [{"id": "stm_1"}]}, None) == "succeeded"
    assert ops_ledger.classify({"draft_id": "drf_1", "seq": 1, "queued": "x"}, None) == "queued"


def test_classify_from_error():
    assert ops_ledger.classify(None, PermissionError("nope")) == "rejected"
    assert ops_ledger.classify(None, ValueError("boom")) == "failed"


def test_classify_ignores_unknown_result_types():
    # A generator (streaming tool) must never be iterated — it stays succeeded.
    gen = (x for x in range(3))
    assert ops_ledger.classify(gen, None) == "succeeded"


# --- redaction / summarisation (pure) ---------------------------------------


def test_sanitize_request_redacts_and_truncates():
    out = ops_ledger.sanitize_request(
        {
            "token": "super-secret",
            "text": "x" * 1000,
            "embedding": [0.1, 0.2, 0.3, 0.4],
            "kind": "event",
        }
    )
    assert out["token"] == "[redacted]"
    assert out["text"].endswith("…") and len(out["text"]) <= 501
    assert out["embedding"] == "[4 items]"  # numeric list collapses
    assert out["kind"] == "event"


def test_summarize_result_extracts_metadata():
    summary, count, ids, draft = ops_ledger.summarize_result(
        {"results": [{"id": "stm_1"}, {"statement_id": "stm_2"}]}
    )
    assert count == 2
    assert ids == ["stm_1", "stm_2"]
    assert draft is None
    assert summary is not None


def test_summarize_result_passes_through_non_dict():
    gen = (x for x in range(3))
    assert ops_ledger.summarize_result(gen) == (None, None, None, None)
    assert next(gen) == 0  # untouched


# --- append + query ---------------------------------------------------------


def _rec(tool, *, result=None, error=None, actor="alice", transport="rest", request=None):
    ctx = ops_ledger.CallContext(
        tool=tool, actor=actor, transport=transport, request=request or {}
    )
    return ops_ledger.record(
        ctx, at_start=timestamps.now(), duration_ms=1.0, result=result, error=error
    )


def test_record_and_query_newest_first(ledger):
    _rec("search_statements", result={"results": []})
    _rec("upsert_statement", result={"statement_id": "stm_1"})
    _rec("upsert_statement", error=ValueError("boom"))

    rows, total = ops_ledger.query(ledger, limit=50, offset=0)
    assert total == 3
    assert [r["outcome"] for r in rows] == ["failed", "succeeded", "no_hit"]  # newest first


def test_query_filters(ledger):
    _rec("search_statements", result={"results": []})
    _rec("upsert_statement", result={"statement_id": "stm_1"}, actor="bob")

    rows, total = ops_ledger.query(ledger, limit=50, offset=0, outcomes={"no_hit"})
    assert total == 1 and rows[0]["tool"] == "search_statements"

    rows, total = ops_ledger.query(ledger, limit=50, offset=0, actor="bob")
    assert total == 1 and rows[0]["actor"] == "bob"

    rows, total = ops_ledger.query(ledger, limit=50, offset=0, tools={"upsert_statement"})
    assert total == 1


def test_record_persists_structured_metadata(ledger):
    _rec("upsert_statement", result={"draft_id": "drf_9", "seq": 1, "queued": "upsert"})
    row = ledger.execute("SELECT * FROM operations").fetchone()
    assert row["outcome"] == "queued"
    assert row["draft_id"] == "drf_9"
    assert row["duration_ms"] == 1.0
    assert row["transport"] == "rest"


# --- graceful degradation ---------------------------------------------------


def test_record_is_best_effort_when_unconfigured():
    """No connection configured → record swallows and returns None, never
    raising into the caller."""
    ops_ledger.reset()
    assert ops_ledger.enabled() is False
    ctx = ops_ledger.CallContext(tool="search_statements", request={})
    assert (
        ops_ledger.record(ctx, at_start="2026-07-20T00:00:00.000Z", duration_ms=1.0)
        is None
    )


def test_record_is_best_effort_on_broken_connection(ledger):
    ledger.close()  # subsequent writes raise ProgrammingError inside record
    assert _rec("search_statements", result={"results": []}) is None


def test_enabled_kill_switch(ledger, monkeypatch):
    assert ops_ledger.enabled() is True  # default-on when configured
    monkeypatch.setenv("MYCELIUM_OPS_LEDGER", "0")
    assert ops_ledger.enabled() is False


def test_capture_none_suppresses_content(ledger, monkeypatch):
    monkeypatch.setenv("MYCELIUM_OPS_CAPTURE", "none")
    ctx = ops_ledger.CallContext(tool="upsert_statement", request={"text": "hello"})
    ops_ledger.record(
        ctx,
        at_start="2026-07-20T00:00:00.000Z",
        duration_ms=1.0,
        result={"results": [{"id": "stm_1"}]},
    )
    row = ledger.execute("SELECT * FROM operations").fetchone()
    # Free-form content suppressed; structured metadata still kept.
    assert row["request_summary"] is None
    assert row["result_summary"] is None
    assert row["result_count"] == 1
    assert row["result_ids"] == '["stm_1"]'


# --- retention --------------------------------------------------------------


def test_prune_by_rows(ledger):
    for _ in range(5):
        _rec("search_statements", result={"results": []})
    removed = ops_ledger.prune(ledger, keep_days=None, keep_rows=2)
    assert removed == 3
    _, total = ops_ledger.query(ledger, limit=50, offset=0)
    assert total == 2


def test_prune_by_age(ledger):
    ledger.execute(
        "INSERT INTO operations (op_id, at_start, tool, outcome) VALUES (?,?,?,?)",
        ("op_old", "2000-01-01T00:00:00.000Z", "search_statements", "no_hit"),
    )
    _rec("search_statements", result={"results": []})  # at_start = now()
    removed = ops_ledger.prune(ledger, keep_days=30, keep_rows=None)
    assert removed == 1
    rows, _ = ops_ledger.query(ledger, limit=50, offset=0)
    assert all(r["op_id"] != "op_old" for r in rows)


def test_runtime_prune_bounds_a_long_lived_ledger(ledger, monkeypatch):
    """record() amortises retention so a never-restarted process stays bounded."""
    monkeypatch.setattr(ops_ledger, "_PRUNE_EVERY", 2)
    monkeypatch.setenv("MYCELIUM_OPS_RETENTION_ROWS", "3")
    for _ in range(10):
        _rec("search_statements", result={"results": []})
    _, total = ops_ledger.query(ledger, limit=50, offset=0)
    assert total <= 3  # pruned in-flight, not only at startup


# --- redaction of error messages & nested secrets ---------------------------


def test_error_message_is_truncated_and_gated(ledger):
    _rec("upsert_statement", error=ValueError("x" * 2000))
    row = ledger.execute("SELECT * FROM operations").fetchone()
    assert row["error_class"] == "ValueError"
    assert row["error_message"].endswith("…") and len(row["error_message"]) <= 501


def test_secret_substrings_redacted_in_request(ledger):
    _rec(
        "upsert_statement",
        result={"statement_id": "stm_1"},
        request={"access_token": "abc", "client_secret": "def", "kind": "event"},
    )
    row = ledger.execute("SELECT request_summary FROM operations").fetchone()
    assert '"access_token": "[redacted]"' in row["request_summary"]
    assert '"client_secret": "[redacted]"' in row["request_summary"]
    assert '"kind": "event"' in row["request_summary"]


def test_result_ids_are_capped(ledger):
    big = [{"id": f"stm_{i}"} for i in range(ops_ledger._MAX_IDS + 50)]
    _rec("search_statements", result=big)
    row = ledger.execute("SELECT result_count, result_ids FROM operations").fetchone()
    import json

    assert row["result_count"] == ops_ledger._MAX_IDS + 50  # true count kept
    assert len(json.loads(row["result_ids"])) == ops_ledger._MAX_IDS  # ids capped


def test_query_empty_filter_matches_nothing(ledger):
    _rec("search_statements", result={"results": []})
    # An explicitly empty set (e.g. an unknown outcome intersected away) must
    # return zero rows — distinct from None, which imposes no filter.
    _, total = ops_ledger.query(ledger, limit=50, offset=0, outcomes=set())
    assert total == 0
    _, total = ops_ledger.query(ledger, limit=50, offset=0, outcomes=None)
    assert total == 1
