"""What the instance spends on models: the call ledger, reports and budget.

Every model call lands here through the recorder `install` hands to
`ai.usage`, one compact row per call, in the drafts database beside the runs
it is attributed to. Like those runs it is operational history rather than
substrate truth. It rides along in backups: rows are small, and a restore
without them would reset the month's spend and silently re-arm a budget that
had paused background work.

Costs are list-price estimates (`ai.pricing`); a call to an unpriced model
keeps its tokens with no cost and is counted separately so a total never
reads as complete when it is not. Days and the budget month are UTC.

The recorder writes through its own autocommit connection per thread, so a
call made while the caller holds a drafts transaction neither joins nor
commits it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from . import drafts_store, product_settings, timestamps
from .ai import usage
from .connections import ConnectionProvider

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
    id                 INTEGER PRIMARY KEY,
    at                 TEXT NOT NULL,
    action             TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    input_tokens       INTEGER NOT NULL,
    cached_tokens      INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    output_tokens      INTEGER NOT NULL,
    cost_usd           REAL,
    duration_ms        INTEGER NOT NULL,
    ok                 INTEGER NOT NULL,
    run_id             TEXT,
    draft_id           TEXT
);
CREATE INDEX IF NOT EXISTS ai_usage_at ON ai_usage(at);
"""

#: Actions that run without a person waiting on them; the only ones a spent
#: budget may pause. `connect` is the connect pass.
BACKGROUND_ACTIONS = frozenset({"audience_labelling", "draft_review", "connect"})


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _connect(path: str) -> sqlite3.Connection:
    conn = drafts_store.connect(path)
    conn.isolation_level = None
    return conn


_provider: ConnectionProvider[str] = ConnectionProvider("ai_usage", _connect)


def install(drafts_path: Path | str) -> None:
    """Record every model call into the drafts database at `drafts_path`."""
    _provider.configure(str(drafts_path))
    usage.install(lambda call: record(_provider.connection(), call), _gate)


def uninstall() -> None:
    usage.install(None)
    _provider.reset()


def record(conn: sqlite3.Connection, call: usage.Call, at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO ai_usage (at, action, provider, model, input_tokens, "
        "cached_tokens, cache_write_tokens, output_tokens, cost_usd, duration_ms, "
        "ok, run_id, draft_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            at or timestamps.now(),
            call.action,
            call.provider,
            call.model,
            call.usage.input_tokens,
            call.usage.cache_read_input_tokens,
            call.usage.cache_creation_input_tokens,
            call.usage.output_tokens,
            call.cost_usd,
            call.duration_ms,
            int(call.ok),
            call.run_id,
            call.draft_id,
        ),
    )


# --- reports -------------------------------------------------------------------


class Totals(BaseModel):
    calls: int
    failed_calls: int
    unpriced_calls: int
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float


class Day(BaseModel):
    day: str
    calls: int
    cost_usd: float


class ActionSpend(BaseModel):
    action: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ModelSpend(BaseModel):
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    priced: bool


class RunSpend(BaseModel):
    action: str
    run_id: str | None
    draft_id: str | None
    calls: int
    cost_usd: float
    last_at: str


class Report(BaseModel):
    since: str
    totals: Totals
    days: list[Day]
    actions: list[ActionSpend]
    models: list[ModelSpend]
    runs: list[RunSpend]


_SUMS = (
    "COUNT(*) AS calls, COALESCE(SUM(input_tokens + cached_tokens + "
    "cache_write_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) "
    "AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd"
)


