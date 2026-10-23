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
    cost: float | None = 1.0,
    output: int = 100,
    ok: bool = True,
    run_id: str | None = None,
    draft_id: str | None = None,
) -> ai.usage.Call:
    return ai.usage.Call(
        action=action,
        provider="claude",
        model=model,
        usage=ai.Usage(
            input_tokens=10, cache_read_input_tokens=5, output_tokens=output
        ),
        cost_usd=cost,
        duration_ms=1200,
        ok=ok,
        run_id=run_id,
        draft_id=draft_id,
    )


def test_report_aggregates_the_period_by_day_action_model_and_run(
    conn: sqlite3.Connection,
) -> None:
    ai_usage.record(conn, _call(), at="2026-09-30T23:59:59.000Z")
    ai_usage.record(conn, _call(cost=0.5), at="2026-10-01T08:00:00.000Z")
    ai_usage.record(
        conn, _call("docgen", run_id="drn_a", cost=2.0), at="2026-10-01T09:00:00.000Z"
    )
    ai_usage.record(
        conn,
        _call("docgen", run_id="drn_a", cost=1.0, ok=False),
        at="2026-10-02T09:00:00.000Z",
    )
    ai_usage.record(
        conn,
        _call("draft_review", run_id="drv_1", draft_id="drf_1", cost=0.25),
        at="2026-10-02T10:00:00.000Z",
    )
    ai_usage.record(
        conn, _call(model="unpriced", cost=None), at="2026-10-02T11:00:00.000Z"
    )

    report = ai_usage.report(conn, "2026-10-01T00:00:00.000Z")

    assert report.totals.model_dump() == {
        "calls": 5,
        "failed_calls": 1,
        "unpriced_calls": 1,
        "input_tokens": 75,
        "cached_tokens": 25,
        "output_tokens": 500,
        "cost_usd": 3.75,
    }
    assert [(d.day, d.calls, d.cost_usd) for d in report.days] == [
        ("2026-10-01", 2, 2.5),
        ("2026-10-02", 3, 1.25),
    ]
    assert [(a.action, a.calls, a.cost_usd) for a in report.actions] == [
        ("docgen", 2, 3.0),
        ("ask", 2, 0.5),
        ("draft_review", 1, 0.25),
    ]
    assert [(m.model, m.priced) for m in report.models] == [
        ("claude-sonnet-5-5", True),
        ("unpriced", False),
    ]
    assert [(r.run_id, r.draft_id, r.calls, r.cost_usd) for r in report.runs] == [
        ("drn_a", None, 2, 3.0),
        ("drv_1", "drf_1", 1, 0.25),
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
    assert row["cost_usd"] == pytest.approx(0.10 + 0.0005)


def test_mean_run_cost_averages_whole_priced_runs(conn: sqlite3.Connection) -> None:
    since = "2026-10-01T00:00:00.000Z"
    assert ai_usage.mean_run_cost(conn, "draft_review", since) is None
    for run_id, cost in [("drv_1", 0.25), ("drv_1", 0.25), ("drv_2", 0.1)]:
        ai_usage.record(
            conn, _call("draft_review", run_id=run_id, cost=cost), at="2026-10-02"
        )
    ai_usage.record(
        conn, _call("draft_review", run_id="drv_3", cost=None), at="2026-10-02"
    )
    ai_usage.record(
        conn, _call("draft_review", run_id="drv_0", cost=9.0), at="2026-09-30"
    )

    assert ai_usage.mean_run_cost(conn, "draft_review", since) == pytest.approx(0.3)


def test_budget_counts_only_this_utc_month(conn: sqlite3.Connection) -> None:
    ai_usage.record(conn, _call(cost=50.0), at="2026-09-30T23:00:00.000Z")
    ai_usage.record(conn, _call(cost=8.5), at="2026-10-01T00:00:00.000Z")
    settings = AIBudgetSettings(monthly_limit_usd=10, warn_percent=80)

    status = ai_usage.budget(conn, settings, NOW)

    assert status is not None
    assert (status.spent_usd, status.percent, status.warning, status.paused) == (
        8.5,
        85.0,
        True,
        False,
    )
    assert ai_usage.budget(conn, AIBudgetSettings(), NOW) is None


def test_a_spent_budget_pauses_only_background_actions_when_asked(
    conn: sqlite3.Connection,
) -> None:
    ai_usage.record(conn, _call(cost=10.0), at="2026-10-05T00:00:00.000Z")
    pausing = AIBudgetSettings(monthly_limit_usd=10, pause_background=True)

    for action in ("audience_labelling", "draft_review", "connect"):
        assert ai_usage.paused_reason(conn, action, pausing, NOW)
    for action in ("ask", "ingest", "docgen", "alias_discovery", "other"):
        assert ai_usage.paused_reason(conn, action, pausing, NOW) is None
    warning_only = AIBudgetSettings(monthly_limit_usd=10)
    assert ai_usage.paused_reason(conn, "draft_review", warning_only, NOW) is None
