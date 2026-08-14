"""Documentation-run and generated-document persistence in the drafts database.

Both tables live in the EXISTING drafts DB file (`mycelium-drafts.db`) because
documentation requests and their durable products are draft-side projection
state, not substrate truth. A run records what was asked and what happened; a
document records what currently exists and outlives any one run. Combining
them would make "is there already a page for this topic" depend on filtering
historical outcomes and guessing which run still represents the live page.

State uses terminal timestamps rather than a `status` column: a run is queued
until `started_at`, running until `finished_at`, then document_written,
nothing_written, or failed according to `outcome`. `last_run_id` is a soft
reference with deliberately no FK, so a document survives disposable run
history. `slug` is the stable identity later runs update; deciding whether two
topics are the same document belongs to a later issue, not this store.

Statement ids are a JSON text column rather than a join table. They are an
unqueried snapshot written and read as a whole, so a relationship table would
add schema and queries without serving a lookup.
"""

from __future__ import annotations

import json
import sqlite3
import uuid as _uuid
from pathlib import Path

from . import timestamps

DOCUMENTATION_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documentation_runs (
    id            TEXT PRIMARY KEY,
    prompt        TEXT NOT NULL,
    guideline_set TEXT,
    document_type TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    outcome       TEXT CHECK (outcome IN ('document_written', 'nothing_written', 'failed')),
    document_id   TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS documentation_runs_created ON documentation_runs (created_at);
CREATE INDEX IF NOT EXISTS documentation_runs_active ON documentation_runs (started_at) WHERE finished_at IS NULL;
"""

GENERATED_DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS generated_documents (
    id            TEXT PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    guideline_set TEXT,
    document_type TEXT,
    body          TEXT NOT NULL,
    statement_ids TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_run_id   TEXT
);
CREATE INDEX IF NOT EXISTS generated_documents_updated ON generated_documents (updated_at);
"""

OUTCOMES = ("document_written", "nothing_written", "failed")


def connect(db_path: Path | str) -> sqlite3.Connection:
    # Same settings as the drafts store — it is the same DB file.
    from . import drafts_store

    return drafts_store.connect(Path(db_path))


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(DOCUMENTATION_RUNS_SCHEMA)
    conn.executescript(GENERATED_DOCUMENTS_SCHEMA)
    conn.commit()


def status_for(row: sqlite3.Row | dict) -> str:
    """Derive a documentation run's status from timestamps + outcome."""
    if row["finished_at"]:
        return row["outcome"] or "failed"
    if row["started_at"]:
        return "running"
    return "queued"


def _now() -> str:
    return timestamps.now()


def create_run(
    conn: sqlite3.Connection,
    *,
    prompt: str,
    guideline_set: str | None = None,
    document_type: str | None = None,
    created_by: str | None,
) -> str:
    run_id = "drn_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO documentation_runs "
        "(id, prompt, guideline_set, document_type, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, prompt, guideline_set, document_type, _now(), created_by),
    )
    conn.commit()
    return run_id


def mark_started(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
) -> None:
    """Stamp the run as started, and record what it resolved.

    Two callers, in that order, and both are this function because they are
    the same fact arriving in two parts. The executor calls it as it spawns
    the worker, which is what makes the row count against the concurrency
    bound before anything else can be admitted; the run calls it again once it
    has settled which guideline set and document type it is writing against,
    which it cannot know until it has read the prompt.

    So `started_at` is written once (COALESCE keeps the first stamp — the
    moment the run was admitted, not the moment it finished deciding) while
    the two names are last-non-null-wins. A finished run is left alone: its
    outcome is already recorded and nothing may reopen it.
    """
    conn.execute(
        "UPDATE documentation_runs SET started_at = COALESCE(started_at, ?), "
        "guideline_set = COALESCE(?, guideline_set), "
        "document_type = COALESCE(?, document_type) "
        "WHERE id = ? AND finished_at IS NULL",
        (_now(), guideline_set, document_type, run_id),
    )
    conn.commit()


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    outcome: str,
    document_id: str | None = None,
    error: str | None = None,
) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    conn.execute(
        "UPDATE documentation_runs "
        "SET finished_at = ?, outcome = ?, document_id = ?, error = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (_now(), outcome, document_id, error, run_id),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documentation_runs WHERE id = ?", (run_id,)
    ).fetchone()


