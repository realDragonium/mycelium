"""Statements and vector-id mappings for statements and names."""

from __future__ import annotations

import sqlite3
import uuid

from . import kernel
from .kernel import _now, _record, _row_dict

# --- statements --------------------------------------------------------------


def create_statement(conn: sqlite3.Connection, kind: str, text: str) -> str:
    statement_id = f"stm_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO statements (id, kind, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (statement_id, kind, text, _now(), kernel._actor),
    )
    _record(
        conn,
        "create",
        "statement",
        statement_id,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    return statement_id


def get_statement(conn: sqlite3.Connection, statement_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, kind, text, created_at, updated_at, created_by, updated_by "
        "FROM statements WHERE id = ?",
        (statement_id,),
    ).fetchone()


def update_statement(
    conn: sqlite3.Connection, statement_id: str, kind: str, text: str
) -> None:
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET kind = ?, text = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (kind, text, _now(), kernel._actor, statement_id),
    )
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
        (text, _now(), kernel._actor, statement_id),
    )
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
        (kind, _now(), kernel._actor, statement_id),
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
    return list(conn.execute("SELECT id, text, entity_id FROM names").fetchall())
