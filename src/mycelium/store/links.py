"""Statement-to-statement links: write path, read path, merge support."""

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
from .statements import get_statement

# --- links: write path ------------------------------------------------------


def _hash_for(expr: dict[str, Any] | None) -> str:
    """Local thin wrapper to keep store.py's link callers from each
    importing when_expression. Returns the canonical hash, or HASH_NONE
    for an unconditional link."""
    from .. import when_expression as we

    return we.hash_canonical(expr)


def _canonical_for(expr: dict[str, Any] | None) -> dict[str, Any] | None:
    if expr is None:
        return None
    from .. import when_expression as we

    return we.canonicalize(expr)


def _insert_one_link(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    link_type: str,
    when: dict[str, Any] | None,
) -> int | None:
    """Insert one link row + its when_nodes tree. Returns the new
    link_id, or None if a row with the same (from, to, link_type,
    when_hash) already existed."""
    canonical = _canonical_for(when)
    when_hash = _hash_for(canonical)
    cur = conn.execute(
        "INSERT OR IGNORE INTO statement_links "
        "(from_statement_id, to_statement_id, link_type, when_hash, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (from_id, to_id, link_type, when_hash, _now(), kernel._actor),
    )
    if not cur.rowcount:
        return None
    link_id = cur.lastrowid
    if canonical is not None:
        _insert_when_tree(conn, link_id, canonical)
    _record(
        conn,
        "link",
        "statement_link",
        str(link_id),
        after={
            "link_id": link_id,
            "from_id": from_id,
            "to_id": to_id,
            "link_type": link_type,
            "when": canonical,
        },
    )
    return link_id


def _record_statement_link_delete(
    conn: sqlite3.Connection, link_id: int, reason: str | None = None
) -> None:
    """Capture a link's current shape for an unlink event. Must be called
    BEFORE the row is deleted, since it reads the row and its when-tree."""
    row = conn.execute(
        "SELECT link_id, from_statement_id, to_statement_id, link_type, "
        "       when_hash, created_at, created_by "
        "FROM statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return
    tree = _load_when_tree(conn, link_id)
    _record(
        conn,
        "unlink",
        "statement_link",
        str(link_id),
        before={
            "link_id": row["link_id"],
            "from_id": row["from_statement_id"],
            "to_id": row["to_statement_id"],
            "link_type": row["link_type"],
            "when": tree,
            "created_at": row["created_at"],
            "created_by": row["created_by"],
        },
        context={"reason": reason} if reason else None,
    )


def replace_links(
    conn: sqlite3.Connection,
    statement_id: str,
    links: list[tuple[str, str, dict[str, Any] | None]],
) -> None:
    """Replace this statement's outgoing edges wholesale. Each link is
    `(to_statement_id, link_type, when_expression | None)`. when_nodes
    rows cascade away when statement_links rows are deleted."""
    existing = conn.execute(
        "SELECT link_id FROM statement_links WHERE from_statement_id = ?",
        (statement_id,),
    ).fetchall()
    for r in existing:
        _record_statement_link_delete(conn, r["link_id"], reason="replace_links")
    conn.execute(
        "DELETE FROM statement_links WHERE from_statement_id = ?", (statement_id,)
    )
    for to_id, link_type, when in links:
        _insert_one_link(conn, statement_id, to_id, link_type, when)


def insert_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, dict[str, Any] | None]],
) -> int:
    """Insert (from, to, link_type, when_expression?) edges. Returns rows
    actually inserted — pre-existing edges (matched on the four-tuple
    `(from, to, link_type, when_hash)`) are silently skipped."""
    if not edges:
        return 0
    inserted = 0
    for from_id, to_id, link_type, when in edges:
        if _insert_one_link(conn, from_id, to_id, link_type, when) is not None:
            inserted += 1
    return inserted


