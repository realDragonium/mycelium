"""Editable prompt texts — instance configuration, not substrate truth.

Steering texts (ingest/research doctrines, ask preambles, server
instructions, guideline sets) are rows here instead of files baked into the
deploy artifact, so editing one is an ordinary tool call and the change
applies to the next run without a restart.

Its own SQLite file (`mycelium-prompts.db`). Not the substrate: prompt texts
are instance config and must never enter the draft pipeline. Not the drafts
DB either: drafts are disposable — wiping them must not take an instance's
prompt configuration with it.

Append-only. A save inserts a row carrying the next `version` for its
(type, name); reads serve the highest version. A delete appends a tombstone
(`deleted = 1`) instead of removing rows, so the full history of a name
survives and the name can be saved again later.

`type` and `name` are free strings — the store never enumerates them.
Consumers declare what they load, so a new sort of steering text is a new
`type` value rather than a code change.

Backup: `backup.py` archives the substrate only; prompt texts are outside it
and join the archive with the media work.
"""

from __future__ import annotations

import sqlite3
import uuid as _uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import timestamps
from .connections import ConnectionProvider

PROMPT_TEXTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_texts (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    text       TEXT NOT NULL,
    deleted    INTEGER NOT NULL DEFAULT 0,
    version    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT,
    UNIQUE (type, name, version)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    # isolation_level=None: `_writing` owns every transaction explicitly, and
    # the driver's legacy auto-BEGIN would leave one open underneath it.
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL + busy timeout, as every other DB in this process: a run thread
    # reading its doctrine can overlap an HTTP thread saving a new version.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# --- per-thread connection provider -----------------------------------------
#
# Each thread holds its OWN prompts connection, opened lazily against the
# configured path (see `ConnectionProvider`). `server.init()` calls
# `configure()` once; unit tests pin a single :memory: connection with
# `use_connection()`.

_provider: ConnectionProvider[str] = ConnectionProvider("prompts", connect)


def configure(db_path: Path | str) -> None:
    """Point the provider at the prompts DB file. Threads (re)open lazily."""
    _provider.configure(str(db_path))


def connection() -> sqlite3.Connection:
    """The calling thread's prompts connection."""
    return _provider.connection()


def use_connection(conn: sqlite3.Connection) -> None:
    """Pin `conn` as this thread's prompts connection (for :memory: / tests)."""
    _provider.use(conn)


def reset() -> None:
    """Forget the configured path and this thread's connection (test isolation)."""
    _provider.reset()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(PROMPT_TEXTS_SCHEMA)
    conn.commit()


@contextmanager
def _writing(conn: sqlite3.Connection) -> Iterator[None]:
    """Own the write transaction for one append.

    BEGIN IMMEDIATE takes the write lock up front, so the reads a write
    depends on (is there a live version? what is the highest one?) see the
    same state the append lands in — another connection's save can't slip
    between the two."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def _key(type: str, name: str) -> tuple[str, str]:
    """Normalize and validate a (type, name) key. Free strings, but not
    blank ones — a nameless text can never be loaded back."""
    type, name = type.strip(), name.strip()
    if not type:
        raise ValueError("type is required")
    if not name:
        raise ValueError("name is required")
    return type, name


def _require_text(text: str) -> str:
    if not text.strip():
        raise ValueError("text is required")
    return text


def _append(
    conn: sqlite3.Connection,
    *,
    type: str,
    name: str,
    text: str,
    deleted: int,
    created_by: str | None,
) -> sqlite3.Row:
    """Insert the next version for (type, name) and return the stored row.
    Call inside `_writing`.

    The version is derived inside the INSERT rather than read first, and
    UNIQUE (type, name, version) is what makes consecutive versions a
    guarantee rather than a hope."""
    row_id = "ptx_" + _uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO prompt_texts "
        "  (id, type, name, text, deleted, version, created_at, created_by) "
        "SELECT ?, ?, ?, ?, ?, COALESCE(MAX(version), 0) + 1, ?, ? "
        "FROM prompt_texts WHERE type = ? AND name = ?",
        (
            row_id,
            type,
            name,
            text,
            deleted,
            timestamps.now(),
            created_by,
            type,
            name,
        ),
    )
    return conn.execute("SELECT * FROM prompt_texts WHERE id = ?", (row_id,)).fetchone()


def save(
    conn: sqlite3.Connection,
    *,
    type: str,
    name: str,
    text: str,
    created_by: str | None = None,
) -> sqlite3.Row:
    """Append a new version of the text stored under (type, name)."""
    type, name = _key(type, name)
    text = _require_text(text)
    with _writing(conn):
        return _append(
            conn, type=type, name=name, text=text, deleted=0, created_by=created_by
        )


def save_if_absent(
    conn: sqlite3.Connection,
    *,
    type: str,
    name: str,
    text: str,
    created_by: str | None = None,
) -> sqlite3.Row | None:
    """Seed (type, name) when it has no live text; return None when one is
    already there. This is what lets a consumer seed its packaged default on
    every startup without ever overwriting an operator's edit — the check
    and the append share one write transaction, so a concurrent save wins
    or loses cleanly rather than being clobbered."""
    type, name = _key(type, name)
    text = _require_text(text)
    with _writing(conn):
        if latest(conn, type, name) is not None:
            return None
        return _append(
            conn, type=type, name=name, text=text, deleted=0, created_by=created_by
        )


def delete(
    conn: sqlite3.Connection,
    *,
    type: str,
    name: str,
    created_by: str | None = None,
) -> bool:
    """Retire (type, name) by appending a tombstone: it stops being listed
    and served, while every earlier version stays readable as history.
    False when there was no live text to retire."""
    type, name = _key(type, name)
    with _writing(conn):
        if latest(conn, type, name) is None:
            return False
        _append(conn, type=type, name=name, text="", deleted=1, created_by=created_by)
    return True


def latest(conn: sqlite3.Connection, type: str, name: str) -> sqlite3.Row | None:
    """The current row for (type, name) — None when the name was never saved
    or its newest version is a tombstone."""
    row = conn.execute(
        "SELECT * FROM prompt_texts WHERE type = ? AND name = ? "
        "ORDER BY version DESC LIMIT 1",
        (type.strip(), name.strip()),
    ).fetchone()
    return None if row is None or row["deleted"] else row


def latest_text(conn: sqlite3.Connection, type: str, name: str) -> str | None:
    """The current text for (type, name). The read consumers do at run start."""
    row = latest(conn, type, name)
    return None if row is None else row["text"]


def history(conn: sqlite3.Connection, type: str, name: str) -> list[sqlite3.Row]:
    """Every version ever written for (type, name), newest first, tombstones
    included."""
    return list(
        conn.execute(
            "SELECT * FROM prompt_texts WHERE type = ? AND name = ? "
            "ORDER BY version DESC",
            (type.strip(), name.strip()),
        ).fetchall()
    )


def list_current(
    conn: sqlite3.Connection, type: str | None = None
) -> list[sqlite3.Row]:
    """The live row for each (type, name), ordered by type then name.
    Retired names are absent; `type` narrows to one type."""
    sql = (
        "SELECT * FROM prompt_texts AS p WHERE deleted = 0 AND version = ("
        "  SELECT MAX(version) FROM prompt_texts "
        "  WHERE type = p.type AND name = p.name"
        ")"
    )
    params: list[str] = []
    if type is not None:
        sql += " AND type = ?"
        params.append(type.strip())
    return list(conn.execute(sql + " ORDER BY type, name", params).fetchall())


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "text": row["text"],
        "version": row["version"],
        "deleted": bool(row["deleted"]),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }


def serialize_summary(row: sqlite3.Row) -> dict:
    """Listing shape: everything but the body. Steering texts run to
    kilobytes, and a caller listing them wants to know what exists."""
    return {
        "type": row["type"],
        "name": row["name"],
        "version": row["version"],
        "chars": len(row["text"]),
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }
