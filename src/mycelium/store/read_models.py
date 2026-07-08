"""UI-shaped read models: substrate dump and activity feed."""

from __future__ import annotations

import sqlite3
from typing import Any

from .kernel import _load_when_tree

# --- read models (UI-shaped) ------------------------------------------------
# Pure reads that assemble the exact JSON shapes the bundled web UI expects.
# They live here (not in the HTTP layer) so the endpoints stay thin translators
# and all substrate SQL stays behind the store boundary. No commits.


def substrate_dump(conn: sqlite3.Connection) -> dict[str, Any]:
    """Dump the entire substrate in the shape the UI expects.

    Returns:
        - entities: [{id, name, description}] — `name` is one of the
          entity's names (alphabetically first); falls back to the id if
          the entity has no names.
        - names: [{id, text, entity}] — `entity` is the entity_id.
        - statements: [{id, kind, text, mentions: [entity_id]}] — entity_ids
          are deduplicated from the underlying name_id mentions, since the UI
          renders mentions as entity chips.
        - links: [{from, to, link_type}] — with an optional `when` tree when
          the link is conditional.
        - entity_links: [{from, to, link_type}].
    """
    name_rows = conn.execute("SELECT id, text, entity_id FROM names").fetchall()
    names = [
        {"id": r["id"], "text": r["text"], "entity": r["entity_id"]} for r in name_rows
    ]

    primary_name: dict[str, str] = {}
    for r in sorted(name_rows, key=lambda r: r["text"]):
        primary_name.setdefault(r["entity_id"], r["text"])

    entity_rows = conn.execute("SELECT id, description FROM entities").fetchall()
    entities = [
        {
            "id": r["id"],
            "name": primary_name.get(r["id"], r["id"]),
            "description": r["description"] or "",
        }
        for r in entity_rows
    ]

    statement_rows = conn.execute("SELECT id, kind, text FROM statements").fetchall()
    mention_rows = conn.execute(
        "SELECT bm.statement_id, n.entity_id "
        "FROM statement_mentions bm "
        "JOIN names n ON n.id = bm.name_id"
    ).fetchall()
    mentions_by_statement: dict[str, list[str]] = {}
    for r in mention_rows:
        bucket = mentions_by_statement.setdefault(r["statement_id"], [])
        if r["entity_id"] not in bucket:
            bucket.append(r["entity_id"])
    statements = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "text": r["text"],
            "mentions": mentions_by_statement.get(r["id"], []),
        }
        for r in statement_rows
    ]

    link_rows = conn.execute(
        "SELECT link_id, from_statement_id, to_statement_id, link_type, when_hash "
        "FROM statement_links"
    ).fetchall()
    links = []
    for r in link_rows:
        entry = {
            "from": r["from_statement_id"],
            "to": r["to_statement_id"],
            "link_type": r["link_type"],
        }
        if r["when_hash"] != "NONE":
            tree = _load_when_tree(conn, r["link_id"])
            if tree is not None:
                entry["when"] = tree
        links.append(entry)

    entity_link_rows = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type FROM entity_links"
    ).fetchall()
    entity_links = [
        {
            "from": r["from_entity_id"],
            "to": r["to_entity_id"],
            "link_type": r["link_type"],
        }
        for r in entity_link_rows
    ]

    return {
        "entities": entities,
        "names": names,
        "statements": statements,
        "links": links,
        "entity_links": entity_links,
    }


# The activity feed unions every table's create/update/link timestamps into a
# single event stream. Sourced from the live `created_at`/`updated_at` columns
# — not the attached history log — so deletes are invisible (the row is gone).
_ACTIVITY_UNION = """
    SELECT created_at AS at, 'create' AS op, 'entity' AS target_kind,
           id AS target_id, created_by AS actor
      FROM entities WHERE created_at IS NOT NULL
    UNION ALL
    SELECT updated_at, 'update', 'entity', id, updated_by
      FROM entities
     WHERE updated_at IS NOT NULL AND updated_at <> COALESCE(created_at, '')
    UNION ALL
    SELECT created_at, 'create', 'statement', id, created_by
      FROM statements WHERE created_at IS NOT NULL
    UNION ALL
    SELECT updated_at, 'update', 'statement', id, updated_by
      FROM statements
     WHERE updated_at IS NOT NULL AND updated_at <> COALESCE(created_at, '')
    UNION ALL
    SELECT created_at, 'create', 'name', id, created_by
      FROM names WHERE created_at IS NOT NULL
    UNION ALL
    SELECT updated_at, 'update', 'name', id, updated_by
      FROM names
     WHERE updated_at IS NOT NULL AND updated_at <> COALESCE(created_at, '')
    UNION ALL
    SELECT created_at, 'link', 'statement_link',
           from_statement_id || '|' || to_statement_id || '|' || link_type,
           created_by
      FROM statement_links WHERE created_at IS NOT NULL
    UNION ALL
    SELECT created_at, 'link', 'entity_link',
           from_entity_id || '|' || to_entity_id || '|' || link_type,
           created_by
      FROM entity_links WHERE created_at IS NOT NULL
    UNION ALL
    SELECT created_at, 'link', 'entity_statement_link',
           entity_id || '|' || statement_id || '|' || direction || '|' || link_type,
           created_by
      FROM entity_statement_links WHERE created_at IS NOT NULL
"""


def activity_feed(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    ops: set[str],
    kinds: set[str],
    query: str,
) -> tuple[list[sqlite3.Row], int]:
    """Page over recent creates/updates/links, newest first.

    Filters are already-validated clean args: `ops`/`kinds` are subsets of
    the feed's op/target_kind vocabularies, and `query` is a stripped
    case-insensitive substring match on target_id (empty string = no
    filter). `limit`/`offset` are assumed pre-clamped by the caller.

    Returns `(rows, total)` where each row carries `at`, `op`,
    `target_kind`, `target_id`, `actor`, and `total` is the unpaged match
    count.
    """
    where_parts: list[str] = []
    params: list[Any] = []
    if ops:
        where_parts.append(f"op IN ({','.join('?' for _ in ops)})")
        params.extend(sorted(ops))
    if kinds:
        where_parts.append(f"target_kind IN ({','.join('?' for _ in kinds)})")
        params.extend(sorted(kinds))
    if query:
        where_parts.append("LOWER(target_id) LIKE ?")
        params.append(f"%{query.lower()}%")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    base = f"SELECT * FROM ({_ACTIVITY_UNION}){where_sql}"

    total_row = conn.execute(f"SELECT COUNT(*) AS n FROM ({base})", params).fetchone()
    total = int(total_row["n"]) if total_row else 0

    rows = conn.execute(
        f"{base} ORDER BY at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return rows, total
