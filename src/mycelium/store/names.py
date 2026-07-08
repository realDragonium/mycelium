"""Names: first-class references linking entities to statements."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Callable

from . import kernel
from .kernel import _now, _record, _row_dict

# --- names ------------------------------------------------------------------


def create_name(
    conn: sqlite3.Connection,
    text: str,
    entity_id: str,
    generated_from_name_id: str | None = None,
) -> str:
    """Create a name row. `generated_from_name_id` marks it as an
    auto-generated plural derived from another name (see
    `mycelium.plurals`); NULL means human-authored."""
    name_id = f"nam_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO names (id, text, entity_id, generated_from_name_id, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name_id, text, entity_id, generated_from_name_id, _now(), kernel._actor),
    )
    _record(
        conn,
        "create",
        "name",
        name_id,
        after=_row_dict(get_name_by_id(conn, name_id)),
    )
    return name_id


def get_generated_children(conn: sqlite3.Connection, name_id: str) -> list[sqlite3.Row]:
    """Names auto-generated from `name_id` (its regular plural). Used to
    keep generated plurals in lockstep with their source on delete/rename/
    move."""
    return conn.execute(
        "SELECT id, text, entity_id FROM names WHERE generated_from_name_id = ?",
        (name_id,),
    ).fetchall()


def get_name_by_text(conn: sqlite3.Connection, text: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, text, entity_id, generated_from_name_id, "
        "created_at, updated_at, created_by, updated_by "
        "FROM names WHERE text = ?",
        (text,),
    ).fetchone()


def get_name_by_id(conn: sqlite3.Connection, name_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, text, entity_id, generated_from_name_id, "
        "created_at, updated_at, created_by, updated_by "
        "FROM names WHERE id = ?",
        (name_id,),
    ).fetchone()


def get_names_by_entity(conn: sqlite3.Connection, entity_id: str) -> list[sqlite3.Row]:
    """All names attached to an entity, sorted by text alphabetically."""
    return conn.execute(
        "SELECT id, text FROM names WHERE entity_id = ? ORDER BY text",
        (entity_id,),
    ).fetchall()


def delete_name_mentions(conn: sqlite3.Connection, name_id: str) -> int:
    """Remove a name's derived mention rows — its `statement_mentions`
    (count returned) and its `pending_mentions` review-queue rows — so the
    name can be deleted under FK enforcement."""
    removed = conn.execute(
        "DELETE FROM statement_mentions WHERE name_id = ?", (name_id,)
    ).rowcount
    conn.execute("DELETE FROM pending_mentions WHERE name_id = ?", (name_id,))
    return removed


def delete_name(conn: sqlite3.Connection, name_id: str) -> None:
    """Delete a single name row. The caller must have cleared its derived
    mention rows (`delete_name_mentions`) and any generated-plural
    self-reference pointing at it first."""
    conn.execute("DELETE FROM names WHERE id = ?", (name_id,))


def delete_names_clearing_generated_refs(
    conn: sqlite3.Connection, name_ids: list[str]
) -> None:
    """Delete a batch of names that may reference each other as generated
    plurals: NULL out `generated_from_name_id` across the whole set first
    (the self-reference is a RESTRICT FK), then drop the rows."""
    if not name_ids:
        return
    conn.executemany(
        "UPDATE names SET generated_from_name_id = NULL WHERE id = ?",
        [(nid,) for nid in name_ids],
    )
    conn.executemany("DELETE FROM names WHERE id = ?", [(nid,) for nid in name_ids])


def list_entities(
    conn: sqlite3.Connection,
    prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Entities with their alphabetically-first name. Optional case-
    insensitive prefix filter on that name."""
    if prefix:
        rows = conn.execute(
            """
            SELECT e.id AS id, e.description AS description,
                   MIN(n.text) AS primary_name
            FROM entities e
            LEFT JOIN names n ON n.entity_id = e.id
            GROUP BY e.id
            HAVING primary_name LIKE ? COLLATE NOCASE
            ORDER BY primary_name
            LIMIT ? OFFSET ?
            """,
            (prefix + "%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT e.id AS id, e.description AS description,
                   MIN(n.text) AS primary_name
            FROM entities e
            LEFT JOIN names n ON n.entity_id = e.id
            GROUP BY e.id
            ORDER BY primary_name
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return rows


def list_statements(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
    entity_id: str | None = None,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Statements in insertion order (rowid ascending).

    When `entity_id` is given, restricts to statements mentioning any
    name attached to that entity. DISTINCT collapses statements that
    mention multiple aliases of the same entity to a single row. When
    `kind` is given, restricts to statements of that kind.
    """
    where: list[str] = []
    args: list[Any] = []
    if entity_id is not None:
        # Filter goes through the join below. Mark with a sentinel.
        pass
    if kind is not None:
        where.append("b.kind = ?")
        args.append(kind)
    kind_clause = (" AND " + " AND ".join(where)) if where else ""

    if entity_id is None:
        # No join needed; plain table scan with optional kind filter.
        sql = "SELECT id, kind, text FROM statements"
        kargs: list[Any] = []
        if kind is not None:
            sql += " WHERE kind = ?"
            kargs.append(kind)
        sql += " ORDER BY rowid LIMIT ? OFFSET ?"
        kargs.extend([limit, offset])
        return conn.execute(sql, kargs).fetchall()
    return conn.execute(
        f"""
        SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid
        FROM statements b
        JOIN statement_mentions bm ON bm.statement_id = b.id
        JOIN names n             ON n.id           = bm.name_id
        WHERE n.entity_id = ?{kind_clause}
        ORDER BY rid
        LIMIT ? OFFSET ?
        """,
        (entity_id, *args, limit, offset),
    ).fetchall()


def count_entities(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]


def _grep_match(case_sensitive: bool) -> tuple[str, Callable[[str], str]]:
    """Returns (sql_predicate_template, param_transform) for a literal
    substring match. Uses SQLite's `instr` so glob/regex chars in the
    query are matched literally without escape gymnastics. Case
    folding is via `lower(...)` on both sides."""
    if case_sensitive:
        return ("instr({col}, ?) > 0", lambda q: q)
    return ("instr(lower({col}), ?) > 0", lambda q: q.lower())


def grep_statements(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Statements whose `text` contains `query` as a literal substring.
    Insertion order. Optional case sensitivity, entity, and kind filters."""
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    kind_extra = " AND kind = ?" if kind is not None and entity_id is None else ""
    kind_extra_join = (
        " AND b.kind = ?" if kind is not None and entity_id is not None else ""
    )
    if entity_id is None:
        args: list[Any] = [needle]
        if kind is not None:
            args.append(kind)
        args.extend([limit, offset])
        return conn.execute(
            f"SELECT id, kind, text, rowid AS rid FROM statements "
            f"WHERE {predicate.format(col='text')}{kind_extra} "
            f"ORDER BY rowid LIMIT ? OFFSET ?",
            args,
        ).fetchall()
    args = [entity_id, needle]
    if kind is not None:
        args.append(kind)
    args.extend([limit, offset])
    return conn.execute(
        f"SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n              ON n.id           = bm.name_id "
        f"WHERE n.entity_id = ? AND {predicate.format(col='b.text')}{kind_extra_join} "
        f"ORDER BY rid LIMIT ? OFFSET ?",
        args,
    ).fetchall()


def grep_statements_via_mentions(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Statements that mention an entity whose *name* (any alias)
    contains `query` as a literal substring. The statement's own text
    is irrelevant — this is the alias-aware companion to
    `grep_statements`.

    The query is matched against every name of every mentioned entity,
    so a statement mentioning "Selection Flow" surfaces when the query
    is "tree" if that entity carries "tree" as an alias.

    A statement matching via multiple aliases / entities shows up once
    (DISTINCT on statement id). Ordered by insertion (rowid)."""
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    extra = " AND b.kind = ?" if kind else ""
    args: list[Any] = [needle]
    if kind:
        args.append(kind)
    # Two joins on names: n1 binds the mention to an entity (via the
    # name actually used in the mention), n2 walks every alias of that
    # entity. We match the substring against n2 so any alias counts.
    return conn.execute(
        f"SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n1 ON n1.id = bm.name_id "
        f"JOIN names n2 ON n2.entity_id = n1.entity_id "
        f"WHERE {predicate.format(col='n2.text')}{extra} "
        f"ORDER BY rid",
        args,
    ).fetchall()


def count_grep_statements(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    if entity_id is None:
        if kind is None:
            return conn.execute(
                f"SELECT COUNT(*) AS n FROM statements WHERE {predicate.format(col='text')}",
                (needle,),
            ).fetchone()["n"]
        return conn.execute(
            f"SELECT COUNT(*) AS n FROM statements "
            f"WHERE {predicate.format(col='text')} AND kind = ?",
            (needle, kind),
        ).fetchone()["n"]
    extra = " AND b.kind = ?" if kind is not None else ""
    args: list[Any] = [entity_id, needle]
    if kind is not None:
        args.append(kind)
    return conn.execute(
        f"SELECT COUNT(DISTINCT b.id) AS n "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n              ON n.id           = bm.name_id "
        f"WHERE n.entity_id = ? AND {predicate.format(col='b.text')}{extra}",
        args,
    ).fetchone()["n"]


def count_statements(
    conn: sqlite3.Connection,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    if entity_id is None:
        if kind is None:
            return conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()["n"]
        return conn.execute(
            "SELECT COUNT(*) AS n FROM statements WHERE kind = ?", (kind,)
        ).fetchone()["n"]
    extra = " AND b.kind = ?" if kind is not None else ""
    args: list[Any] = [entity_id]
    if kind is not None:
        args.append(kind)
    return conn.execute(
        f"""
        SELECT COUNT(DISTINCT b.id) AS n
        FROM statements b
        JOIN statement_mentions bm ON bm.statement_id = b.id
        JOIN names n             ON n.id           = bm.name_id
        WHERE n.entity_id = ?{extra}
        """,
        args,
    ).fetchone()["n"]


def reassign_names(
    conn: sqlite3.Connection, from_entity_id: str, to_entity_id: str
) -> int:
    """Move every name from one entity to another. Returns rows affected."""
    affected = conn.execute(
        "SELECT id FROM names WHERE entity_id = ?", (from_entity_id,)
    ).fetchall()
    befores = {r["id"]: _row_dict(get_name_by_id(conn, r["id"])) for r in affected}
    cur = conn.execute(
        "UPDATE names SET entity_id = ?, updated_at = ?, updated_by = ? "
        "WHERE entity_id = ?",
        (to_entity_id, _now(), kernel._actor, from_entity_id),
    )
    for nid, before in befores.items():
        _record(
            conn,
            "update",
            "name",
            nid,
            before=before,
            after=_row_dict(get_name_by_id(conn, nid)),
            context={"reason": "reassign_names", "from_entity_id": from_entity_id},
        )
    return cur.rowcount


def set_name_entity(conn: sqlite3.Connection, name_id: str, entity_id: str) -> None:
    before = _row_dict(get_name_by_id(conn, name_id))
    conn.execute(
        "UPDATE names SET entity_id = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (entity_id, _now(), kernel._actor, name_id),
    )
    _record(
        conn,
        "update",
        "name",
        name_id,
        before=before,
        after=_row_dict(get_name_by_id(conn, name_id)),
        context={"reason": "set_name_entity"},
    )


def rename_name(conn: sqlite3.Connection, name_id: str, new_text: str) -> None:
    """Change a name's `text` in place without changing its id or its
    entity binding. Statements that mentioned this name
    keep pointing at the same name_id and start rendering under the new
    text.

    Raises ValueError if the name_id is unknown, or if the new text is
    already used by a different name (caller should use `merge_entities`
    or `move_name` to resolve such a clash before retrying)."""
    row = conn.execute(
        "SELECT entity_id, text FROM names WHERE id = ?", (name_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"name {name_id!r} does not exist")
    if row["text"] == new_text:
        return
    clash = conn.execute(
        "SELECT id, entity_id FROM names WHERE text = ?", (new_text,)
    ).fetchone()
    if clash is not None and clash["id"] != name_id:
        raise ValueError(
            f"name text {new_text!r} is already used by name {clash['id']!r} "
            f"on entity {clash['entity_id']!r}; "
            "use merge_entities or move_name to resolve"
        )
    before = _row_dict(get_name_by_id(conn, name_id))
    conn.execute(
        "UPDATE names SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (new_text, _now(), kernel._actor, name_id),
    )
    _record(
        conn,
        "update",
        "name",
        name_id,
        before=before,
        after=_row_dict(get_name_by_id(conn, name_id)),
        context={"reason": "rename_name"},
    )
