"""Documentation-run and generated-document persistence in the drafts database.

Both tables live in the EXISTING drafts DB file (`mycelium-drafts.db`) because
documentation requests and their durable products are draft-side projection
state, not substrate truth. A run records what was asked and what happened; a
document records what currently exists and outlives any one run. Combining
them would make "is there already a page for this topic" depend on filtering
historical outcomes and guessing which run still represents the live page.

State uses terminal timestamps rather than a `status` column: a run is queued
until `started_at`, running until `finished_at`, then document_written,
document_superseded, nothing_written, or failed according to `outcome` and the
document's current `last_run_id`. Supersession is derived at read time because
the stored `outcome` is a closed record of what the run did, and another stored
copy of the same fact could disagree with the document table. `last_run_id` is
a soft reference with deliberately no FK, so a document survives disposable
run history. The guideline set, document type, and slug together are the stable
identity later runs update. A title-derived slug alone is too broad: unrelated
kinds of page routinely choose the same ordinary title. A run whose document
row is absent reads as `document_written`, not `document_superseded`, because
nothing replaced it and its `document_id` simply resolves to nothing. Even the
triple cannot distinguish unrelated same-titled pages within one kind, so a
write that would replace a stored body is refused rather than merged;
replacement is something a caller requests explicitly with `updates=` naming
the document and `replacing=` naming the body it expects to replace. A mistaken
match therefore cannot destroy a body the caller never saw. The refused run
wrote nothing and therefore does not report `document_written`.

Statement ids and the review record are JSON text columns rather than join
tables. They are unqueried snapshots written and read as a whole, so
relationship tables would add schema and queries without serving a lookup.
"""

from __future__ import annotations

import hashlib
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


