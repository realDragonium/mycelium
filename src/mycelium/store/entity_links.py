"""Entity-to-entity and entity-to-statement links."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import kernel
from .kernel import (
    _insert_when_tree,
    _load_when_tree,
    _now,
    _record,
    _row_dict,
)
from .links import _canonical_for, _hash_for, links_referencing_statement

# --- entity-to-entity links ------------------------------------------------


def insert_entity_links(
    conn: sqlite3.Connection, edges: list[tuple[str, str, str]]
) -> int:
    """Insert (from_entity, to_entity, link_type) edges. Returns rows
    actually inserted — pre-existing edges (matched on the triple via
    the PK) are silently skipped."""
    if not edges:
        return 0
    now, actor = _now(), kernel._actor
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


# --- entity↔statement links ------------------------------------------------
# Mixed-endpoint edges. Same `link_type` vocabulary and `when` semantics
# as statement_links — the caller-facing API is uniform across both kinds.
# Internally they live in their own table so endpoint typing stays clean
# (always exactly one entity + one statement; `direction` records which
# side is the source).


def _insert_one_entity_statement_link(
    conn: sqlite3.Connection,
    entity_id: str,
    statement_id: str,
    direction: str,
    link_type: str,
    when: dict[str, Any] | None,
) -> int | None:
    """Insert one entity↔statement link row + its when_nodes tree.
    Returns the new link_id, or None if a row with the same
    (entity, statement, direction, link_type, when_hash) already existed."""
    canonical = _canonical_for(when)
    when_hash = _hash_for(canonical)
    cur = conn.execute(
        "INSERT OR IGNORE INTO entity_statement_links "
        "(entity_id, statement_id, direction, link_type, when_hash, "
        " created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            entity_id,
            statement_id,
            direction,
            link_type,
            when_hash,
            _now(),
            kernel._actor,
        ),
    )
    if not cur.rowcount:
        return None
    link_id = cur.lastrowid
    if canonical is not None:
        _insert_when_tree(conn, link_id, canonical, link_kind="entity_statement")
    _record(
        conn,
        "link",
        "entity_statement_link",
        str(link_id),
        after={
            "link_id": link_id,
            "entity_id": entity_id,
            "statement_id": statement_id,
            "direction": direction,
            "link_type": link_type,
            "when": canonical,
        },
    )
    return link_id


def _record_entity_statement_link_delete(
    conn: sqlite3.Connection, link_id: int, reason: str | None = None
) -> None:
    """Capture an entity↔statement link's current shape for an unlink
    event. Must be called BEFORE the row is deleted."""
    row = conn.execute(
        "SELECT link_id, entity_id, statement_id, direction, link_type, "
        "       when_hash, created_at, created_by "
        "FROM entity_statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return
    tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
    _record(
        conn,
        "unlink",
        "entity_statement_link",
        str(link_id),
        before={
            "link_id": row["link_id"],
            "entity_id": row["entity_id"],
            "statement_id": row["statement_id"],
            "direction": row["direction"],
            "link_type": row["link_type"],
            "when": tree,
            "created_at": row["created_at"],
            "created_by": row["created_by"],
        },
        context={"reason": reason} if reason else None,
    )


def insert_entity_statement_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, str, dict[str, Any] | None]],
) -> int:
    """Insert (entity_id, statement_id, direction, link_type,
    when_expression?) edges. Returns rows actually inserted — pre-existing
    edges (matched on the five-tuple via the UNIQUE constraint) are
    silently skipped. `direction` is 'es' (entity→statement) or 'se'
    (statement→entity)."""
    if not edges:
        return 0
    inserted = 0
    for entity_id, statement_id, direction, link_type, when in edges:
        if (
            _insert_one_entity_statement_link(
                conn, entity_id, statement_id, direction, link_type, when
            )
            is not None
        ):
            inserted += 1
    return inserted


def delete_entity_statement_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, str, dict[str, Any] | None]],
) -> int:
    """Delete specific entity↔statement edges by their canonical hash.
    Returns rows actually removed; missing edges are silently skipped.
    The cascade trigger on `entity_statement_links` cleans up when_nodes
    rows."""
    if not edges:
        return 0
    removed = 0
    for entity_id, statement_id, direction, link_type, when in edges:
        when_hash = _hash_for(when)
        matching = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (entity_id, statement_id, direction, link_type, when_hash),
        ).fetchall()
        for r in matching:
            _record_entity_statement_link_delete(conn, r["link_id"])
        cur = conn.execute(
            "DELETE FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (entity_id, statement_id, direction, link_type, when_hash),
        )
        removed += cur.rowcount
    return removed


def delete_entity_statement_links_for_entity(
    conn: sqlite3.Connection, entity_id: str
) -> int:
    """Remove every entity↔statement edge anchored on `entity_id`, returning
    the row count. The cascade trigger on `entity_statement_links` cleans up
    their `when_nodes` rows."""
    return conn.execute(
        "DELETE FROM entity_statement_links WHERE entity_id = ?", (entity_id,)
    ).rowcount


def move_entity_statement_endpoints(
    conn: sqlite3.Connection, from_statement_id: str, into_statement_id: str
) -> None:
    """Re-point entity↔statement edges from `from_statement_id` onto
    `into_statement_id`. `UPDATE OR IGNORE` moves each edge unless it would
    collide with an existing one under the UNIQUE constraint; rows left on the
    source by a collision are then deleted so the source statement can be
    removed."""
    conn.execute(
        "UPDATE OR IGNORE entity_statement_links SET statement_id = ? "
        "WHERE statement_id = ?",
        (into_statement_id, from_statement_id),
    )
    conn.execute(
        "DELETE FROM entity_statement_links WHERE statement_id = ?",
        (from_statement_id,),
    )


def get_entity_statement_links_for_entity(
    conn: sqlite3.Connection, entity_id: str
) -> tuple[
    list[tuple[str, str, dict[str, Any] | None]],
    list[tuple[str, str, dict[str, Any] | None]],
]:
    """Return `(outgoing, incoming)` for `entity_id` in the
    entity↔statement table.

    `outgoing` are edges where this entity is the source (direction='es'):
    each tuple is `(to_statement_id, link_type, when | None)`.
    `incoming` are edges where this entity is the target (direction='se'):
    each tuple is `(from_statement_id, link_type, when | None)`."""
    outgoing_rows = conn.execute(
        "SELECT link_id, statement_id, link_type FROM entity_statement_links "
        "WHERE entity_id = ? AND direction = 'es' ORDER BY link_id",
        (entity_id,),
    ).fetchall()
    incoming_rows = conn.execute(
        "SELECT link_id, statement_id, link_type FROM entity_statement_links "
        "WHERE entity_id = ? AND direction = 'se' ORDER BY link_id",
        (entity_id,),
    ).fetchall()
    outgoing = [
        (
            r["statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in outgoing_rows
    ]
    incoming = [
        (
            r["statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in incoming_rows
    ]
    return outgoing, incoming


def get_entity_statement_links_for_statement(
    conn: sqlite3.Connection, statement_id: str
) -> tuple[
    list[tuple[str, str, dict[str, Any] | None]],
    list[tuple[str, str, dict[str, Any] | None]],
]:
    """Return `(outgoing, incoming)` for `statement_id` in the
    entity↔statement table.

    `outgoing` are edges where the statement is the source (direction='se'):
    each tuple is `(to_entity_id, link_type, when | None)`.
    `incoming` are edges where the statement is the target (direction='es'):
    each tuple is `(from_entity_id, link_type, when | None)`."""
    outgoing_rows = conn.execute(
        "SELECT link_id, entity_id, link_type FROM entity_statement_links "
        "WHERE statement_id = ? AND direction = 'se' ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    incoming_rows = conn.execute(
        "SELECT link_id, entity_id, link_type FROM entity_statement_links "
        "WHERE statement_id = ? AND direction = 'es' ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    outgoing = [
        (
            r["entity_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in outgoing_rows
    ]
    incoming = [
        (
            r["entity_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in incoming_rows
    ]
    return outgoing, incoming


def get_entity_statement_when_references(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, str, str, dict[str, Any] | None]]:
    """Every entity↔statement edge whose `when` tree references
    `statement_id` as a leaf, fully hydrated. Each tuple is
    `(entity_id, statement_id, direction, link_type, when_tree)`.

    Empty list when the statement is not used as a condition on any
    entity↔statement edge."""
    rows = conn.execute(
        "SELECT DISTINCT esl.link_id, esl.entity_id, esl.statement_id, "
        "       esl.direction, esl.link_type "
        "FROM when_nodes wn "
        "JOIN entity_statement_links esl ON esl.link_id = wn.link_id "
        "WHERE wn.statement_id = ? AND wn.link_kind = 'entity_statement'",
        (statement_id,),
    ).fetchall()
    return [
        (
            r["entity_id"],
            r["statement_id"],
            r["direction"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in rows
    ]


def rewrite_entity_statement_when_references(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Rewrite every entity↔statement link's when-tree, replacing leaves
    referencing `from_id` (a statement) with `into_id`. Hash collisions
    drop the rewriting row. Mirrors `rewrite_when_references` for the
    statement_links table."""
    from .. import when_expression as we

    link_ids = links_referencing_statement(conn, from_id, link_kind="entity_statement")
    for link_id in link_ids:
        row = conn.execute(
            "SELECT entity_id, statement_id, direction, link_type "
            "FROM entity_statement_links WHERE link_id = ?",
            (link_id,),
        ).fetchone()
        if row is None:
            continue
        tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
        if tree is None:
            continue
        tree = we.substitute_leaves(tree, lambda x: into_id if x == from_id else x)
        canonical = _canonical_for(tree)
        new_hash = _hash_for(canonical)

        # Collision with an existing row?
        existing = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ? AND link_id != ?",
            (
                row["entity_id"],
                row["statement_id"],
                row["direction"],
                row["link_type"],
                new_hash,
                link_id,
            ),
        ).fetchone()
        if existing is not None:
            _record_entity_statement_link_delete(conn, link_id, reason="merge_absorbed")
            conn.execute(
                "DELETE FROM entity_statement_links WHERE link_id = ?",
                (link_id,),
            )
            continue

        before_tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
        before_payload = {
            "link_id": link_id,
            "entity_id": row["entity_id"],
            "statement_id": row["statement_id"],
            "direction": row["direction"],
            "link_type": row["link_type"],
            "when": before_tree,
        }
        conn.execute(
            "UPDATE entity_statement_links SET when_hash = ? WHERE link_id = ?",
            (new_hash, link_id),
        )
        conn.execute(
            "DELETE FROM when_nodes "
            "WHERE link_id = ? AND link_kind = 'entity_statement'",
            (link_id,),
        )
        if canonical is not None:
            _insert_when_tree(conn, link_id, canonical, link_kind="entity_statement")
        _record(
            conn,
            "update",
            "entity_statement_link",
            str(link_id),
            before=before_payload,
            after={
                "link_id": link_id,
                "entity_id": row["entity_id"],
                "statement_id": row["statement_id"],
                "direction": row["direction"],
                "link_type": row["link_type"],
                "when": canonical,
            },
            context={"reason": "rewrite_when_references"},
        )
    return len(link_ids)