def delete_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, dict[str, Any] | None]],
) -> int:
    """Delete specific (from, to, link_type, when_expression?) edges by
    their canonical hash. Returns rows actually removed; missing edges
    are silently skipped. ON DELETE CASCADE drops the when_nodes rows."""
    if not edges:
        return 0
    removed = 0
    for from_id, to_id, link_type, when in edges:
        when_hash = _hash_for(when)
        matching = conn.execute(
            "SELECT link_id FROM statement_links "
            "WHERE from_statement_id = ? AND to_statement_id = ? "
            "AND link_type = ? AND when_hash = ?",
            (from_id, to_id, link_type, when_hash),
        ).fetchall()
        for r in matching:
            _record_statement_link_delete(conn, r["link_id"])
        cur = conn.execute(
            "DELETE FROM statement_links "
            "WHERE from_statement_id = ? AND to_statement_id = ? "
            "AND link_type = ? AND when_hash = ?",
            (from_id, to_id, link_type, when_hash),
        )
        removed += cur.rowcount
    return removed


# --- links: read path -------------------------------------------------------


def get_links(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Outgoing edges of `statement_id` as
    `(to_statement_id, link_type, when_expression | None)` tuples."""
    rows = conn.execute(
        "SELECT link_id, to_statement_id, link_type FROM statement_links "
        "WHERE from_statement_id = ? ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    return [
        (r["to_statement_id"], r["link_type"], _load_when_tree(conn, r["link_id"]))
        for r in rows
    ]


def get_incoming_links(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Statements that link TO `statement_id`. Returns
    `(from_statement_id, link_type, when_expression | None)`."""
    rows = conn.execute(
        "SELECT link_id, from_statement_id, link_type FROM statement_links "
        "WHERE to_statement_id = ? ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    return [
        (r["from_statement_id"], r["link_type"], _load_when_tree(conn, r["link_id"]))
        for r in rows
    ]


def links_referencing_statement(
    conn: sqlite3.Connection,
    statement_id: str,
    *,
    link_kind: str = "statement",
) -> list[int]:
    """Every link_id whose when-tree mentions `statement_id` as a leaf,
    scoped to one link table (default: statement_links). Indexed lookup
    against `when_nodes(link_kind, statement_id)`. Used by cascade
    detection and by rewrite-on-merge."""
    rows = conn.execute(
        "SELECT DISTINCT link_id FROM when_nodes "
        "WHERE statement_id = ? AND link_kind = ?",
        (statement_id, link_kind),
    ).fetchall()
    return [r["link_id"] for r in rows]


def get_when_references(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Every statement-link edge whose `when` tree references
    `statement_id` as a leaf, fully hydrated. Returns
    `[(from_statement_id, to_statement_id, link_type, when_tree)]`.

    Empty list when the statement is not used as a condition anywhere.
    Entity-statement edges that condition on this statement surface via
    `get_entity_statement_when_references` instead.
    """
    rows = conn.execute(
        "SELECT DISTINCT sl.link_id, sl.from_statement_id, "
        "       sl.to_statement_id, sl.link_type "
        "FROM when_nodes wn "
        "JOIN statement_links sl ON sl.link_id = wn.link_id "
        "WHERE wn.statement_id = ? AND wn.link_kind = 'statement'",
        (statement_id,),
    ).fetchall()
    return [
        (
            r["from_statement_id"],
            r["to_statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"]),
        )
        for r in rows
    ]


# --- links: merge support ---------------------------------------------------


def merge_mentions_into(conn: sqlite3.Connection, from_id: str, into_id: str) -> int:
    """Move all mention rows from `from_id` onto `into_id`, deduped on
    name_id. Returns rows actually inserted (excluding dupes that were
    already on `into_id`). Removes `from_id`'s mention rows."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) "
        "SELECT ?, name_id FROM statement_mentions WHERE statement_id = ?",
        (into_id, from_id),
    )
    inserted = cur.rowcount
    conn.execute("DELETE FROM statement_mentions WHERE statement_id = ?", (from_id,))
    return inserted


def _move_link_endpoint(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    new_from: str | None = None,
    new_to: str | None = None,
    rewrite_when_leaves: tuple[str, str] | None = None,
) -> None:
    """Apply endpoint moves and/or when-leaf rewrites to a single link.
    On hash collision with an existing link (same from/to/link_type/hash
    after rewrite), drop the rewriting link — the existing one absorbs
    it. when_nodes auto-cascades away with the link.
    """
    from .. import when_expression as we

    row = conn.execute(
        "SELECT from_statement_id, to_statement_id, link_type "
        "FROM statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return

    new_from_id = new_from if new_from is not None else row["from_statement_id"]
    new_to_id = new_to if new_to is not None else row["to_statement_id"]

    tree = _load_when_tree(conn, link_id)
    if rewrite_when_leaves is not None and tree is not None:
        old_id, replacement_id = rewrite_when_leaves
        tree = we.substitute_leaves(
            tree, lambda x: replacement_id if x == old_id else x
        )

    canonical = _canonical_for(tree)
    new_hash = _hash_for(canonical)

    # Self-loop after move: drop.
    if new_from_id == new_to_id:
        _record_statement_link_delete(conn, link_id, reason="merge_self_loop")
        conn.execute("DELETE FROM statement_links WHERE link_id = ?", (link_id,))
        return

    # Check for collision with an existing distinct link.
    existing = conn.execute(
        "SELECT link_id FROM statement_links "
        "WHERE from_statement_id = ? AND to_statement_id = ? "
        "AND link_type = ? AND when_hash = ? AND link_id != ?",
        (new_from_id, new_to_id, row["link_type"], new_hash, link_id),
    ).fetchone()
    if existing is not None:
        # The destination shape already exists; drop our row.
        _record_statement_link_delete(conn, link_id, reason="merge_absorbed")
        conn.execute("DELETE FROM statement_links WHERE link_id = ?", (link_id,))
        return

    # Apply the move + hash; rebuild the when-tree if the canonical
    # shape may have changed.
    before_tree = _load_when_tree(conn, link_id)
    before_payload = {
        "link_id": link_id,
        "from_id": row["from_statement_id"],
        "to_id": row["to_statement_id"],
        "link_type": row["link_type"],
        "when": before_tree,
    }
    conn.execute(
        "UPDATE statement_links SET from_statement_id = ?, to_statement_id = ?, "
        "when_hash = ? WHERE link_id = ?",
        (new_from_id, new_to_id, new_hash, link_id),
    )
    if rewrite_when_leaves is not None:
        conn.execute(
            "DELETE FROM when_nodes WHERE link_id = ? AND link_kind = 'statement'",
            (link_id,),
        )
        if canonical is not None:
            _insert_when_tree(conn, link_id, canonical)
    _record(
        conn,
        "update",
        "statement_link",
        str(link_id),
        before=before_payload,
        after={
            "link_id": link_id,
            "from_id": new_from_id,
            "to_id": new_to_id,
            "link_type": row["link_type"],
            "when": canonical,
        },
        context={"reason": "move_link_endpoint"},
    )


def merge_outgoing_links_into(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Move all outgoing links of `from_id` so they originate from
    `into_id`. Self-loops drop. Hash collisions absorb into the existing
    link. when_statement_id leaves equal to `from_id` rewrite to `into_id`
    on the way through. Returns the count of moved links (post-collision
    deduplication)."""
    rows = conn.execute(
        "SELECT link_id FROM statement_links WHERE from_statement_id = ?",
        (from_id,),
    ).fetchall()
    moved = 0
    for r in rows:
        before = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        _move_link_endpoint(
            conn,
            r["link_id"],
            new_from=into_id,
            rewrite_when_leaves=(from_id, into_id),
        )
        after = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        if before and after:
            moved += 1
    return moved


def merge_incoming_links_into(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Move all incoming links to `from_id` so they target `into_id`.
    Self-loops drop. Hash collisions absorb into the existing link.
    when_statement_id leaves equal to `from_id` rewrite to `into_id`
    on the way through."""
    rows = conn.execute(
        "SELECT link_id FROM statement_links WHERE to_statement_id = ?",
        (from_id,),
    ).fetchall()
    moved = 0
    for r in rows:
        before = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        _move_link_endpoint(
            conn,
            r["link_id"],
            new_to=into_id,
            rewrite_when_leaves=(from_id, into_id),
        )
        after = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        if before and after:
            moved += 1
    return moved


def rewrite_when_references(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Rewrite every link's when-tree, replacing leaves referencing
    `from_id` with `into_id`. Each rewritten link is re-canonicalized,
    re-hashed, and stored back; on hash collision with an existing link,
    the rewriting row is dropped (the destination already exists).

    Returns the number of links whose when-tree actually contained a
    reference to from_id (= the number processed, before any drops)."""
    link_ids = links_referencing_statement(conn, from_id)
    for lid in link_ids:
        _move_link_endpoint(conn, lid, rewrite_when_leaves=(from_id, into_id))
    return len(link_ids)


def delete_links_touching_statement(
    conn: sqlite3.Connection, statement_id: str
) -> tuple[int, int, int, int]:
    """Remove every link that touches `statement_id` so the statement can be
    deleted under FK enforcement, returning
    `(outgoing_removed, incoming_removed, when_removed, entity_statement_removed)`.

    Order matters: outgoing `statement_links` are dropped before incoming so
    a self-loop is counted exactly once. Conditional links whose when-tree
    references the statement — both `statement_links` and
    `entity_statement_links` — are then dropped by link_id (their `when_nodes`
    rows cascade via trigger), and entity↔statement edges with the statement
    as an endpoint go too. `entity_statement_removed` sums the endpoint and
    when-tree removals."""
    outgoing_removed = conn.execute(
        "DELETE FROM statement_links WHERE from_statement_id = ?", (statement_id,)
    ).rowcount
    incoming_removed = conn.execute(
        "DELETE FROM statement_links WHERE to_statement_id = ?", (statement_id,)
    ).rowcount
    when_removed = 0
    for lid in links_referencing_statement(conn, statement_id):
        when_removed += conn.execute(
            "DELETE FROM statement_links WHERE link_id = ?", (lid,)
        ).rowcount
    es_removed = conn.execute(
        "DELETE FROM entity_statement_links WHERE statement_id = ?", (statement_id,)
    ).rowcount
    for lid in links_referencing_statement(
        conn, statement_id, link_kind="entity_statement"
    ):
        es_removed += conn.execute(
            "DELETE FROM entity_statement_links WHERE link_id = ?", (lid,)
        ).rowcount
    return outgoing_removed, incoming_removed, when_removed, es_removed


def delete_statement(conn: sqlite3.Connection, statement_id: str) -> None:
    """Delete a statement record and its vector_id mapping. Caller must
    ensure no statement_mentions or statement_links still reference it —
    FK enforcement will reject otherwise."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "DELETE FROM statement_vector_ids WHERE statement_id = ?", (statement_id,)
    )
    conn.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
    if before is not None:
        _record(conn, "delete", "statement", statement_id, before=before)


def list_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM statement_links ORDER BY link_type"
    ).fetchall()
    return [r["link_type"] for r in rows]


def count_statement_links_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-type counts for the statement_links table. Returns a dict
    `{link_type: count}`. Types with zero rows are absent from the dict
    — callers default to 0."""
    rows = conn.execute(
        "SELECT link_type, COUNT(*) AS n FROM statement_links GROUP BY link_type"
    ).fetchall()
    return {r["link_type"]: int(r["n"]) for r in rows}


def count_entity_links_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-type counts for the entity_links table. Same shape as
    `count_statement_links_by_type`."""
    rows = conn.execute(
        "SELECT link_type, COUNT(*) AS n FROM entity_links GROUP BY link_type"
    ).fetchall()
    return {r["link_type"]: int(r["n"]) for r in rows}


def count_statements_by_kind_all(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-kind counts for the statements table. Returns `{kind: count}`."""
    rows = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM statements GROUP BY kind"
    ).fetchall()
    return {r["kind"]: int(r["n"]) for r in rows}