def body_digest(body: str) -> str:
    """Identify the body a caller believes it is replacing without retaining it."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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


def _document_superseded(row: sqlite3.Row | dict) -> bool:
    """A missing document row is not supersession because nothing replaced it.
    An existing row is superseded when its current writer differs, including no run.

    Gated on the same outcome `status_for` gates on, and the single place that
    decision is made: a run that never wrote cannot lose a page it never owned,
    and a boolean derived apart from the status could contradict it.
    """
    return (
        bool(row["finished_at"])
        and row["outcome"] == "document_written"
        and row["document_id"] is not None
        and bool(row["document_exists"])
        and row["document_last_run_id"] != row["id"]
    )


def status_for(row: sqlite3.Row | dict) -> str:
    """Derive a run's status from its timestamps, outcome, and current document.
    The row must come from `get_run` or `list_runs`.
    """
    required_columns = (
        "finished_at",
        "started_at",
        "outcome",
        "id",
        "document_id",
        "document_exists",
        "document_last_run_id",
    )
    missing_columns = [
        column for column in required_columns if column not in row.keys()
    ]
    if missing_columns:
        raise ValueError(
            f"row is missing required columns: {', '.join(missing_columns)}; "
            "row must come from get_run or list_runs"
        )

    if row["finished_at"]:
        if _document_superseded(row):
            return "document_superseded"
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
        "SELECT r.*, d.id IS NOT NULL AS document_exists, "
        "d.last_run_id AS document_last_run_id "
        "FROM documentation_runs AS r "
        "LEFT JOIN generated_documents AS d ON d.id = r.document_id "
        "WHERE r.id = ?",
        (run_id,),
    ).fetchone()


def list_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT r.*, d.id IS NOT NULL AS document_exists, "
            "d.last_run_id AS document_last_run_id "
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
        "document_superseded": _document_superseded(row),
        "error": row["error"],
    }


def _write_refusal(
    existing: sqlite3.Row | None,
    *,
    identity: tuple[str, str, str],
    body: str,
    run_id: str | None,
    updates: str | None,
    replacing: str | None,
) -> str | None:
    """Why this write must not land, or None when it may.

    The identity rule in one place, decided from values rather than from the
    database, so what counts as losing a body reads as one thing. A caller
    that named this document with a matching body expectation, a body already
    identical, and a new identity are the three ways a write may land.
    """
    guideline_set, document_type, slug = identity
    where = (
        f"(guideline_set={guideline_set!r}, "
        f"document_type={document_type!r}, slug={slug!r})"
    )
    document_id = None if existing is None else str(existing["id"])
    if updates is not None and replacing is None:
        return (
            "document write refused: a deliberate replacement must state the body "
            "it expects to replace; pass replacing=body_digest(stored_body) with "
            f"updates={updates!r}"
        )
    if replacing is not None and updates is None:
        return (
            "document write refused: replacing names an expected body, but without "
            "updates naming a document that expectation cannot be checked"
        )
    if updates is not None and updates != document_id:
        resolved = "no document" if document_id is None else f"document {document_id!r}"
        return (
            f"document write refused: updates={updates!r}, but identity "
            f"{where} resolved to {resolved}"
        )
    if updates is not None and existing is not None:
        # Naming the stored digest here would hand over the very evidence the
        # check exists to demand, so a refusal says only that the expectation
        # is wrong. The document's body is the one place to obtain it.
        if replacing != body_digest(existing["body"]):
            return (
                f"document write refused: document {document_id!r} does not hold "
                f"the body digest {replacing!r} the write expected; read the "
                "document and retry with the digest of what is stored"
            )
    # New identities lose nothing, deliberate updates passed the digest check
    # above, and identical bodies replace nothing.
    if existing is None or updates == document_id or existing["body"] == body:
        return None
    return (
        "document write refused because it would replace a stored body: "
        f"existing document {document_id!r} at identity {where} has "
        f"last_run_id={existing['last_run_id']!r}; the attempting run has "
        f"run_id={run_id!r}. To deliberately replace it, pass "
        f"updates={document_id!r} and replacing=body_digest(stored_body)"
    )


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
    updates: str | None = None,
    replacing: str | None = None,
) -> str:
    """Write content while preserving metadata a partial writer omits.

    Omitted statement ids, review, and run id keep their stored values; explicit
    empty collections still clear them. Guideline set and document type identify
    the page, so omitting them selects the unresolved ``('', '')`` page instead
    of blanking content. This matches `mark_started`'s last-non-null behaviour,
    which the full-replace version of this function contradicted.

    A finer title-derived key still collapses unrelated pages that happen to
    share a title, so replacing another run's body is refused rather than
    merged. New documents and identical bodies need no replacement authority.
    For every deliberate replacement, `updates` says which document and
    `replacing` says which body; the write is refused if the stored body has
    moved on since the caller read it.
    """
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

    # sqlite3's legacy isolation level leaves the read outside a transaction
    # unless one is opened explicitly; another writer must not interleave here.
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT id, body, statement_ids, review, last_run_id "
            "FROM generated_documents "
            "WHERE guideline_set = ? AND document_type = ? AND slug = ?",
            (guideline_set, document_type, slug),
        ).fetchone()
        refusal = _write_refusal(
            existing,
            identity=(guideline_set, document_type, slug),
            body=body,
            run_id=run_id,
            updates=updates,
            replacing=replacing,
        )
        if refusal is not None:
            raise ValueError(refusal)
        now = _now()
        if existing is None:
            document_id = "gdc_" + _uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO generated_documents "
                "(id, slug, title, guideline_set, document_type, body, "
                "statement_ids, review, created_at, updated_at, last_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    slug,
                    title,
                    guideline_set,
                    document_type,
                    body,
                    json.dumps(
                        list(statement_ids) if statement_ids is not None else []
                    ),
                    json.dumps(review if review is not None else {}),
                    now,
                    now,
                    run_id,
                ),
            )
        else:
            document_id = str(existing["id"])
            conn.execute(
                "UPDATE generated_documents "
                "SET title = ?, body = ?, statement_ids = ?, "
                "review = ?, updated_at = ?, last_run_id = ? WHERE id = ?",
                (
                    title,
                    body,
                    existing["statement_ids"]
                    if statement_ids is None
                    else json.dumps(list(statement_ids)),
                    existing["review"] if review is None else json.dumps(review),
                    now,
                    existing["last_run_id"] if run_id is None else run_id,
                    document_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return document_id


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
    """Return the body-less listing shape.

    Generated documents can run to kilobytes, and a caller listing them wants
    to know what exists before fetching one body in full. Run ownership is
    omitted because it does not authorize a replacement; a caller that intends
    to replace a document fetches the body needed for its digest expectation.
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
    }
