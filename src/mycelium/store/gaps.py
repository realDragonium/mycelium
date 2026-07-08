"""Knowledge-gap reports."""

from __future__ import annotations

import sqlite3
import uuid

from .kernel import _now, get_actor

# --- knowledge gaps ---------------------------------------------------------


def create_knowledge_gap(conn: sqlite3.Connection, text: str) -> str:
    """Insert an open knowledge-gap report and return its id. Timestamped
    with the canonical internal format (`timestamps.now()`, millisecond-Z, the
    same one statements use) and stamped with the current actor as
    `created_by`."""
    gap_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO knowledge_gaps (id, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (gap_id, text, now, get_actor()),
    )
    return gap_id


_GAP_STATUS_FILTERS = {
    "all": "",
    "open": "WHERE resolved_at IS NULL AND dismissed_at IS NULL",
    "resolved": "WHERE resolved_at IS NOT NULL",
    "dismissed": "WHERE dismissed_at IS NOT NULL",
}


def list_knowledge_gaps(
    conn: sqlite3.Connection, status: str = "all"
) -> list[sqlite3.Row]:
    """Gap reports newest first. The status column is virtual — derived from
    which terminal timestamp is set — so `status` filters on those."""
    where = _GAP_STATUS_FILTERS[status]
    return conn.execute(
        f"SELECT id, text, created_at, created_by, resolved_at, resolved_by, "
        f"       dismissed_at, dismissed_by "
        f"FROM knowledge_gaps {where} ORDER BY created_at DESC"
    ).fetchall()


def get_knowledge_gap(conn: sqlite3.Connection, gap_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, text, created_at, created_by, resolved_at, resolved_by, "
        "       dismissed_at, dismissed_by FROM knowledge_gaps WHERE id = ?",
        (gap_id,),
    ).fetchone()


def set_knowledge_gap_status(
    conn: sqlite3.Connection, gap_id: str, action: str, actor: str | None
) -> sqlite3.Row:
    """Apply `resolve` / `dismiss` / `reopen` to a gap and return the updated
    row. Resolving clears any dismissal and vice versa; reopening clears both.
    Terminal timestamps use the same canonical format as `created_at`."""
    now = _now()
    if action == "resolve":
        conn.execute(
            "UPDATE knowledge_gaps SET resolved_at = ?, resolved_by = ?, "
            "dismissed_at = NULL, dismissed_by = NULL WHERE id = ?",
            (now, actor, gap_id),
        )
    elif action == "dismiss":
        conn.execute(
            "UPDATE knowledge_gaps SET dismissed_at = ?, dismissed_by = ?, "
            "resolved_at = NULL, resolved_by = NULL WHERE id = ?",
            (now, actor, gap_id),
        )
    elif action == "reopen":
        conn.execute(
            "UPDATE knowledge_gaps SET resolved_at = NULL, resolved_by = NULL, "
            "dismissed_at = NULL, dismissed_by = NULL WHERE id = ?",
            (gap_id,),
        )
    else:
        raise ValueError("action must be one of: resolve, dismiss, reopen")
    return get_knowledge_gap(conn, gap_id)
