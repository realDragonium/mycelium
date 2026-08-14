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
history. The guideline set, document type, and slug together are the stable
identity later runs update. A title-derived slug alone is too broad: unrelated
kinds of page routinely choose the same ordinary title.

Statement ids and the review record are JSON text columns rather than join
tables. They are unqueried snapshots written and read as a whole, so
relationship tables would add schema and queries without serving a lookup.
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
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    guideline_set TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL,
    statement_ids TEXT NOT NULL DEFAULT '[]',
    review        TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_run_id   TEXT
);
CREATE INDEX IF NOT EXISTS generated_documents_updated ON generated_documents (updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS generated_documents_identity
    ON generated_documents (guideline_set, document_type, slug);
"""

OUTCOMES = ("document_written", "nothing_written", "failed")


def connect(db_path: Path | str) -> sqlite3.Connection:
    # Same settings as the drafts store — it is the same DB file.
    from . import drafts_store

    return drafts_store.connect(Path(db_path))


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(DOCUMENTATION_RUNS_SCHEMA)
    conn.executescript(GENERATED_DOCUMENTS_SCHEMA)
    _add_generated_document_review(conn)
    _rekey_generated_documents(conn)
    conn.commit()


def _add_generated_document_review(conn: sqlite3.Connection) -> None:
    """Add `generated_documents.review` to a DB created before it existed.

    The schema script only runs CREATE TABLE IF NOT EXISTS, so an existing
    drafts DB keeps its old column set and every later document write would
    fail despite the column appearing in the script.

    Rows written before the upgrade read as `{}`: no review record was kept
    for that page. This is deliberately not represented as a passing review.
    """
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(generated_documents)")
    }
    if "review" not in columns:
        conn.execute(
            "ALTER TABLE generated_documents "
            "ADD COLUMN review TEXT NOT NULL DEFAULT '{}'"
        )


def _rekey_generated_documents(conn: sqlite3.Connection) -> None:
    """Replace the old slug-only key with the document's full identity.

    SQLite cannot remove the table-level UNIQUE constraint or make the two
    identity columns non-null in place, so deployed tables need rebuilding.
    The copy cannot encounter a duplicate under the new key: a triple is a
    strictly finer identity than slug alone, and every legacy slug was unique.
    """
    slug_only_unique = False
    for index in conn.execute("PRAGMA index_list(generated_documents)"):
        if index["unique"] != 1 or index["origin"] != "u":
            continue
        index_name = '"' + index["name"].replace('"', '""') + '"'
        columns = [
            row["name"] for row in conn.execute(f"PRAGMA index_info({index_name})")
        ]
        if columns == ["slug"]:
            slug_only_unique = True
            break

    # Matching only SQLite's table-constraint origin makes this idempotent:
    # the replacement identity index is explicitly created and has origin 'c'.
    if not slug_only_unique:
        return

    # sqlite3's legacy isolation level lets DDL autocommit unless a transaction
    # is opened explicitly; losing the old table halfway through is not safe.
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE generated_documents_rekeyed (
                id            TEXT PRIMARY KEY,
                slug          TEXT NOT NULL,
                title         TEXT NOT NULL,
                guideline_set TEXT NOT NULL DEFAULT '',
                document_type TEXT NOT NULL DEFAULT '',
                body          TEXT NOT NULL,
                statement_ids TEXT NOT NULL DEFAULT '[]',
                review        TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                last_run_id   TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO generated_documents_rekeyed
                (id, slug, title, guideline_set, document_type, body,
                 statement_ids, review, created_at, updated_at, last_run_id)
            SELECT id, slug, title, COALESCE(guideline_set, ''),
                   COALESCE(document_type, ''), body, statement_ids, review,
                   created_at, updated_at, last_run_id
            FROM generated_documents
            """
        )
        conn.execute("DROP TABLE generated_documents")
        conn.execute(
            "ALTER TABLE generated_documents_rekeyed RENAME TO generated_documents"
        )
        conn.execute(
            "CREATE INDEX generated_documents_updated "
            "ON generated_documents (updated_at)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX generated_documents_identity "
            "ON generated_documents (guideline_set, document_type, slug)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
        "SELECT r.*, d.last_run_id AS document_last_run_id "
        "FROM documentation_runs AS r "
        "LEFT JOIN generated_documents AS d ON d.id = r.document_id "
        "WHERE r.id = ?",
        (run_id,),
    ).fetchone()


def list_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT r.*, d.last_run_id AS document_last_run_id "
            "FROM documentation_runs AS r "
            "LEFT JOIN generated_documents AS d ON d.id = r.document_id "
            "ORDER BY r.created_at DESC, r.id DESC LIMIT ?",
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
    """Serialize a run while deriving whether its document was superseded.

    Finished run rows are closed, so replacement cannot be copied back onto
    them. Reading the document's current writer also keeps that fact in one
    place instead of maintaining two rows that could disagree.
    """
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
        "document_superseded": row["document_id"] is not None
        and row["document_last_run_id"] != row["id"],
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
    review: dict | None = None,
    run_id: str | None = None,
) -> str:
    slug = slug.strip()
    title = title.strip()
    if not slug:
        raise ValueError("slug is required")
    if not title:
        raise ValueError("title is required")
    if guideline_set is None:
        guideline_set = ""
    if document_type is None:
        document_type = ""
    document_id = "gdc_" + _uuid.uuid4().hex[:12]
    now = _now()
    conn.execute(
        "INSERT INTO generated_documents "
        "(id, slug, title, guideline_set, document_type, body, statement_ids, "
        "review, created_at, updated_at, last_run_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(guideline_set, document_type, slug) DO UPDATE SET "
        "title = excluded.title, body = excluded.body, "
        "statement_ids = excluded.statement_ids, review = excluded.review, "
        "updated_at = excluded.updated_at, last_run_id = excluded.last_run_id",
        (
            document_id,
            slug,
            title,
            guideline_set,
            document_type,
            body,
            json.dumps(list(statement_ids) if statement_ids is not None else []),
            json.dumps(review if review is not None else {}),
            now,
            now,
            run_id,
        ),
    )
    row = conn.execute(
        "SELECT id FROM generated_documents "
        "WHERE guideline_set = ? AND document_type = ? AND slug = ?",
        (guideline_set, document_type, slug),
    ).fetchone()
    conn.commit()
    return str(row["id"])


def get_document(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM generated_documents WHERE id = ?", (document_id,)
    ).fetchone()


def get_document_by_slug(
    conn: sqlite3.Connection,
    slug: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
) -> sqlite3.Row | None:
    """Find a slug, optionally narrowed by either part of its full identity.

    Slugs are no longer unique. The unfiltered fallback is explicitly the
    most recently updated match so older callers get a stable, useful answer
    instead of whichever row SQLite happens to visit first.
    """
    clauses = ["slug = ?"]
    parameters = [slug]
    if guideline_set is not None:
        clauses.append("guideline_set = ?")
        parameters.append(guideline_set)
    if document_type is not None:
        clauses.append("document_type = ?")
        parameters.append(document_type)
    return conn.execute(
        "SELECT * FROM generated_documents WHERE "
        + " AND ".join(clauses)
        + " ORDER BY updated_at DESC, id DESC LIMIT 1",
        parameters,
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


def _review(row: sqlite3.Row) -> dict:
    return json.loads(row["review"])


def serialize_document(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "guideline_set": row["guideline_set"],
        "document_type": row["document_type"],
        "body": row["body"],
        "statement_ids": _statement_ids(row),
        "review": _review(row),
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
        "review": _review(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_run_id": row["last_run_id"],
    }
