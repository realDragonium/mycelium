"""Drafts database — separate SQLite file from the substrate.

A draft is a queue of substrate operations a drafter (or anyone passing
an explicit `draft_id`) wants to apply. The substrate isn't touched
until a curator approves the draft, at which point the ops are replayed
all-or-nothing as the curator's principal.

Why a separate file: drafts are pending, possibly-incorrect work. Keeping
them off the substrate means a snapshot/restore of the substrate doesn't
carry half-applied drafts, and a wipe of drafts (e.g. after a bad batch)
doesn't risk the live KB.

State model — terminal-timestamp style, no `status` column. A draft's
status is derived from which timestamp is set:
    open      — submitted_at, decided_at all NULL
    submitted — submitted_at set, decided_at NULL
    approved  — decided_at set, decision = 'approved'
    rejected  — decided_at set, decision = 'rejected'
    withdrawn — decided_at set, decision = 'withdrawn'
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DRAFTS_SCHEMA = """
-- A drafter's pending change set. One open draft per MCP session;
-- additional drafts arrive via explicit start (not in v1) or by the
-- prior open one being submitted.
CREATE TABLE IF NOT EXISTS drafts (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    session_id   TEXT,
    submitted_at TEXT,
    decided_at   TEXT,
    decided_by   TEXT,
    decision     TEXT CHECK (decision IN ('approved', 'rejected', 'withdrawn'))
);
CREATE INDEX IF NOT EXISTS drafts_session ON drafts (session_id);
CREATE INDEX IF NOT EXISTS drafts_creator ON drafts (created_by);

-- Each queued tool call as one row. `kind` matches the substrate tool's
-- function name (e.g. 'upsert_statement'). `payload_json` carries the
-- kwargs the tool would have been called with (minus `draft_id`). `seq`
-- is per-draft and assigned monotonically — used both for ordering at
-- approve-time and as the addressable handle for removing/editing an op.
CREATE TABLE IF NOT EXISTS draft_ops (
    id           TEXT PRIMARY KEY,
    draft_id     TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    UNIQUE (draft_id, seq)
);
CREATE INDEX IF NOT EXISTS draft_ops_draft ON draft_ops (draft_id);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + a busy timeout so the drafts DB tolerates a background writer: a
    # research run finalizes its row and queues its draft ops from a worker
    # thread while HTTP threads read/write the same file. Mirrors store.py,
    # which set this for the mention-recompute worker. (No-op on :memory:.)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(DRAFTS_SCHEMA)
    conn.commit()


def status_for(row: sqlite3.Row | dict) -> str:
    """Derive a draft's status from its terminal timestamps + decision."""
    if row["decided_at"]:
        return row["decision"] or "withdrawn"
    if row["submitted_at"]:
        return "submitted"
    return "open"


# --- helpers used by the @tool redirect path + HTTP API ------------------

import json as _json
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz


def _now() -> str:
    return _dt.now(_tz.utc).isoformat()


def create_draft(
    conn: sqlite3.Connection,
    *,
    created_by: str | None,
    session_id: str | None,
    title: str | None = None,
) -> str:
    draft_id = "drf_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO drafts (id, title, created_at, created_by, session_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (draft_id, title, _now(), created_by, session_id),
    )
    conn.commit()
    return draft_id


def find_open_session_draft(
    conn: sqlite3.Connection, session_id: str
) -> sqlite3.Row | None:
    """Return the drafter's currently-open draft for this MCP session,
    or None if there isn't one yet. Open == submitted_at IS NULL AND
    decided_at IS NULL."""
    return conn.execute(
        "SELECT * FROM drafts WHERE session_id = ? "
        "  AND submitted_at IS NULL AND decided_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()


def get_draft(conn: sqlite3.Connection, draft_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()


def add_op(
    conn: sqlite3.Connection,
    *,
    draft_id: str,
    kind: str,
    payload: dict,
    created_by: str | None,
) -> int:
    """Append an op to a draft; returns the new seq number. Caller must
    have already verified the draft is open — this function does not
    re-check (callers vary in how they want to report the failure)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM draft_ops WHERE draft_id = ?",
        (draft_id,),
    ).fetchone()
    seq = int(row["next"])
    op_id = "op_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO draft_ops (id, draft_id, seq, kind, payload_json, "
        "                       created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (op_id, draft_id, seq, kind, _json.dumps(payload), _now(), created_by),
    )
    conn.commit()
    return seq


def list_ops(conn: sqlite3.Connection, draft_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM draft_ops WHERE draft_id = ? ORDER BY seq",
            (draft_id,),
        ).fetchall()
    )


def remove_op(conn: sqlite3.Connection, draft_id: str, seq: int) -> bool:
    cur = conn.execute(
        "DELETE FROM draft_ops WHERE draft_id = ? AND seq = ?",
        (draft_id, seq),
    )
    conn.commit()
    return cur.rowcount > 0


def update_op_payload(
    conn: sqlite3.Connection, draft_id: str, seq: int, payload: dict
) -> bool:
    cur = conn.execute(
        "UPDATE draft_ops SET payload_json = ? WHERE draft_id = ? AND seq = ?",
        (_json.dumps(payload), draft_id, seq),
    )
    conn.commit()
    return cur.rowcount > 0


def set_submitted(conn: sqlite3.Connection, draft_id: str) -> None:
    conn.execute(
        "UPDATE drafts SET submitted_at = ? WHERE id = ? AND submitted_at IS NULL",
        (_now(), draft_id),
    )
    conn.commit()


def set_decision(
    conn: sqlite3.Connection, draft_id: str, *, decision: str, by: str | None
) -> None:
    if decision not in ("approved", "rejected", "withdrawn"):
        raise ValueError(f"invalid decision: {decision}")
    conn.execute(
        "UPDATE drafts SET decided_at = ?, decided_by = ?, decision = ? "
        "WHERE id = ? AND decided_at IS NULL",
        (_now(), by, decision, draft_id),
    )
    conn.commit()


def serialize_draft(row: sqlite3.Row, *, ops: list[sqlite3.Row] | None = None) -> dict:
    out = {
        "id": row["id"],
        "title": row["title"],
        "status": status_for(row),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "session_id": row["session_id"],
        "submitted_at": row["submitted_at"],
        "decided_at": row["decided_at"],
        "decided_by": row["decided_by"],
        "decision": row["decision"],
    }
    if ops is not None:
        out["ops"] = [serialize_op(o) for o in ops]
    return out


def serialize_op(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "seq": row["seq"],
        "kind": row["kind"],
        "payload": _json.loads(row["payload_json"]),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }
