"""Audience labels on statements and the queue the labelling worker drains.

A statement's label is the set of documentation audiences that may see it.
No label means unlabelled, which fails closed: only internal audiences see
it. Audience ids are owned by the prompts database (`mycelium.audiences`).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from .kernel import _now

Source = Literal["ai", "curator"]

#: Attempts before a failing statement waits for the next backfill.
MAX_ATTEMPTS = 5
_BACKOFF = timedelta(minutes=1)


def visibility_clause(audience_id: str, internal: bool) -> tuple[str, tuple[str]]:
    """SQL over `statements s LEFT JOIN statement_audience_labels l`: whether
    `s` is visible to the audience."""
    granted = "EXISTS (SELECT 1 FROM json_each(l.audiences) WHERE value = ?)"
    if internal:
        return f"(l.statement_id IS NULL OR {granted})", (audience_id,)
    return f"(l.statement_id IS NOT NULL AND {granted})", (audience_id,)


def visible_statement_ids(
    conn: sqlite3.Connection, audience_id: str, internal: bool
) -> frozenset[str]:
    clause, params = visibility_clause(audience_id, internal)
    return frozenset(
        str(row["id"])
        for row in conn.execute(
            "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
            f"ON l.statement_id = s.id WHERE {clause}",
            params,
        )
    )


def visible_among(
    conn: sqlite3.Connection,
    audience_id: str,
    internal: bool,
    statement_ids: Sequence[str],
) -> frozenset[str]:
    """Which of `statement_ids` the audience may see."""
    clause, params = visibility_clause(audience_id, internal)
    visible: set[str] = set()
    for offset in range(0, len(statement_ids), 500):
        chunk = list(statement_ids[offset : offset + 500])
        placeholders = ", ".join("?" for _ in chunk)
        visible.update(
            str(row["id"])
            for row in conn.execute(
                "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
                f"ON l.statement_id = s.id WHERE s.id IN ({placeholders}) AND {clause}",
                (*chunk, *params),
            )
        )
    return frozenset(visible)


def awaiting_label(
    conn: sqlite3.Connection, statement_ids: Sequence[str]
) -> frozenset[str]:
    """Which of `statement_ids` are queued with attempts left, so a label is
    still coming."""
    awaiting: set[str] = set()
    for offset in range(0, len(statement_ids), 500):
        chunk = list(statement_ids[offset : offset + 500])
        placeholders = ", ".join("?" for _ in chunk)
        awaiting.update(
            str(row["statement_id"])
            for row in conn.execute(
                "SELECT statement_id FROM audience_label_queue "
                f"WHERE statement_id IN ({placeholders}) AND attempts < ?",
                (*chunk, MAX_ATTEMPTS),
            )
        )
    return frozenset(awaiting)


def get_label(conn: sqlite3.Connection, statement_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM statement_audience_labels WHERE statement_id = ?",
        (statement_id,),
    ).fetchone()
    return row


def label_audiences(row: sqlite3.Row) -> list[str]:
    value = json.loads(row["audiences"])
    return [str(item) for item in value] if isinstance(value, list) else []


def set_label(
    conn: sqlite3.Connection,
    statement_id: str,
    audiences: Sequence[str],
    *,
    source: Source,
    reason: str,
    model: str | None = None,
    cost_usd: float | None = None,
    labelled_by: str | None = None,
) -> None:
    """Replace the statement's label. The caller decides whether an AI label
    may replace what is there; see `apply_ai_label`."""
    conn.execute(
        "INSERT INTO statement_audience_labels "
        "(statement_id, audiences, source, reason, model, cost_usd, labelled_at, labelled_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(statement_id) DO UPDATE SET "
        "audiences = excluded.audiences, source = excluded.source, "
        "reason = excluded.reason, model = excluded.model, "
        "cost_usd = excluded.cost_usd, labelled_at = excluded.labelled_at, "
        "labelled_by = excluded.labelled_by, text_changed_at = NULL",
        (
            statement_id,
            json.dumps(sorted(set(audiences))),
            source,
            reason,
            model,
            cost_usd,
            _now(),
            labelled_by,
        ),
    )
    conn.execute(
        "DELETE FROM audience_label_queue WHERE statement_id = ?", (statement_id,)
    )


def apply_ai_label(
    conn: sqlite3.Connection,
    statement_id: str,
    audiences: Sequence[str],
    *,
    reason: str,
    model: str,
    cost_usd: float | None,
) -> bool:
    """Store an AI label unless a curator has decided. False when skipped."""
    current = get_label(conn, statement_id)
    if current is not None and current["source"] == "curator":
        conn.execute(
            "DELETE FROM audience_label_queue WHERE statement_id = ?", (statement_id,)
        )
        return False
    set_label(
        conn,
        statement_id,
        audiences,
        source="ai",
        reason=reason,
        model=model,
        cost_usd=cost_usd,
    )
    return True


def clear_label(conn: sqlite3.Connection, statement_id: str) -> None:
    """Drop the label and queue the statement to be labelled again."""
    conn.execute(
        "DELETE FROM statement_audience_labels WHERE statement_id = ?",
        (statement_id,),
    )
    enqueue(conn, [statement_id])


def confirm_label(
    conn: sqlite3.Connection, statement_id: str, *, labelled_by: str | None
) -> bool:
    """A curator re-decides their label unchanged after a text change. False
    when the statement has no curator label."""
    cursor = conn.execute(
        "UPDATE statement_audience_labels SET text_changed_at = NULL, "
        "labelled_at = ?, labelled_by = ? WHERE statement_id = ? AND source = 'curator'",
        (_now(), labelled_by, statement_id),
    )
    return cursor.rowcount > 0


def text_changed(conn: sqlite3.Connection, statement_id: str) -> None:
    """A statement's text changed: its AI label no longer describes it, and
    a curator label is kept but marked for the curator to look at again."""
    conn.execute(
        "DELETE FROM statement_audience_labels WHERE statement_id = ? AND source = 'ai'",
        (statement_id,),
    )
    conn.execute(
        "UPDATE statement_audience_labels SET text_changed_at = ? "
        "WHERE statement_id = ? AND text_changed_at IS NULL",
        (_now(), statement_id),
    )
    if get_label(conn, statement_id) is None:
        enqueue(conn, [statement_id])


def enqueue(conn: sqlite3.Connection, statement_ids: Sequence[str]) -> None:
    """Queue statements for labelling, re-arming any that exhausted retries."""
    now = _now()
    conn.executemany(
        "INSERT INTO audience_label_queue (statement_id, enqueued_at) VALUES (?, ?) "
        "ON CONFLICT(statement_id) DO UPDATE SET attempts = 0, "
        "next_attempt_at = NULL, last_error = NULL",
        [(statement_id, now) for statement_id in statement_ids],
    )


def enqueue_backfill(conn: sqlite3.Connection, *, relabel_ai: bool) -> int:
    """Queue every unlabelled statement, and AI-labelled ones when
    `relabel_ai`. Curator labels are never queued. Returns how many."""
    condition = (
        "l.statement_id IS NULL OR l.source = 'ai'"
        if relabel_ai
        else "l.statement_id IS NULL"
    )
    ids = [
        str(row["id"])
        for row in conn.execute(
            "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
            f"ON l.statement_id = s.id WHERE {condition} ORDER BY s.id"
        )
    ]
    enqueue(conn, ids)
    return len(ids)


def due_batch(
    conn: sqlite3.Connection, limit: int, now: datetime | None = None
) -> list[sqlite3.Row]:
    """Queued statements ready for an attempt, oldest first, with their text."""
    at = (now or datetime.now(UTC)).isoformat()
    return list(
        conn.execute(
            "SELECT s.id, s.kind, s.text FROM audience_label_queue q "
            "JOIN statements s ON s.id = q.statement_id "
            "WHERE q.attempts < ? AND (q.next_attempt_at IS NULL OR q.next_attempt_at <= ?) "
            "ORDER BY q.enqueued_at, q.statement_id LIMIT ?",
            (MAX_ATTEMPTS, at, limit),
        )
    )


def record_failure(
    conn: sqlite3.Connection,
    statement_ids: Sequence[str],
    error: str,
    now: datetime | None = None,
) -> None:
    at = now or datetime.now(UTC)
    for statement_id in statement_ids:
        row = conn.execute(
            "SELECT attempts FROM audience_label_queue WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()
        if row is None:
            continue
        attempts = int(row["attempts"]) + 1
        conn.execute(
            "UPDATE audience_label_queue SET attempts = ?, next_attempt_at = ?, "
            "last_error = ? WHERE statement_id = ?",
            (
                attempts,
                (at + _BACKOFF * (1 << (attempts - 1))).isoformat(),
                error[:500],
                statement_id,
            ),
        )


def queue_counts(conn: sqlite3.Connection) -> tuple[int, int, str | None]:
    """(waiting, failed, last error)."""
    row = conn.execute(
        "SELECT SUM(attempts < ?) AS waiting, SUM(attempts >= ?) AS failed "
        "FROM audience_label_queue",
        (MAX_ATTEMPTS, MAX_ATTEMPTS),
    ).fetchone()
    error = conn.execute(
        "SELECT last_error FROM audience_label_queue WHERE last_error IS NOT NULL "
        "ORDER BY next_attempt_at DESC LIMIT 1"
    ).fetchone()
    return (
        int(row["waiting"] or 0),
        int(row["failed"] or 0),
        str(error["last_error"]) if error is not None else None,
    )
