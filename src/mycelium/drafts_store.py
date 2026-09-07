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

import json as _json
import sqlite3
import uuid as _uuid
from pathlib import Path
from typing import TypedDict

from . import timestamps
from .connections import ConnectionProvider
from .link_authoring import reject_entity_statement_additions

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
    revision     INTEGER NOT NULL DEFAULT 0,
    source_repository TEXT,
    source_pull_request INTEGER,
    source_merged_commit TEXT,
    source_workflow_run_id INTEGER,
    source_workflow_run_attempt INTEGER,
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
    provenance_json TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    UNIQUE (draft_id, seq)
);
CREATE INDEX IF NOT EXISTS draft_ops_draft ON draft_ops (draft_id);

CREATE TRIGGER IF NOT EXISTS draft_ops_revision_insert
AFTER INSERT ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = NEW.draft_id;
END;
CREATE TRIGGER IF NOT EXISTS draft_ops_revision_update
AFTER UPDATE OF payload_json ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = NEW.draft_id;
END;
CREATE TRIGGER IF NOT EXISTS draft_ops_revision_delete
AFTER DELETE ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = OLD.draft_id;
END;

CREATE TABLE IF NOT EXISTS draft_reviews (
    id                 TEXT PRIMARY KEY,
    draft_id           TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    outcome            TEXT NOT NULL CHECK (
        outcome IN ('accepted', 'refined', 'rejected', 'needs_context')
    ),
    rationale          TEXT NOT NULL,
    draft_revision     INTEGER NOT NULL,
    preconditions_json TEXT NOT NULL,
    unresolved_json    TEXT NOT NULL,
    reviewed_at        TEXT NOT NULL,
    reviewed_by        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS draft_reviews_draft ON draft_reviews (draft_id, reviewed_at);

CREATE TABLE IF NOT EXISTS draft_applications (
    id             TEXT PRIMARY KEY,
    draft_id       TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    review_id      TEXT NOT NULL REFERENCES draft_reviews(id),
    status         TEXT NOT NULL CHECK (status IN ('claimed', 'committed', 'failed')),
    claimed_at     TEXT NOT NULL,
    finished_at    TEXT,
    claimed_by     TEXT NOT NULL,
    result_json    TEXT,
    failure        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS draft_application_active
ON draft_applications (draft_id) WHERE status IN ('claimed', 'committed');
"""

DRAFTS_SOURCE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS drafts_source ON drafts ("
    "created_by, source_repository, source_pull_request, source_merged_commit, "
    "source_workflow_run_id, source_workflow_run_attempt) "
    "WHERE source_repository IS NOT NULL"
)

#: Op kinds that are records for the curator, not tool calls: replay skips them
#: by membership rather than by name-matching scattered through the replayer.
ALIAS_SUGGESTION_KIND = "alias_suggestion"
NON_REPLAYING_OP_KINDS = frozenset({"flag", ALIAS_SUGGESTION_KIND})


class DraftSource(TypedDict):
    repository: str
    pull_request: int
    merged_commit: str
    workflow_run_id: int
    workflow_run_attempt: int


class StaleDraftRevisionError(ValueError):
    pass


class ActiveApplicationError(ValueError):
    pass


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


# --- per-thread connection provider -----------------------------------------
#
# Each thread (a request thread, or a background research-run worker) holds its
# OWN drafts connection, opened lazily against the configured path (see
# `ConnectionProvider`). WAL gives every reader a committed snapshot, so the
# worker finalizing a run and an HTTP thread reading drafts never contend on
# one connection object. `server.init()` calls `configure()` once; unit tests
# pin a single :memory: connection with `use_connection()`.

_provider: ConnectionProvider[str] = ConnectionProvider("drafts", connect)


def configure(db_path: Path | str) -> None:
    """Point the provider at the drafts DB file. Threads (re)open lazily."""
    _provider.configure(str(db_path))


def connection() -> sqlite3.Connection:
    """The calling thread's drafts connection."""
    return _provider.connection()


def use_connection(conn: sqlite3.Connection) -> None:
    """Pin `conn` as this thread's drafts connection (for :memory: / unit tests)."""
    _provider.use(conn)


def reset() -> None:
    """Forget the configured path and this thread's connection (test isolation)."""
    _provider.reset()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(DRAFTS_SCHEMA)
    draft_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()
    }
    additions = {
        "revision": "INTEGER NOT NULL DEFAULT 0",
        "review_assessment_json": "TEXT",
        "review_evidence": "TEXT",
        "source_repository": "TEXT",
        "source_pull_request": "INTEGER",
        "source_merged_commit": "TEXT",
        "source_workflow_run_id": "INTEGER",
        "source_workflow_run_attempt": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in draft_columns:
            conn.execute(f"ALTER TABLE drafts ADD COLUMN {name} {definition}")
    conn.execute(DRAFTS_SOURCE_INDEX)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(draft_ops)").fetchall()
    }
    if "provenance_json" not in columns:
        conn.execute("ALTER TABLE draft_ops ADD COLUMN provenance_json TEXT")
    from . import draft_review_store

    draft_review_store.migrate(conn)
    conn.commit()


def status_for(row: sqlite3.Row | dict) -> str:
    """Derive a draft's status from its terminal timestamps + decision."""
    if row["decided_at"]:
        return row["decision"] or "withdrawn"
    if row["submitted_at"]:
        return "submitted"
    return "open"


# --- helpers used by the @tool redirect path + HTTP API ------------------


def _now() -> str:
    return timestamps.now()


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
    return draft_id


def find_open_session_draft(
    conn: sqlite3.Connection, session_id: str, created_by: str
) -> sqlite3.Row | None:
    """Return `created_by`'s currently-open draft for this MCP session, or
    None if there isn't one yet. Open == submitted_at IS NULL AND
    decided_at IS NULL.

    Matching on the creator as well as the session is what keeps a session
    id from acting as a bearer credential: it is minted by the transport,
    travels in a header, and is not bound to the principal that obtained
    it, so a caller presenting someone else's session id gets their own
    draft rather than write access to that person's."""
    return conn.execute(
        "SELECT * FROM drafts WHERE session_id = ? AND created_by = ? "
        "  AND submitted_at IS NULL AND decided_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id, created_by),
    ).fetchone()


def list_drafts_by_creator(
    conn: sqlite3.Connection, creator: str | None
) -> list[sqlite3.Row]:
    """All drafts created by `creator`, newest first."""
    return conn.execute(
        "SELECT * FROM drafts WHERE created_by = ? ORDER BY created_at DESC",
        (creator,),
    ).fetchall()


_DRAFT_STATUS_FILTERS = {
    "all": "",
    "open": "WHERE submitted_at IS NULL AND decided_at IS NULL",
    "submitted": "WHERE submitted_at IS NOT NULL AND decided_at IS NULL",
    "approved": "WHERE decision = 'approved'",
    "rejected": "WHERE decision = 'rejected'",
    "withdrawn": "WHERE decision = 'withdrawn'",
}


def list_drafts(conn: sqlite3.Connection, status: str = "all") -> list[sqlite3.Row]:
    """All drafts newest first, filtered by review status. Status is virtual
    (see `status_for`): open/submitted derive from the lifecycle timestamps,
    the rest match the recorded decision."""
    where = _DRAFT_STATUS_FILTERS[status]
    return conn.execute(
        f"SELECT * FROM drafts {where} ORDER BY created_at DESC"
    ).fetchall()


def count_ops_by_draft(conn: sqlite3.Connection) -> dict[str, int]:
    """Op counts keyed by draft id, for list views that show totals without
    a per-draft roundtrip."""
    return {
        r["draft_id"]: int(r["n"])
        for r in conn.execute(
            "SELECT draft_id, COUNT(*) AS n FROM draft_ops GROUP BY draft_id"
        ).fetchall()
    }


def get_draft(conn: sqlite3.Connection, draft_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()


def get_draft_snapshot(
    conn: sqlite3.Connection, draft_id: str
) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
    """Read a draft and its operations from one SQLite snapshot."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        row = get_draft(conn, draft_id)
        ops = list_ops(conn, draft_id) if row is not None else []
        return row, ops
    finally:
        if owns_transaction:
            conn.rollback()


def find_draft_by_source(
    conn: sqlite3.Connection, creator: str, source: DraftSource
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM drafts WHERE created_by = ? AND source_repository = ? "
        "AND source_pull_request = ? AND source_workflow_run_id = ? "
        "AND source_workflow_run_attempt = ? AND source_merged_commit = ?",
        (
            creator,
            source["repository"],
            source["pull_request"],
            source["workflow_run_id"],
            source["workflow_run_attempt"],
            source["merged_commit"],
        ),
    ).fetchone()


def _check_revision(row: sqlite3.Row, expected_revision: int | None) -> None:
    if expected_revision is not None and row["revision"] != expected_revision:
        raise StaleDraftRevisionError(
            f"draft revision is {row['revision']}; expected {expected_revision}"
        )


def _check_no_active_application(conn: sqlite3.Connection, draft_id: str) -> None:
    if active_application(conn, draft_id) is not None:
        raise ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )


def set_source(
    conn: sqlite3.Connection,
    draft_id: str,
    source: DraftSource,
    *,
    expected_revision: int | None = None,
) -> int:
    _check_no_active_application(conn, draft_id)
    values = (
        source["repository"],
        source["pull_request"],
        source["merged_commit"],
        source["workflow_run_id"],
        source["workflow_run_attempt"],
    )
    revision_clause = "" if expected_revision is None else " AND revision = ?"
    params: tuple[object, ...] = (*values, draft_id, *values)
    if expected_revision is not None:
        params = (*params, expected_revision)
    cur = conn.execute(
        "UPDATE drafts SET source_repository = ?, source_pull_request = ?, "
        "source_merged_commit = ?, source_workflow_run_id = ?, "
        "source_workflow_run_attempt = ?, revision = revision + 1 WHERE id = ? "
        "AND decided_at IS NULL "
        "AND NOT (source_repository IS ? AND source_pull_request IS ? "
        "AND source_merged_commit IS ? AND source_workflow_run_id IS ? "
        "AND source_workflow_run_attempt IS ?)" + revision_clause,
        params,
    )
    row = get_draft(conn, draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    if cur.rowcount == 0:
        _check_revision(row, expected_revision)
        if row["decided_at"] is not None:
            raise ValueError(f"cannot attach source to a {status_for(row)} draft")
    return int(row["revision"])


def add_op(
    conn: sqlite3.Connection,
    *,
    draft_id: str,
    kind: str,
    payload: dict,
    created_by: str | None,
    provenance: dict | None = None,
) -> int:
    """Append an op to a draft; returns the new seq number. Caller must
    have already verified the draft is open — this function does not
    re-check (callers vary in how they want to report the failure)."""
    _check_no_active_application(conn, draft_id)
    if kind == "add_links":
        reject_entity_statement_additions(payload.get("links"))
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM draft_ops WHERE draft_id = ?",
        (draft_id,),
    ).fetchone()
    seq = int(row["next"])
    op_id = "op_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO draft_ops (id, draft_id, seq, kind, payload_json, "
        "                       provenance_json, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            op_id,
            draft_id,
            seq,
            kind,
            _json.dumps(payload),
            _json.dumps(provenance) if provenance is not None else None,
            _now(),
            created_by,
        ),
    )
    return seq


def list_ops(conn: sqlite3.Connection, draft_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM draft_ops WHERE draft_id = ? ORDER BY seq",
            (draft_id,),
        ).fetchall()
    )


def remove_op(
    conn: sqlite3.Connection,
    draft_id: str,
    seq: int,
    *,
    expected_revision: int | None = None,
) -> int | None:
    _check_no_active_application(conn, draft_id)
    revision_clause = "" if expected_revision is None else " AND revision = ?"
    protected = conn.execute(
        "SELECT kind FROM draft_ops WHERE draft_id = ? AND seq = ?", (draft_id, seq)
    ).fetchone()
    if protected is not None and protected["kind"] == ALIAS_SUGGESTION_KIND:
        raise ValueError(
            "Reject alias suggestions through the alias suggestion review screen."
        )
    params: tuple[object, ...] = (draft_id, seq, draft_id)
    if expected_revision is not None:
        params = (*params, expected_revision)
    cur = conn.execute(
        "DELETE FROM draft_ops WHERE draft_id = ? AND seq = ? AND EXISTS ("
        "SELECT 1 FROM drafts WHERE id = ? AND decided_at IS NULL"
        + revision_clause
        + ")",
        params,
    )
    if cur.rowcount == 0:
        row = get_draft(conn, draft_id)
        if row is not None and expected_revision is not None:
            _check_revision(row, expected_revision)
        return None
    return int(get_draft(conn, draft_id)["revision"])


def remove_op_by_ref(
    conn: sqlite3.Connection,
    draft_id: str,
    operation_ref: str,
    *,
    expected_revision: int | None = None,
) -> int | None:
    revision_clause = "" if expected_revision is None else " AND revision = ?"
    protected = conn.execute(
        "SELECT kind FROM draft_ops WHERE draft_id = ? AND id = ?",
        (draft_id, operation_ref),
    ).fetchone()
    if protected is not None and protected["kind"] == ALIAS_SUGGESTION_KIND:
        raise ValueError(
            "Reject alias suggestions through the alias suggestion review screen."
        )
    params: tuple[object, ...] = (draft_id, operation_ref, draft_id)
    if expected_revision is not None:
        params = (*params, expected_revision)
    cur = conn.execute(
        "DELETE FROM draft_ops WHERE draft_id = ? AND id = ? AND EXISTS ("
        "SELECT 1 FROM drafts WHERE id = ? AND decided_at IS NULL"
        + revision_clause
        + ")",
        params,
    )
    if cur.rowcount == 0:
        row = get_draft(conn, draft_id)
        if row is not None and expected_revision is not None:
            _check_revision(row, expected_revision)
        return None
    return int(get_draft(conn, draft_id)["revision"])


def update_op_payload(
    conn: sqlite3.Connection,
    draft_id: str,
    seq: int,
    payload: dict,
    *,
    expected_revision: int | None = None,
) -> int | None:
    _check_no_active_application(conn, draft_id)
    row = conn.execute(
        "SELECT kind FROM draft_ops WHERE draft_id = ? AND seq = ?",
        (draft_id, seq),
    ).fetchone()
    if row is not None and row["kind"] == ALIAS_SUGGESTION_KIND:
        raise ValueError(
            "Use the alias suggestion review screen to change this operation."
        )
    if row is not None and row["kind"] == "add_links":
        reject_entity_statement_additions(payload.get("links"))
    revision_clause = "" if expected_revision is None else " AND revision = ?"
    params: tuple[object, ...] = (_json.dumps(payload), draft_id, seq, draft_id)
    if expected_revision is not None:
        params = (*params, expected_revision)
    cur = conn.execute(
        "UPDATE draft_ops SET payload_json = ? WHERE draft_id = ? AND seq = ? "
        "AND EXISTS (SELECT 1 FROM drafts WHERE id = ? AND decided_at IS NULL"
        + revision_clause
        + ")",
        params,
    )
    if cur.rowcount == 0:
        draft = get_draft(conn, draft_id)
        if draft is not None and expected_revision is not None:
            _check_revision(draft, expected_revision)
        return None
    return int(get_draft(conn, draft_id)["revision"])


def update_op_payload_by_ref(
    conn: sqlite3.Connection,
    draft_id: str,
    operation_ref: str,
    payload: dict,
    *,
    expected_revision: int | None = None,
) -> int | None:
    row = conn.execute(
        "SELECT kind FROM draft_ops WHERE draft_id = ? AND id = ?",
        (draft_id, operation_ref),
    ).fetchone()
    if row is None:
        draft = get_draft(conn, draft_id)
        if draft is not None:
            _check_revision(draft, expected_revision)
        return None
    if row["kind"] == ALIAS_SUGGESTION_KIND:
        raise ValueError(
            "Use the alias suggestion review screen to change this operation."
        )
    if row["kind"] == "add_links":
        reject_entity_statement_additions(payload.get("links"))
    revision_clause = "" if expected_revision is None else " AND revision = ?"
    params: tuple[object, ...] = (
        _json.dumps(payload),
        draft_id,
        operation_ref,
        draft_id,
    )
    if expected_revision is not None:
        params = (*params, expected_revision)
    cur = conn.execute(
        "UPDATE draft_ops SET payload_json = ? WHERE draft_id = ? AND id = ? "
        "AND EXISTS (SELECT 1 FROM drafts WHERE id = ? AND decided_at IS NULL"
        + revision_clause
        + ")",
        params,
    )
    if cur.rowcount == 0:
        draft = get_draft(conn, draft_id)
        if draft is not None and expected_revision is not None:
            _check_revision(draft, expected_revision)
        return None
    return int(get_draft(conn, draft_id)["revision"])


def set_submitted(conn: sqlite3.Connection, draft_id: str) -> None:
    conn.execute(
        "UPDATE drafts SET submitted_at = ? WHERE id = ? AND submitted_at IS NULL",
        (_now(), draft_id),
    )


def set_decision(
    conn: sqlite3.Connection,
    draft_id: str,
    *,
    decision: str,
    by: str | None,
    application_id: str | None = None,
) -> None:
    from . import (
        alias_suggestions,  # local import: suggestion records depend on this store
    )

    if alias_suggestions.pending(list_ops(conn, draft_id)):
        raise ValueError(
            "Review alias suggestions individually before closing this draft."
        )
    if decision not in ("approved", "rejected", "withdrawn"):
        raise ValueError(f"invalid decision: {decision}")
    active = active_application(conn, draft_id)
    if active is not None and active["id"] != application_id:
        raise ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )
    conn.execute(
        "UPDATE drafts SET decided_at = ?, decided_by = ?, decision = ? "
        "WHERE id = ? AND decided_at IS NULL",
        (_now(), by, decision, draft_id),
    )


def create_review(
    conn: sqlite3.Connection,
    *,
    draft_id: str,
    outcome: str,
    rationale: str,
    draft_revision: int,
    preconditions: list[dict],
    unresolved_questions: list[str],
    reviewed_by: str,
) -> str:
    review_id = "rev_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO draft_reviews (id, draft_id, outcome, rationale, "
        "draft_revision, preconditions_json, unresolved_json, reviewed_at, "
        "reviewed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            review_id,
            draft_id,
            outcome,
            rationale,
            draft_revision,
            _json.dumps(preconditions, sort_keys=True),
            _json.dumps(unresolved_questions),
            _now(),
            reviewed_by,
        ),
    )
    return review_id


def get_review(conn: sqlite3.Connection, review_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM draft_reviews WHERE id = ?", (review_id,)
    ).fetchone()


def list_reviews(conn: sqlite3.Connection, draft_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM draft_reviews WHERE draft_id = ? ORDER BY reviewed_at, rowid",
        (draft_id,),
    ).fetchall()


def list_applications(conn: sqlite3.Connection, draft_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM draft_applications WHERE draft_id = ? ORDER BY claimed_at, rowid",
        (draft_id,),
    ).fetchall()


def active_application(conn: sqlite3.Connection, draft_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM draft_applications WHERE draft_id = ? "
        "AND status IN ('claimed', 'committed') ORDER BY claimed_at DESC LIMIT 1",
        (draft_id,),
    ).fetchone()


def application_for_review(
    conn: sqlite3.Connection, draft_id: str, review_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM draft_applications WHERE draft_id = ? AND review_id = ? "
        "ORDER BY claimed_at DESC LIMIT 1",
        (draft_id, review_id),
    ).fetchone()


def claim_application(
    conn: sqlite3.Connection,
    *,
    draft_id: str,
    review_id: str,
    claimed_by: str,
) -> str:
    active = active_application(conn, draft_id)
    if active is not None:
        if active["review_id"] == review_id:
            return str(active["id"])
        raise ActiveApplicationError(
            f"draft '{draft_id}' already has an active application"
        )
    application_id = "app_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO draft_applications (id, draft_id, review_id, status, "
        "claimed_at, claimed_by) VALUES (?, ?, ?, 'claimed', ?, ?)",
        (application_id, draft_id, review_id, _now(), claimed_by),
    )
    return application_id


def finish_application(
    conn: sqlite3.Connection,
    application_id: str,
    *,
    status: str,
    result: dict | None = None,
    failure: str | None = None,
) -> None:
    conn.execute(
        "UPDATE draft_applications SET status = ?, finished_at = ?, "
        "result_json = ?, failure = COALESCE(?, failure) WHERE id = ?",
        (
            status,
            _now(),
            _json.dumps(result) if result is not None else None,
            failure,
            application_id,
        ),
    )


def note_application_failure(
    conn: sqlite3.Connection, application_id: str, failure: str
) -> None:
    conn.execute(
        "UPDATE draft_applications SET failure = ? WHERE id = ?",
        (failure, application_id),
    )


def serialize_application(row: sqlite3.Row) -> dict:
    return {
        "application_id": row["id"],
        "draft_id": row["draft_id"],
        "review_id": row["review_id"],
        "status": row["status"],
        "claimed_at": row["claimed_at"],
        "finished_at": row["finished_at"],
        "claimed_by": row["claimed_by"],
        "result": _json.loads(row["result_json"]) if row["result_json"] else None,
        "failure": row["failure"],
    }


def serialize_review(row: sqlite3.Row) -> dict:
    return {
        "review_id": row["id"],
        "draft_id": row["draft_id"],
        "outcome": row["outcome"],
        "rationale": row["rationale"],
        "draft_revision": row["draft_revision"],
        "knowledge_preconditions": _json.loads(row["preconditions_json"]),
        "unresolved_questions": _json.loads(row["unresolved_json"]),
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
    }


def serialize_draft(row: sqlite3.Row, *, ops: list[sqlite3.Row] | None = None) -> dict:
    from . import draft_review_store

    out = {
        "review_evidence": row["review_evidence"],
        "review_assessment": draft_review_store.serialized_assessment(
            row["review_assessment_json"], row["revision"]
        ),
        "id": row["id"],
        "title": row["title"],
        "status": status_for(row),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "session_id": row["session_id"],
        "revision": row["revision"],
        "source": (
            {
                "repository": row["source_repository"],
                "pull_request": row["source_pull_request"],
                "merged_commit": row["source_merged_commit"],
                "workflow_run_id": row["source_workflow_run_id"],
                "workflow_run_attempt": row["source_workflow_run_attempt"],
            }
            if row["source_repository"] is not None
            else None
        ),
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
        "operation_ref": row["id"],
        "seq": row["seq"],
        "kind": row["kind"],
        "payload": _json.loads(row["payload_json"]),
        "provenance": (
            _json.loads(row["provenance_json"])
            if row["provenance_json"] is not None
            else None
        ),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }
