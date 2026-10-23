"""Media items, their bytes and what they are attached to.

Its own SQLite file (`mycelium-media.db`), so the substrate stays small and a
backup can leave media out. Attachments name statements and concepts by id,
as anchors in the drafts database do; the server moves or clears them when a
statement or concept is merged or deleted.

The bytes sit behind `Blobs`, so moving them to object storage replaces
`SqliteBlobs` and nothing else.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from .connections import ConnectionProvider

DB_NAME = "mycelium-media.db"

Origin = Literal["uploaded", "agent", "captured"]
TargetKind = Literal["statement", "entity"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_items (
    id                  TEXT PRIMARY KEY,
    content_type        TEXT NOT NULL,
    byte_size           INTEGER NOT NULL,
    sha256              TEXT NOT NULL,
    content_version     INTEGER NOT NULL DEFAULT 1,
    content_updated_at  TEXT NOT NULL,
    alt_text            TEXT NOT NULL DEFAULT '',
    caption             TEXT NOT NULL DEFAULT '',
    origin              TEXT NOT NULL CHECK (origin IN ('uploaded', 'agent', 'captured')),
    source_url          TEXT,
    product_version     TEXT,
    captured_at         TEXT,
    audiences           TEXT,
    labelled_by         TEXT,
    labelled_at         TEXT,
    content_changed_at  TEXT,
    created_at          TEXT NOT NULL,
    created_by          TEXT,
    updated_at          TEXT NOT NULL,
    updated_by          TEXT
);
CREATE TABLE IF NOT EXISTS media_blobs (
    media_id TEXT PRIMARY KEY REFERENCES media_items(id) ON DELETE CASCADE,
    data     BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS media_attachments (
    media_id    TEXT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('statement', 'entity')),
    target_id   TEXT NOT NULL,
    attached_at TEXT NOT NULL,
    attached_by TEXT,
    PRIMARY KEY (media_id, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS media_attachments_target
    ON media_attachments (target_kind, target_id);
CREATE TABLE IF NOT EXISTS media_uploads (
    token_hash    TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_provider: ConnectionProvider[str] = ConnectionProvider("media", connect)


def configure(db_path: Path | str) -> None:
    _provider.configure(str(db_path))


def connection() -> sqlite3.Connection:
    """The calling thread's media connection."""
    return _provider.connection()


def is_configured() -> bool:
    return _provider.is_configured()


def use_connection(conn: sqlite3.Connection) -> None:
    """Pin `conn` as this thread's media connection (for :memory: / tests)."""
    _provider.use(conn)


def reset() -> None:
    _provider.reset()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class Blobs(Protocol):
    def put(self, conn: sqlite3.Connection, media_id: str, data: bytes) -> None: ...

    def get(self, conn: sqlite3.Connection, media_id: str) -> bytes | None: ...


class SqliteBlobs:
    """Bytes in the media database itself, inside the caller's transaction.
    Deleting an item cascades to its bytes."""

    def put(self, conn: sqlite3.Connection, media_id: str, data: bytes) -> None:
        conn.execute(
            "INSERT INTO media_blobs (media_id, data) VALUES (?, ?) "
            "ON CONFLICT(media_id) DO UPDATE SET data = excluded.data",
            (media_id, data),
        )

    def get(self, conn: sqlite3.Connection, media_id: str) -> bytes | None:
        row = conn.execute(
            "SELECT data FROM media_blobs WHERE media_id = ?", (media_id,)
        ).fetchone()
        return None if row is None else bytes(row["data"])


blobs: Blobs = SqliteBlobs()


def get(conn: sqlite3.Connection, media_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM media_items WHERE id = ?", (media_id,)
    ).fetchone()
    return row


def get_many(conn: sqlite3.Connection, media_ids: Iterable[str]) -> list[sqlite3.Row]:
    wanted = sorted(set(media_ids))
    rows: list[sqlite3.Row] = []
    for offset in range(0, len(wanted), 500):
        chunk = wanted[offset : offset + 500]
        rows.extend(
            conn.execute(
                "SELECT * FROM media_items WHERE id IN "
                f"({', '.join('?' for _ in chunk)})",
                chunk,
            )
        )
    return rows


def label(row: sqlite3.Row) -> list[str] | None:
    """The audiences a curator granted, or None while unlabelled."""
    raw = row["audiences"]
    if raw is None:
        return None
    value = json.loads(raw)
    return [str(item) for item in value] if isinstance(value, list) else []


def attachments(
    conn: sqlite3.Connection, media_ids: Sequence[str]
) -> dict[str, list[tuple[TargetKind, str]]]:
    found: dict[str, list[tuple[TargetKind, str]]] = {item: [] for item in media_ids}
    for offset in range(0, len(media_ids), 500):
        chunk = list(media_ids[offset : offset + 500])
        for row in conn.execute(
            "SELECT media_id, target_kind, target_id FROM media_attachments "
            f"WHERE media_id IN ({', '.join('?' for _ in chunk)}) "
            "ORDER BY attached_at, target_id",
            chunk,
        ):
            found[str(row["media_id"])].append(
                (row["target_kind"], str(row["target_id"]))
            )
    return found


def attached_to(
    conn: sqlite3.Connection, kind: TargetKind, target_ids: Sequence[str]
) -> dict[str, list[str]]:
    """Media ids attached to each target, oldest attachment first."""
    found: dict[str, list[str]] = {}
    for offset in range(0, len(target_ids), 500):
        chunk = list(target_ids[offset : offset + 500])
        for row in conn.execute(
            "SELECT media_id, target_id FROM media_attachments "
            f"WHERE target_kind = ? AND target_id IN ({', '.join('?' for _ in chunk)}) "
            "ORDER BY attached_at, media_id",
            (kind, *chunk),
        ):
            found.setdefault(str(row["target_id"]), []).append(str(row["media_id"]))
    return found


def move_attachments(
    conn: sqlite3.Connection, kind: TargetKind, from_id: str, into_id: str
) -> int:
    """Re-point a merged-away target's attachments at the survivor."""
    moved = conn.execute(
        "INSERT OR IGNORE INTO media_attachments "
        "(media_id, target_kind, target_id, attached_at, attached_by) "
        "SELECT media_id, target_kind, ?, attached_at, attached_by "
        "FROM media_attachments WHERE target_kind = ? AND target_id = ?",
        (into_id, kind, from_id),
    ).rowcount
    clear_attachments(conn, kind, from_id)
    return moved


def clear_attachments(
    conn: sqlite3.Connection, kind: TargetKind, target_id: str
) -> int:
    return conn.execute(
        "DELETE FROM media_attachments WHERE target_kind = ? AND target_id = ?",
        (kind, target_id),
    ).rowcount
