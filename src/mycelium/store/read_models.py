"""UI-shaped read models: substrate dump, counts and activity feed."""

from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from .kernel import _load_when_tree

# --- read models (UI-shaped) ------------------------------------------------
# Pure reads that assemble the exact JSON shapes the bundled web UI expects.
# They live here (not in the HTTP layer) so the endpoints stay thin translators
# and all substrate SQL stays behind the store boundary. No commits.


def _like_escape(s: str) -> str:
    """Escape LIKE wildcards so a substring `query` matches literally.

    `%` and `_` are LIKE metacharacters and `\\` is our chosen ESCAPE char;
    all three must be backslash-escaped. Callers pair this with an
    `ESCAPE '\\'` clause on the LIKE.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def substrate_dump(conn: sqlite3.Connection) -> dict[str, Any]:
    """Dump the entire substrate in the shape the UI expects.

    Returns:
        - entities: [{id, name, description}] — `name` is one of the
          entity's preferred name (alphabetical fallback); falls back to the id if
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

    entity_rows = conn.execute(
        "SELECT id, description, preferred_name_id FROM entities"
    ).fetchall()
    by_name_id = {r["id"]: r for r in name_rows}
    for entity in entity_rows:
        preferred = by_name_id.get(entity["preferred_name_id"])
        if preferred is not None and preferred["entity_id"] == entity["id"]:
            primary_name[entity["id"]] = preferred["text"]
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


def dump_neighbourhood(dump: dict[str, Any], focus: str) -> dict[str, Any] | None:
    """The part of a `substrate_dump` around one record, in the same shape,
    or None when `focus` is in neither its entities nor its statements.

    Around an entity: the statements that mention it, the entities linked to
    it and the entities those statements mention. Around a statement: the
    statements it links to or from and the entities they mention. Links are
    kept when both their ends are.
    """
    statements = {s["id"]: s for s in dump["statements"]}
    if any(e["id"] == focus for e in dump["entities"]):
        kept = {s["id"] for s in dump["statements"] if focus in s["mentions"]}
        entity_ids = {focus}
        for link in dump["entity_links"]:
            if focus in (link["from"], link["to"]):
                entity_ids.update((link["from"], link["to"]))
    elif focus in statements:
        kept = {focus}
        for link in dump["links"]:
            if focus in (link["from"], link["to"]):
                kept.update((link["from"], link["to"]))
        entity_ids = set()
    else:
        return None
    for statement_id in kept:
        entity_ids.update(statements[statement_id]["mentions"])
    return {
        "entities": [e for e in dump["entities"] if e["id"] in entity_ids],
        "names": [n for n in dump["names"] if n["entity"] in entity_ids],
        "statements": [s for s in dump["statements"] if s["id"] in kept],
        "links": [
            link
            for link in dump["links"]
            if link["from"] in kept and link["to"] in kept
        ],
        "entity_links": [
            link
            for link in dump["entity_links"]
            if link["from"] in entity_ids and link["to"] in entity_ids
        ],
    }


class ConceptDegree(TypedDict):
    id: str
    name: str
    statements: int
    links: int


def concept_degrees(dump: dict[str, Any]) -> list[ConceptDegree]:
    """Each entity of a `substrate_dump` with how many statements mention it
    and how many entity links it has, most mentioned first."""
    statements: dict[str, int] = {}
    for statement in dump["statements"]:
        for entity_id in statement["mentions"]:
            statements[entity_id] = statements.get(entity_id, 0) + 1
    links: dict[str, int] = {}
    for link in dump["entity_links"]:
        for entity_id in (link["from"], link["to"]):
            links[entity_id] = links.get(entity_id, 0) + 1
    degrees = [
        ConceptDegree(
            id=e["id"],
            name=e["name"],
            statements=statements.get(e["id"], 0),
            links=links.get(e["id"], 0),
        )
        for e in dump["entities"]
    ]
    degrees.sort(key=lambda d: (-d["statements"], -d["links"], d["name"].lower()))
    return degrees


class SubstrateCounts(TypedDict):
    statements: int
    entities: int
    names: int
    links: int
    entity_links: int


def substrate_counts(conn: sqlite3.Connection) -> SubstrateCounts:
    """How many of each record `substrate_dump` would return."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM statements), (SELECT COUNT(*) FROM entities), "
        "(SELECT COUNT(*) FROM names), (SELECT COUNT(*) FROM statement_links), "
        "(SELECT COUNT(*) FROM entity_links)"
    ).fetchone()
    statements, entities, names, links, entity_links = (int(n) for n in row)
    return SubstrateCounts(
        statements=statements,
        entities=entities,
        names=names,
        links=links,
        entity_links=entity_links,
    )


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
        where_parts.append(r"LOWER(target_id) LIKE ? ESCAPE '\'")
        params.append(f"%{_like_escape(query.lower())}%")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    base = f"SELECT * FROM ({_ACTIVITY_UNION}){where_sql}"

    total_row = conn.execute(f"SELECT COUNT(*) AS n FROM ({base})", params).fetchone()
    total = int(total_row["n"]) if total_row else 0

    rows = conn.execute(
        f"{base} ORDER BY at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return rows, total


def history_feed(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    ops: set[str],
    kinds: set[str],
    query: str,
) -> tuple[list[sqlite3.Row], int]:
    """Page over the attached transactional audit log, newest first.

    Unlike `activity_feed` (which reconstructs events from the live tables'
    `created_at`/`updated_at` and therefore cannot show deletes or a
    superseded update), this reads `history.history_events` — the durable
    record written in the same transaction as every state-changing write.
    Deletes, unlinks, and every historical update are all present.

    Requires a history DB to be attached (`has_history(conn)`); the caller
    is responsible for falling back to `activity_feed` when it isn't.

    Filters mirror `activity_feed`: `ops`/`kinds` are already-validated
    subsets, `query` is a stripped case-insensitive substring match on
    `target_id`, and `limit`/`offset` are pre-clamped. Ordering is by the
    monotonic `event_id` so equal timestamps keep a stable order.

    Returns `(rows, total)` where each row carries `event_id`, `at`, `op`,
    `target_kind`, `target_id`, `actor`, `before_json`, and `after_json`.
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
        where_parts.append(r"LOWER(target_id) LIKE ? ESCAPE '\'")
        params.append(f"%{_like_escape(query.lower())}%")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM history.history_events{where_sql}", params
    ).fetchone()
    total = int(total_row["n"]) if total_row else 0

    rows = conn.execute(
        "SELECT event_id, at, actor, op, target_kind, target_id, "
        "before_json, after_json, context_json "
        f"FROM history.history_events{where_sql} "
        "ORDER BY event_id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return rows, total
