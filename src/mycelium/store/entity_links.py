"""Entity-to-entity links."""

from __future__ import annotations

import sqlite3

from . import kernel
from .kernel import _now, _record, _row_dict

# --- entity-to-entity links ------------------------------------------------


def insert_entity_links(
    conn: sqlite3.Connection, edges: list[tuple[str, str, str]]
) -> int:
    """Insert (from_entity, to_entity, link_type) edges. Returns rows
    actually inserted — pre-existing edges (matched on the triple via
    the PK) are silently skipped."""
    if not edges:
        return 0
    now, actor = _now(), kernel.get_actor()
    inserted = 0
    for f, t, lt in edges:
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (f, t, lt, now, actor),
        )
        if cur.rowcount:
            inserted += 1
            _record(
                conn,
                "link",
                "entity_link",
                f"{f}|{t}|{lt}",
                after={
                    "from_entity_id": f,
                    "to_entity_id": t,
                    "link_type": lt,
                    "created_at": now,
                    "created_by": actor,
                },
            )
    return inserted


def delete_entity_links(
    conn: sqlite3.Connection, edges: list[tuple[str, str, str]]
) -> int:
    """Delete specific (from_entity, to_entity, link_type) edges.
    Returns rows actually removed — missing edges silently skipped."""
    if not edges:
        return 0
    removed = 0
    for f, t, lt in edges:
        row = conn.execute(
            "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
            "FROM entity_links "
            "WHERE from_entity_id = ? AND to_entity_id = ? AND link_type = ?",
            (f, t, lt),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            "DELETE FROM entity_links "
            "WHERE from_entity_id = ? AND to_entity_id = ? AND link_type = ?",
            (f, t, lt),
        )
        removed += 1
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{f}|{t}|{lt}",
            before=_row_dict(row),
        )
    return removed


def get_entity_links_outgoing(
    conn: sqlite3.Connection, entity_id: str
) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT to_entity_id, link_type FROM entity_links WHERE from_entity_id = ?",
        (entity_id,),
    ).fetchall()
    return [(r["to_entity_id"], r["link_type"]) for r in rows]


def get_entity_links_incoming(
    conn: sqlite3.Connection, entity_id: str
) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT from_entity_id, link_type FROM entity_links WHERE to_entity_id = ?",
        (entity_id,),
    ).fetchall()
    return [(r["from_entity_id"], r["link_type"]) for r in rows]


def list_entity_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM entity_links ORDER BY link_type"
    ).fetchall()
    return [r["link_type"] for r in rows]


def delete_entity_links_touching(
    conn: sqlite3.Connection, entity_id: str
) -> tuple[int, int]:
    """Remove every `entity_links` row from or to `entity_id`, returning
    `(outgoing_removed, incoming_removed)`."""
    outgoing_removed = conn.execute(
        "DELETE FROM entity_links WHERE from_entity_id = ?", (entity_id,)
    ).rowcount
    incoming_removed = conn.execute(
        "DELETE FROM entity_links WHERE to_entity_id = ?", (entity_id,)
    ).rowcount
    return outgoing_removed, incoming_removed


def rewrite_entity_link_endpoints(
    conn: sqlite3.Connection, from_entity_id: str, into_entity_id: str
) -> None:
    """Used by merge_entities. Rewrites every entity_link that
    references `from_entity_id` (as either endpoint) to reference
    `into_entity_id` instead, dropping any self-loops the merge would
    create. Without this, FK enforcement would block the source's
    deletion at merge time."""
    # Outgoing rewrites: source as `from`. For history fidelity, walk
    # row-by-row so each move emits an event pair (unlink old shape,
    # link new shape). Preserves original created_at/created_by on the
    # rewritten row — the merged-into row inherits the provenance of
    # the source link rather than being treated as fresh.
    outgoing = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
        "FROM entity_links WHERE from_entity_id = ? AND to_entity_id != ?",
        (from_entity_id, into_entity_id),
    ).fetchall()
    for r in outgoing:
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{r['from_entity_id']}|{r['to_entity_id']}|{r['link_type']}",
            before=_row_dict(r),
            context={"reason": "merge_entities"},
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                into_entity_id,
                r["to_entity_id"],
                r["link_type"],
                r["created_at"],
                r["created_by"],
            ),
        )
        if cur.rowcount:
            _record(
                conn,
                "link",
                "entity_link",
                f"{into_entity_id}|{r['to_entity_id']}|{r['link_type']}",
                after={
                    "from_entity_id": into_entity_id,
                    "to_entity_id": r["to_entity_id"],
                    "link_type": r["link_type"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                },
                context={"reason": "merge_entities"},
            )
    conn.execute("DELETE FROM entity_links WHERE from_entity_id = ?", (from_entity_id,))
    # Incoming rewrites: source as `to`. Same dedupe-merged shape.
    incoming = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
        "FROM entity_links WHERE to_entity_id = ? AND from_entity_id != ?",
        (from_entity_id, into_entity_id),
    ).fetchall()
    for r in incoming:
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{r['from_entity_id']}|{r['to_entity_id']}|{r['link_type']}",
            before=_row_dict(r),
            context={"reason": "merge_entities"},
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                r["from_entity_id"],
                into_entity_id,
                r["link_type"],
                r["created_at"],
                r["created_by"],
            ),
        )
        if cur.rowcount:
            _record(
                conn,
                "link",
                "entity_link",
                f"{r['from_entity_id']}|{into_entity_id}|{r['link_type']}",
                after={
                    "from_entity_id": r["from_entity_id"],
                    "to_entity_id": into_entity_id,
                    "link_type": r["link_type"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                },
                context={"reason": "merge_entities"},
            )
    conn.execute("DELETE FROM entity_links WHERE to_entity_id = ?", (from_entity_id,))