def list_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM documentation_runs "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def count_active(conn: sqlite3.Connection) -> int:
    """Runs that have started and not finished. The executor's concurrency
    bound is counted from here rather than from live threads, so a restart
    that loses the threads does not also lose the count."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM documentation_runs "
        "WHERE started_at IS NOT NULL AND finished_at IS NULL"
    ).fetchone()
    return int(row["n"])


def mark_orphaned(conn: sqlite3.Connection) -> int:
    # Called at server startup, when no worker thread can exist — so EVERY
    # unfinished row is an orphan, including one stranded 'queued' by a crash
    # between create_run and mark_started.
    cur = conn.execute(
        "UPDATE documentation_runs "
        "SET finished_at = ?, outcome = 'failed', error = 'orphaned by restart' "
        "WHERE finished_at IS NULL",
        (_now(),),
    )
    conn.commit()
    return cur.rowcount


def serialize_run(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "prompt": row["prompt"],
        "guideline_set": row["guideline_set"],
        "document_type": row["document_type"],
        "status": status_for(row),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "outcome": row["outcome"],
        "document_id": row["document_id"],
        "error": row["error"],
    }


def upsert_document(
    conn: sqlite3.Connection,
    *,
    slug: str,
    title: str,
    body: str,
    guideline_set: str | None = None,
    document_type: str | None = None,
    statement_ids: list[str] | None = None,
    run_id: str | None = None,
) -> str:
    slug = slug.strip()
    title = title.strip()
    if not slug:
        raise ValueError("slug is required")
    if not title:
        raise ValueError("title is required")
    document_id = "gdc_" + _uuid.uuid4().hex[:12]
    now = _now()
    conn.execute(
        "INSERT INTO generated_documents "
        "(id, slug, title, guideline_set, document_type, body, statement_ids, "
        "created_at, updated_at, last_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET title = excluded.title, "
        "guideline_set = excluded.guideline_set, "
        "document_type = excluded.document_type, body = excluded.body, "
        "statement_ids = excluded.statement_ids, updated_at = excluded.updated_at, "
        "last_run_id = excluded.last_run_id",
        (
            document_id,
            slug,
            title,
            guideline_set,
            document_type,
            body,
            json.dumps(list(statement_ids) if statement_ids is not None else []),
            now,
            now,
            run_id,
        ),
    )
    row = conn.execute(
        "SELECT id FROM generated_documents WHERE slug = ?", (slug,)
    ).fetchone()
    conn.commit()
    return str(row["id"])


def get_document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM generated_documents WHERE id = ?", (document_id,)
    ).fetchone()


def get_document_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM generated_documents WHERE slug = ?", (slug,)
    ).fetchone()


def list_documents(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM generated_documents "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def _statement_ids(row: sqlite3.Row) -> list[str]:
    return json.loads(row["statement_ids"])


def serialize_document(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "guideline_set": row["guideline_set"],
        "document_type": row["document_type"],
        "body": row["body"],
        "statement_ids": _statement_ids(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_run_id": row["last_run_id"],
    }


def serialize_document_summary(row: sqlite3.Row) -> dict:
    """Return the listing shape: everything but the body.

    Generated documents can run to kilobytes, and a caller listing them wants
    to know what exists before fetching one body in full.
    """
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "guideline_set": row["guideline_set"],
        "document_type": row["document_type"],
        "chars": len(row["body"]),
        "statement_ids": _statement_ids(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_run_id": row["last_run_id"],
    }
