"""Statements and vector-id mappings for statements and names."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence

from . import audience_labels, kernel
from .kernel import _now, _record, _row_dict

# --- statements --------------------------------------------------------------


def create_statement(conn: sqlite3.Connection, kind: str, text: str) -> str:
    statement_id = f"stm_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO statements (id, kind, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (statement_id, kind, text, _now(), kernel.get_actor()),
    )
    _record(
        conn,
        "create",
        "statement",
        statement_id,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    audience_labels.enqueue(conn, [statement_id])
    return statement_id


def get_statement(conn: sqlite3.Connection, statement_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, kind, text, created_at, updated_at, created_by, updated_by "
        "FROM statements WHERE id = ?",
        (statement_id,),
    ).fetchone()
    return row


def get_statement_kinds(
    conn: sqlite3.Connection, statement_ids: Sequence[str]
) -> dict[str, str]:
    """Return kinds for the requested statements that still exist."""
    kinds: dict[str, str] = {}
    for offset in range(0, len(statement_ids), 500):
        chunk = statement_ids[offset : offset + 500]
        placeholders = ", ".join("?" for _statement_id in chunk)
        rows = conn.execute(
            f"SELECT id, kind FROM statements WHERE id IN ({placeholders})",
            tuple(chunk),
        )
        kinds.update((str(row["id"]), str(row["kind"])) for row in rows)
    return kinds


def get_statement_texts(
    conn: sqlite3.Connection, statement_ids: Sequence[str]
) -> dict[str, str]:
    """Return text for the requested statements that still exist."""
    texts: dict[str, str] = {}
    for offset in range(0, len(statement_ids), 500):
        chunk = statement_ids[offset : offset + 500]
        placeholders = ", ".join("?" for _statement_id in chunk)
        rows = conn.execute(
            f"SELECT id, text FROM statements WHERE id IN ({placeholders})",
            tuple(chunk),
        )
        texts.update((str(row["id"]), str(row["text"])) for row in rows)
    return texts


def merge_targets(
    conn: sqlite3.Connection, statement_ids: Sequence[str]
) -> dict[str, str]:
    """For deleted statements that were merged away, the statement each was
    merged into, read from the history their deletion recorded. Empty when no
    history is attached."""
    if not kernel.has_history(conn):
        return {}
    targets: dict[str, str] = {}
    for offset in range(0, len(statement_ids), 500):
        chunk = statement_ids[offset : offset + 500]
        placeholders = ", ".join("?" for _statement_id in chunk)
        rows = conn.execute(
            "SELECT target_id, json_extract(context_json, '$.merged_into') AS into_id "
            "FROM history.history_events WHERE target_kind = 'statement' "
            f"AND op = 'delete' AND target_id IN ({placeholders}) ORDER BY event_id",
            tuple(chunk),
        )
        for row in rows:
            if row["into_id"] is not None:
                targets[str(row["target_id"])] = str(row["into_id"])
            else:
                targets.pop(str(row["target_id"]), None)
    return targets


def update_statement(
    conn: sqlite3.Connection, statement_id: str, kind: str, text: str
) -> None:
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET kind = ?, text = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (kind, text, _now(), kernel.get_actor(), statement_id),
    )
    if before is not None and before["text"] != text:
        audience_labels.text_changed(conn, statement_id)
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )


def update_statement_text(
    conn: sqlite3.Connection, statement_id: str, text: str
) -> None:
    """Update only the text — used by `replace_text`, which never touches kind."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (text, _now(), kernel.get_actor(), statement_id),
    )
    if before is not None and before["text"] != text:
        audience_labels.text_changed(conn, statement_id)
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )


def update_statement_kind(
    conn: sqlite3.Connection, statement_id: str, kind: str
) -> None:
    """Update only the kind — used by `patch_statement` when text is unchanged.

    Avoids touching `text` (and thus the embedding) when the caller is
    only re-classifying a statement."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET kind = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (kind, _now(), kernel.get_actor(), statement_id),
    )
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )


# --- vector id mapping ------------------------------------------------------


def next_vector_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(vector_id), -1) + 1 AS next FROM statement_vector_ids"
    ).fetchone()
    return int(row["next"])


def set_vector_id(conn: sqlite3.Connection, statement_id: str, vector_id: int) -> None:
    conn.execute(
        "INSERT INTO statement_vector_ids (statement_id, vector_id) VALUES (?, ?)",
        (statement_id, vector_id),
    )


def get_vector_id(conn: sqlite3.Connection, statement_id: str) -> int | None:
    row = conn.execute(
        "SELECT vector_id FROM statement_vector_ids WHERE statement_id = ?",
        (statement_id,),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def get_vector_ids(
    conn: sqlite3.Connection, statement_ids: Sequence[str]
) -> dict[str, int]:
    """Return stored vector ids for the requested statement ids."""
    vector_ids: dict[str, int] = {}
    for offset in range(0, len(statement_ids), 500):
        chunk = statement_ids[offset : offset + 500]
        placeholders = ", ".join("?" for _statement_id in chunk)
        rows = conn.execute(
            "SELECT statement_id, vector_id FROM statement_vector_ids "
            f"WHERE statement_id IN ({placeholders})",
            tuple(chunk),
        )
        vector_ids.update((row["statement_id"], int(row["vector_id"])) for row in rows)
    return vector_ids


def get_statement_id_by_vector_id(
    conn: sqlite3.Connection, vector_id: int
) -> str | None:
    row = conn.execute(
        "SELECT statement_id FROM statement_vector_ids WHERE vector_id = ?",
        (vector_id,),
    ).fetchone()
    return row["statement_id"] if row else None


# --- name vector_id mapping ------------------------------------------------


def next_name_vector_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(vector_id), -1) + 1 AS next FROM name_vector_ids"
    ).fetchone()
    return int(row["next"])


def set_name_vector_id(conn: sqlite3.Connection, name_id: str, vector_id: int) -> None:
    conn.execute(
        "INSERT INTO name_vector_ids (name_id, vector_id) VALUES (?, ?)",
        (name_id, vector_id),
    )


def get_name_vector_id(conn: sqlite3.Connection, name_id: str) -> int | None:
    row = conn.execute(
        "SELECT vector_id FROM name_vector_ids WHERE name_id = ?",
        (name_id,),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def get_name_id_by_vector_id(conn: sqlite3.Connection, vector_id: int) -> str | None:
    row = conn.execute(
        "SELECT name_id FROM name_vector_ids WHERE vector_id = ?",
        (vector_id,),
    ).fetchone()
    return row["name_id"] if row else None


def delete_name_vector_mapping(conn: sqlite3.Connection, name_id: str) -> None:
    conn.execute("DELETE FROM name_vector_ids WHERE name_id = ?", (name_id,))


def list_all_names(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, text, entity_id, generated_from_name_id FROM names"
        ).fetchall()
    )
