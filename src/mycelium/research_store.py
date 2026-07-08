"""Research-run persistence in the drafts database.

The `research_runs` table lives in the EXISTING drafts DB file
(`mycelium-drafts.db`) because a run's only durable product is a draft.
`draft_id` is a soft reference to `drafts.id`, deliberately no FK so run
history survives draft deletion; the substrate DB is off-limits.

State model — terminal-timestamp style, no `status` column:
    queued        — started_at NULL, finished_at NULL
    running       — started_at set,  finished_at NULL
    draft_created / nothing_found / failed — finished_at set, per `outcome`
"""

from __future__ import annotations

import sqlite3
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path


RESEARCH_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    started_at  TEXT,
    finished_at TEXT,
    outcome     TEXT CHECK (outcome IN ('draft_created', 'nothing_found', 'failed')),
    draft_id    TEXT,
    error       TEXT,
    trace_ref   TEXT
);
CREATE INDEX IF NOT EXISTS research_runs_created ON research_runs (created_at);
CREATE INDEX IF NOT EXISTS research_runs_active ON research_runs (started_at) WHERE finished_at IS NULL;
"""

OUTCOMES = ("draft_created", "nothing_found", "failed")


def connect(db_path: Path | str) -> sqlite3.Connection:
    # Same settings as the drafts store — it is the same DB file, and
    # sqlite3.connect's default 5s timeout already covers cross-connection
    # write contention between HTTP threads and run threads.
    from . import drafts_store

    return drafts_store.connect(Path(db_path))


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(RESEARCH_RUNS_SCHEMA)
    conn.commit()


def status_for(row: sqlite3.Row | dict) -> str:
    """Derive a research run's status from timestamps + outcome."""
    if row["finished_at"]:
        return row["outcome"] or "failed"
    if row["started_at"]:
        return "running"
    return "queued"


def _now() -> str:
    return _dt.now(_tz.utc).isoformat()


def create_run(
    conn: sqlite3.Connection,
    *,
    topic: str,
    source: str,
    created_by: str | None,
) -> str:
    run_id = "rrn_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO research_runs (id, topic, source, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, topic, source, _now(), created_by),
    )
    conn.commit()
    return run_id


def mark_started(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "UPDATE research_runs SET started_at = ? WHERE id = ? AND started_at IS NULL",
        (_now(), run_id),
    )
    conn.commit()


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    outcome: str,
    draft_id: str | None = None,
    error: str | None = None,
    trace_ref: str | None = None,
) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    conn.execute(
        "UPDATE research_runs "
        "SET finished_at = ?, outcome = ?, draft_id = ?, error = ?, trace_ref = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (_now(), outcome, draft_id, error, trace_ref, run_id),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM research_runs WHERE id = ?", (run_id,)
    ).fetchone()


def list_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM research_runs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def count_active(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM research_runs "
        "WHERE started_at IS NOT NULL AND finished_at IS NULL"
    ).fetchone()
    return int(row["n"])


def mark_orphaned(conn: sqlite3.Connection) -> int:
    # Called at server startup, when no worker thread can exist — so EVERY
    # unfinished row is an orphan, including one stranded 'queued' by a crash
    # between create_run and mark_started.
    cur = conn.execute(
        "UPDATE research_runs "
        "SET finished_at = ?, outcome = 'failed', error = 'orphaned by restart' "
        "WHERE finished_at IS NULL",
        (_now(),),
    )
    conn.commit()
    return cur.rowcount


def serialize_run(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "topic": row["topic"],
        "source": row["source"],
        "status": status_for(row),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "outcome": row["outcome"],
        "draft_id": row["draft_id"],
        "error": row["error"],
        "trace_ref": row["trace_ref"],
    }
