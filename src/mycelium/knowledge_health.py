"""What needs a curator's attention: knowledge nothing reaches, and the queues
waiting on someone.

Every count is one indexed aggregate in SQL, and every list a keyset page, so
neither grows with the size of the knowledge base beyond the scan itself.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from typing import Literal, get_args

from pydantic import BaseModel

from . import document_freshness
from .ingest.connect import Target

StatementFilter = Literal["isolated", "unmentioned", "unlabelled"]
EntityFilter = Literal["undescribed", "unused"]
Filter = StatementFilter | EntityFilter
STATEMENT_FILTERS: tuple[StatementFilter, ...] = get_args(StatementFilter)
ENTITY_FILTERS: tuple[EntityFilter, ...] = get_args(EntityFilter)

_UNLINKED = (
    "NOT EXISTS (SELECT 1 FROM statement_links l WHERE l.from_statement_id = s.id) "
    "AND NOT EXISTS (SELECT 1 FROM statement_links l WHERE l.to_statement_id = s.id) "
    "AND NOT EXISTS (SELECT 1 FROM when_nodes w WHERE w.statement_id = s.id)"
)
_STATEMENT_WHERE: dict[StatementFilter, str] = {
    "isolated": _UNLINKED,
    "unmentioned": (
        "NOT EXISTS (SELECT 1 FROM statement_mentions m WHERE m.statement_id = s.id)"
    ),
    "unlabelled": (
        "NOT EXISTS (SELECT 1 FROM statement_audience_labels a "
        "WHERE a.statement_id = s.id)"
    ),
}
_ENTITY_WHERE: dict[EntityFilter, str] = {
    "undescribed": "TRIM(COALESCE(e.description, '')) = ''",
    "unused": (
        "NOT EXISTS (SELECT 1 FROM names n JOIN statement_mentions m "
        "ON m.name_id = n.id WHERE n.entity_id = e.id)"
    ),
}


class Counts(BaseModel):
    statements: int
    entities: int
    isolated: int
    unmentioned: int
    undescribed: int
    unused: int
    unlabelled: int
    #: Unlabelled statements whose last labelling attempt failed.
    labelling_failed: int
    open_gaps: int
    #: Drafts not yet decided: open with their author, or submitted.
    pending_drafts: int
    out_of_date_documents: int


def counts(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    substrate: Callable[[], sqlite3.Connection],
) -> Counts:
    statement_counts = ", ".join(
        f"(SELECT COUNT(*) FROM statements s WHERE {where}) AS {name}"
        for name, where in _STATEMENT_WHERE.items()
    )
    entity_counts = ", ".join(
        f"(SELECT COUNT(*) FROM entities e WHERE {where}) AS {name}"
        for name, where in _ENTITY_WHERE.items()
    )
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM statements) AS statements, "
        "(SELECT COUNT(*) FROM entities) AS entities, "
        f"{statement_counts}, {entity_counts}, "
        "(SELECT COUNT(*) FROM audience_label_queue q WHERE q.last_error IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM statement_audience_labels a "
        "WHERE a.statement_id = q.statement_id)) AS labelling_failed, "
        "(SELECT COUNT(*) FROM knowledge_gaps "
        "WHERE resolved_at IS NULL AND dismissed_at IS NULL) AS open_gaps"
    ).fetchone()
    pending = drafts.execute(
        "SELECT COUNT(*) FROM drafts WHERE decided_at IS NULL"
    ).fetchone()[0]
    document_ids = [
        str(r[0]) for r in drafts.execute("SELECT id FROM generated_documents")
    ]
    freshness = document_freshness.for_documents(drafts, substrate, document_ids)
    return Counts(
        **{key: int(row[key]) for key in row.keys()},
        pending_drafts=int(pending),
        out_of_date_documents=sum(
            1 for f in freshness.values() if f.status == "out_of_date"
        ),
    )


class StatementItem(BaseModel):
    id: str
    kind: str
    text: str
    links: int
    #: Names of the concepts the text mentions.
    mentions: list[str]
    #: Why labelling last failed, while it has no label.
    label_error: str | None
    #: An undecided draft already proposes links or aliases for it.
    in_pending_draft: bool


class EntityItem(BaseModel):
    id: str
    name: str | None
    description: str | None


class StatementPage(BaseModel):
    filter: StatementFilter
    items: list[StatementItem]
    next_after: str | None


class EntityPage(BaseModel):
    filter: EntityFilter
    items: list[EntityItem]
    next_after: str | None


def pending_statement_ids(drafts: sqlite3.Connection) -> set[str]:
    """Statements an undecided draft already links or names an alias from."""
    rows = drafts.execute(
        "SELECT json_extract(l.value, '$.from_id'), json_extract(l.value, '$.to_id') "
        "FROM drafts d JOIN draft_ops o ON o.draft_id = d.id, "
        "json_each(o.payload_json, '$.links') l "
        "WHERE d.decided_at IS NULL AND o.kind = 'add_links' "
        "AND json_valid(o.payload_json) "
        "UNION ALL SELECT json_extract(o.payload_json, '$.evidence.statement_id'), "
        "json_extract(o.payload_json, '$.proposal.statement_id') "
        "FROM drafts d JOIN draft_ops o ON o.draft_id = d.id "
        "WHERE d.decided_at IS NULL AND o.kind = 'alias_suggestion' "
        "AND json_valid(o.payload_json)"
    )
    return {str(v) for row in rows for v in row if isinstance(v, str)}


def statements(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    which: StatementFilter,
    *,
    after: str | None = None,
    limit: int = 50,
    skip_pending: bool = False,
) -> StatementPage:
    """A page of statements matching `which`, in id order."""
    pending = pending_statement_ids(drafts)
    chosen: list[sqlite3.Row] = []
    cursor = after or ""
    next_after: str | None = None
    while next_after is None:
        rows = conn.execute(
            f"SELECT s.id, s.kind, s.text FROM statements s "
            f"WHERE s.id > ? AND {_STATEMENT_WHERE[which]} ORDER BY s.id LIMIT ?",
            (cursor, limit),
        ).fetchall()
        for row in rows:
            if len(chosen) == limit:
                next_after = str(chosen[-1]["id"])
                break
            cursor = str(row["id"])
            if not (skip_pending and cursor in pending):
                chosen.append(row)
        if next_after is None and len(rows) < limit:
            break
    return StatementPage(
        filter=which,
        items=_statement_items(conn, chosen, pending),
        next_after=next_after,
    )


def _statement_items(
    conn: sqlite3.Connection, rows: Sequence[sqlite3.Row], pending: set[str]
) -> list[StatementItem]:
    ids = [str(r["id"]) for r in rows]
    if not ids:
        return []
    marks = ", ".join("?" for _ in ids)
    links: dict[str, int] = {}
    for row in conn.execute(
        f"SELECT id, (SELECT COUNT(*) FROM statement_links WHERE from_statement_id = id)"
        f" + (SELECT COUNT(*) FROM statement_links WHERE to_statement_id = id) "
        f"FROM statements WHERE id IN ({marks})",
        ids,
    ):
        links[str(row[0])] = int(row[1])
    names: dict[str, list[str]] = {}
    for row in conn.execute(
        f"SELECT m.statement_id, n.text FROM statement_mentions m "
        f"JOIN names n ON n.id = m.name_id WHERE m.statement_id IN ({marks}) "
        "ORDER BY n.text",
        ids,
    ):
        names.setdefault(str(row[0]), []).append(str(row[1]))
    errors = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            f"SELECT q.statement_id, q.last_error FROM audience_label_queue q "
            f"WHERE q.statement_id IN ({marks}) AND q.last_error IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM statement_audience_labels a "
            "WHERE a.statement_id = q.statement_id)",
            ids,
        )
    }
    return [
        StatementItem(
            id=str(r["id"]),
            kind=str(r["kind"]),
            text=str(r["text"]),
            links=links.get(str(r["id"]), 0),
            mentions=names.get(str(r["id"]), []),
            label_error=errors.get(str(r["id"])),
            in_pending_draft=str(r["id"]) in pending,
        )
        for r in rows
    ]


def entities(
    conn: sqlite3.Connection,
    which: EntityFilter,
    *,
    after: str | None = None,
    limit: int = 50,
) -> EntityPage:
    """A page of entities matching `which`, in id order."""
    rows = conn.execute(
        "SELECT e.id, e.description, n.text AS name FROM entities e "
        "LEFT JOIN names n ON n.id = COALESCE(e.preferred_name_id, "
        "(SELECT MIN(id) FROM names WHERE entity_id = e.id)) "
        f"WHERE e.id > ? AND {_ENTITY_WHERE[which]} ORDER BY e.id LIMIT ?",
        (after or "", limit + 1),
    ).fetchall()
    page = rows[:limit]
    return EntityPage(
        filter=which,
        items=[
            EntityItem(
                id=str(r["id"]),
                name=None if r["name"] is None else str(r["name"]),
                description=None if r["description"] is None else str(r["description"]),
            )
            for r in page
        ],
        next_after=str(page[-1]["id"]) if len(rows) > limit else None,
    )


def targets(conn: sqlite3.Connection, ids: Sequence[str]) -> list[Target]:
    """The connect pass's view of `ids`, in the order given.

    Raises ValueError naming any id that is not a statement.
    """
    unique = list(dict.fromkeys(ids))
    rows = {
        str(r["id"]): r
        for r in conn.execute(
            "SELECT id, kind, text FROM statements WHERE id IN "
            f"({', '.join('?' for _ in unique)})",
            unique,
        )
    }
    missing = [i for i in unique if i not in rows]
    if missing:
        raise ValueError(f"not a statement: {', '.join(missing)}")
    items = {i.id: i for i in _statement_items(conn, list(rows.values()), set())}
    return [
        Target(
            id=i,
            kind=items[i].kind,
            text=items[i].text,
            mentions=tuple(items[i].mentions),
            links=items[i].links,
        )
        for i in unique
    ]