def rewrite_entity_statement_endpoints(
    conn: sqlite3.Connection, from_entity_id: str, into_entity_id: str
) -> None:
    """Used by `merge_entities`. Rewrites every entity↔statement link
    whose `entity_id == from_entity_id` to point at `into_entity_id`.
    Hash/collision behavior mirrors `rewrite_entity_link_endpoints`:
    on UNIQUE conflict the rewriting row is dropped (the destination
    already exists). when_nodes rows cascade via the AFTER DELETE
    trigger."""
    rows = conn.execute(
        "SELECT link_id, statement_id, direction, link_type, when_hash "
        "FROM entity_statement_links WHERE entity_id = ?",
        (from_entity_id,),
    ).fetchall()
    for r in rows:
        existing = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (
                into_entity_id,
                r["statement_id"],
                r["direction"],
                r["link_type"],
                r["when_hash"],
            ),
        ).fetchone()
        if existing is not None:
            _record_entity_statement_link_delete(
                conn, r["link_id"], reason="merge_absorbed"
            )
            conn.execute(
                "DELETE FROM entity_statement_links WHERE link_id = ?",
                (r["link_id"],),
            )
            continue
        before = {
            "link_id": r["link_id"],
            "entity_id": from_entity_id,
            "statement_id": r["statement_id"],
            "direction": r["direction"],
            "link_type": r["link_type"],
            "when_hash": r["when_hash"],
        }
        conn.execute(
            "UPDATE entity_statement_links SET entity_id = ? WHERE link_id = ?",
            (into_entity_id, r["link_id"]),
        )
        _record(
            conn,
            "update",
            "entity_statement_link",
            str(r["link_id"]),
            before=before,
            after={**before, "entity_id": into_entity_id},
            context={"reason": "rewrite_entity_statement_endpoints"},
        )


def list_entity_statement_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM entity_statement_links ORDER BY link_type"
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
