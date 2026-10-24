"""The AI usage ledger: recording, reports and the monthly budget."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mycelium import ai, ai_usage, drafts_store
from mycelium.product_settings import AIBudgetSettings

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = drafts_store.connect(tmp_path / "drafts.db")
    drafts_store.migrate(db)
    yield db
    db.close()


def _call(
    action: str = "ask",
    *,
    model: str = "claude-sonnet-5-5",
    output: int = 85,
    ok: bool = True,
    run_id: str | None = None,
    draft_id: str | None = None,
) -> ai.usage.Call:
    """A call of 10 input, 5 cached and `output` output tokens."""
    return ai.usage.Call(
        action=action,
        provider="claude",
        model=model,
        usage=ai.Usage(
            input_tokens=10, cache_read_input_tokens=5, output_tokens=output
        ),
        duration_ms=1200,
        ok=ok,
        run_id=run_id,
        draft_id=draft_id,
    )


def test_report_aggregates_the_period_by_day_action_model_and_run(
    conn: sqlite3.Connection,
) -> None:
    ai_usage.record(conn, _call(), at="2026-09-30T23:59:59.000Z")
    ai_usage.record(conn, _call(), at="2026-10-01T08:00:00.000Z")
    ai_usage.record(
        conn, _call("docgen", run_id="drn_a", output=185), at="2026-10-01T09:00:00.000Z"
    )
    ai_usage.record(
        conn,
        _call("docgen", run_id="drn_a", ok=False),
        at="2026-10-02T09:00:00.000Z",
    )
    ai_usage.record(
        conn,
        _call("draft_review", run_id="drv_1", draft_id="drf_1"),
        at="2026-10-02T10:00:00.000Z",
    )
    ai_usage.record(
        conn, _call(model="claude-haiku-5-5"), at="2026-10-02T11:00:00.000Z"
    )

    report = ai_usage.report(conn, "2026-10-01T00:00:00.000Z")

    assert report.totals.model_dump() == {
        "calls": 5,
        "failed_calls": 1,
        "input_tokens": 50,
        "cached_tokens": 25,
        "output_tokens": 525,
        "tokens": 600,
    }
    assert [(d.day, d.calls, d.tokens) for d in report.days] == [
        ("2026-10-01", 2, 300),
        ("2026-10-02", 3, 300),
    ]
    assert [(a.action, a.calls, a.tokens) for a in report.actions] == [
        ("docgen", 2, 300),
        ("ask", 2, 200),
        ("draft_review", 1, 100),
    ]
    assert [(m.model, m.tokens) for m in report.models] == [
        ("claude-sonnet-5-5", 500),
        ("claude-haiku-5-5", 100),
    ]
    assert [(r.run_id, r.draft_id, r.calls, r.tokens) for r in report.runs] == [
        ("drn_a", None, 2, 300),
        ("drv_1", "drf_1", 1, 100),
    ]


def test_installed_metering_records_each_call_in_the_drafts_db(
    tmp_path: Path,
) -> None:
    path = tmp_path / "drafts.db"
    setup = drafts_store.connect(path)
    drafts_store.migrate(setup)
    setup.close()
    ai_usage.install(path)
    config = ai.ModelConfig("claude", "claude-haiku-5-5", 10, 1)

    with ai.usage.attributed("draft_review", run_id="drv_1", draft_id="drf_1"):
        with ai.usage.metered(config) as report:
            report(ai.Usage(input_tokens=1_000_000, output_tokens=1000))

    row = drafts_store.connect(path).execute("SELECT * FROM ai_usage").fetchone()
    assert (row["action"], row["run_id"], row["draft_id"], row["ok"]) == (
        "draft_review",
        "drv_1",
        "drf_1",
        1,
    )
    assert (row["input_tokens"], row["output_tokens"]) == (1_000_000, 1000)
    assert row["cost_usd"] is None


def test_mean_run_tokens_averages_whole_runs(conn: sqlite3.Connection) -> None:
    since = "2026-10-01T00:00:00.000Z"
    assert ai_usage.mean_run_tokens(conn, "draft_review", since) is None
    for run_id in ("drv_1", "drv_1", "drv_2"):
        ai_usage.record(conn, _call("draft_review", run_id=run_id), at="2026-10-02")
    ai_usage.record(
        conn, _call("draft_review", run_id="drv_0", output=9000), at="2026-09-30"
    )

    assert ai_usage.mean_run_tokens(conn, "draft_review", since) == 150


def test_budget_counts_only_this_utc_month(conn: sqlite3.Connection) -> None:
    ai_usage.record(conn, _call(output=5000), at="2026-09-30T23:00:00.000Z")
    ai_usage.record(conn, _call(output=835), at="2026-10-01T00:00:00.000Z")
    settings = AIBudgetSettings(monthly_limit_tokens=1000, warn_percent=80)

    status = ai_usage.budget(conn, settings, NOW)

    assert status is not None
    assert (status.used_tokens, status.percent, status.warning, status.paused) == (
        850,
        85.0,
        True,
        False,
    )
    assert ai_usage.budget(conn, AIBudgetSettings(), NOW) is None


def test_a_spent_budget_pauses_only_background_actions_when_asked(
    conn: sqlite3.Connection,
) -> None:
    ai_usage.record(conn, _call(), at="2026-10-05T00:00:00.000Z")
    pausing = AIBudgetSettings(monthly_limit_tokens=100, pause_background=True)

    for action in ("audience_labelling", "draft_review", "connect"):
        assert ai_usage.paused_reason(conn, action, pausing, NOW)
    for action in ("ask", "ingest", "docgen", "alias_discovery", "other"):
        assert ai_usage.paused_reason(conn, action, pausing, NOW) is None
    warning_only = AIBudgetSettings(monthly_limit_tokens=100)
    assert ai_usage.paused_reason(conn, "draft_review", warning_only, NOW) is None
