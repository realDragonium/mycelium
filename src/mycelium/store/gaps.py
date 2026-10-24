"""Knowledge-gap reports."""

from __future__ import annotations

import sqlite3
import uuid

from .kernel import _now, get_actor

# --- knowledge gaps ---------------------------------------------------------


def create_knowledge_gap(
    conn: sqlite3.Connection,
    text: str,
    *,
    draft_id: str | None = None,
    statement_id: str | None = None,
    document_id: str | None = None,
) -> str:
    """Insert an open knowledge-gap report and return its id. Timestamped
    with the canonical internal format (`timestamps.now()`, millisecond-Z, the
    same one statements use) and stamped with the current actor as
    `created_by`. The ids name what the report came from, when known."""
    gap_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO knowledge_gaps (id, text, created_at, created_by, "
        "draft_id, statement_id, document_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (gap_id, text, now, get_actor(), draft_id, statement_id, document_id),
    )
    return gap_id


def resolve_draft_gaps(
    conn: sqlite3.Connection, draft_id: str, actor: str | None
) -> int:
    """Resolve the open reports filed about `draft_id` and return how many
    there were."""
    cursor = conn.execute(
        "UPDATE knowledge_gaps SET resolved_at = ?, resolved_by = ? "
        "WHERE draft_id = ? AND resolved_at IS NULL AND dismissed_at IS NULL",
        (_now(), actor, draft_id),
    )
    return cursor.rowcount


#: The reason a curation agent gave when it resolved or dismissed the gap
#: and the gap still stands as it left it.
_CLOSING_REASON = (
    "(SELECT c.reason FROM curation_attempts c WHERE c.item_id = knowledge_gaps.id "
    "AND c.outcome IN ('resolved', 'not_applicable') "
    "AND c.attempted_by = COALESCE(knowledge_gaps.resolved_by, "
    "knowledge_gaps.dismissed_by)) AS closing_reason"
)
_GAP_COLUMNS = (
    "id, text, created_at, created_by, resolved_at, resolved_by, "
    "dismissed_at, dismissed_by, draft_id, statement_id, document_id, "
    + _CLOSING_REASON
)

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
        f"SELECT {_GAP_COLUMNS} FROM knowledge_gaps {where} ORDER BY created_at DESC"
    ).fetchall()


def get_knowledge_gap(conn: sqlite3.Connection, gap_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        f"SELECT {_GAP_COLUMNS} FROM knowledge_gaps WHERE id = ?", (gap_id,)
    ).fetchone()
    return row


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
    row = get_knowledge_gap(conn, gap_id)
    if row is None:
        raise ValueError(f"knowledge gap not found: {gap_id}")
    return row
