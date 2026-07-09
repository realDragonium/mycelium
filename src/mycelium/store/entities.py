"""Entity records: create, read, update, delete."""

from __future__ import annotations

import sqlite3
import uuid

from . import kernel
from .kernel import _now, _record, _row_dict

# --- entities ---------------------------------------------------------------


def create_entity(conn: sqlite3.Connection, description: str | None) -> str:
    entity_id = f"ent_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO entities (id, description, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (entity_id, description, _now(), kernel.get_actor()),
    )
    _record(
        conn,
        "create",
        "entity",
        entity_id,
        after=_row_dict(get_entity_by_id(conn, entity_id)),
    )
    return entity_id


def get_entity_by_id(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, description, created_at, updated_at, created_by, updated_by "
        "FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()


def update_entity_description(
    conn: sqlite3.Connection, entity_id: str, description: str | None
) -> None:
    before = _row_dict(get_entity_by_id(conn, entity_id))
    conn.execute(
        "UPDATE entities SET description = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (description, _now(), kernel.get_actor(), entity_id),
    )
    _record(
        conn,
        "update",
        "entity",
        entity_id,
        before=before,
        after=_row_dict(get_entity_by_id(conn, entity_id)),
    )


def delete_entity(conn: sqlite3.Connection, entity_id: str) -> None:
    """Caller is responsible for ensuring no names point at this entity."""
    before = _row_dict(get_entity_by_id(conn, entity_id))
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    if before is not None:
        _record(conn, "delete", "entity", entity_id, before=before)