def report(conn: sqlite3.Connection, since: str, *, top_runs: int = 10) -> Report:
    """Spend from `since` (a `timestamps` value) on, and the most expensive
    runs that made calls in that period."""
    totals = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(1 - ok), 0), "
        "COALESCE(SUM(cost_usd IS NULL), 0), "
        "COALESCE(SUM(input_tokens + cached_tokens + cache_write_tokens), 0), "
        "COALESCE(SUM(cached_tokens), 0), COALESCE(SUM(output_tokens), 0), "
        "COALESCE(SUM(cost_usd), 0) FROM ai_usage WHERE at >= ?",
        (since,),
    ).fetchone()
    days = conn.execute(
        "SELECT substr(at, 1, 10) AS day, COUNT(*) AS calls, "
        "COALESCE(SUM(cost_usd), 0) AS cost_usd FROM ai_usage WHERE at >= ? "
        "GROUP BY day ORDER BY day",
        (since,),
    ).fetchall()
    actions = conn.execute(
        f"SELECT action, {_SUMS} FROM ai_usage WHERE at >= ? "
        "GROUP BY action ORDER BY cost_usd DESC, calls DESC",
        (since,),
    ).fetchall()
    models = conn.execute(
        f"SELECT provider, model, {_SUMS}, SUM(cost_usd IS NULL) = 0 AS priced "
        "FROM ai_usage WHERE at >= ? GROUP BY provider, model "
        "ORDER BY cost_usd DESC, calls DESC",
        (since,),
    ).fetchall()
    # A review run is reached through its draft, so draft-only calls group by
    # draft and every other attributed call by its run.
    runs = conn.execute(
        "SELECT action, run_id, draft_id, COUNT(*) AS calls, "
        "COALESCE(SUM(cost_usd), 0) AS cost_usd, MAX(at) AS last_at FROM ai_usage "
        "WHERE at >= ? AND (run_id IS NOT NULL OR draft_id IS NOT NULL) "
        "GROUP BY action, COALESCE(run_id, draft_id) "
        "ORDER BY cost_usd DESC, last_at DESC LIMIT ?",
        (since, top_runs),
    ).fetchall()
    return Report(
        since=since,
        totals=Totals(
            calls=totals[0],
            failed_calls=totals[1],
            unpriced_calls=totals[2],
            input_tokens=totals[3],
            cached_tokens=totals[4],
            output_tokens=totals[5],
            cost_usd=totals[6],
        ),
        days=[Day.model_validate(dict(row)) for row in days],
        actions=[ActionSpend.model_validate(dict(row)) for row in actions],
        models=[
            ModelSpend.model_validate({**dict(row), "priced": bool(row["priced"])})
            for row in models
        ],
        runs=[RunSpend.model_validate(dict(row)) for row in runs],
    )


# --- budget --------------------------------------------------------------------


class Budget(BaseModel):
    limit_usd: float
    spent_usd: float
    percent: float
    warn_percent: int
    #: Spend has reached the warning threshold.
    warning: bool
    #: Spend has reached the limit and background actions are paused.
    paused: bool
    month_start: str


def month_start(now: datetime) -> str:
    return timestamps.of(
        now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )


def spent_since(conn: sqlite3.Connection, since: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_usage WHERE at >= ?", (since,)
    ).fetchone()
    return float(row[0])


def mean_run_cost(conn: sqlite3.Connection, action: str, since: str) -> float | None:
    """What one run of `action` has cost on average since `since`, or None
    when no fully priced run is on record."""
    row = conn.execute(
        "SELECT AVG(cost) FROM (SELECT SUM(cost_usd) AS cost FROM ai_usage "
        "WHERE action = ? AND at >= ? AND run_id IS NOT NULL "
        "GROUP BY run_id HAVING COUNT(cost_usd) = COUNT(*))",
        (action, since),
    ).fetchone()
    return None if row[0] is None else float(row[0])


def draft_cost(
    conn: sqlite3.Connection, action: str, draft_id: str, since: str
) -> float:
    """What `action` has spent on one draft since `since`."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_usage "
        "WHERE action = ? AND draft_id = ? AND at >= ?",
        (action, draft_id, since),
    ).fetchone()
    return float(row[0])


def budget(
    conn: sqlite3.Connection,
    settings: product_settings.AIBudgetSettings,
    now: datetime | None = None,
) -> Budget | None:
    """This month's spend against the budget, or None when no budget is set."""
    if not settings.monthly_limit_usd:
        return None
    start = month_start(now or datetime.now(UTC))
    spent = spent_since(conn, start)
    percent = spent / settings.monthly_limit_usd * 100
    return Budget(
        limit_usd=settings.monthly_limit_usd,
        spent_usd=round(spent, 6),
        percent=round(percent, 1),
        warn_percent=settings.warn_percent,
        warning=percent >= settings.warn_percent,
        paused=settings.pause_background and percent >= 100,
        month_start=start,
    )


def paused_reason(
    conn: sqlite3.Connection,
    action: str,
    settings: product_settings.AIBudgetSettings,
    now: datetime | None = None,
) -> str | None:
    if action not in BACKGROUND_ACTIONS or not settings.pause_background:
        return None
    status = budget(conn, settings, now)
    if status is None or not status.paused:
        return None
    return (
        "Paused: this month's estimated AI spend has reached the "
        f"${status.limit_usd:g} budget. Raise the budget or turn off pausing "
        "in Settings › AI usage to resume."
    )


def _gate(action: str) -> str | None:
    if action not in BACKGROUND_ACTIONS:
        return None
    settings = product_settings.get(product_settings.AIBudgetSettings)
    return paused_reason(_provider.connection(), action, settings)


class UsageView(BaseModel):
    days: int
    report: Report
    budget: Budget | None


def view(
    conn: sqlite3.Connection,
    settings: product_settings.AIBudgetSettings,
    days: int,
    now: datetime | None = None,
) -> UsageView:
    """The last `days` UTC days including today, and this month's budget."""
    now = now or datetime.now(UTC)
    first = now.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days - 1)
    return UsageView(
        days=days,
        report=report(conn, timestamps.of(first)),
        budget=budget(conn, settings, now),
    )
