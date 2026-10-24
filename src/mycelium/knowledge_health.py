"""What needs a curator's attention: knowledge nothing reaches, and the queues
waiting on someone.

Every count is one indexed aggregate in SQL, and every list a keyset page, so
neither grows with the size of the knowledge base beyond the scan itself.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Literal, get_args

from pydantic import BaseModel

from . import document_freshness, media, media_store
from .ingest.connect import Target
from .store import kernel

StatementFilter = Literal["isolated", "unmentioned", "unlabelled"]
EntityFilter = Literal["undescribed", "unused"]
Filter = StatementFilter | EntityFilter
STATEMENT_FILTERS: tuple[StatementFilter, ...] = get_args(StatementFilter)

_UNLINKED = (
    "NOT EXISTS (SELECT 1 FROM statement_links l WHERE l.from_statement_id = s.id) "
    "AND NOT EXISTS (SELECT 1 FROM statement_links l WHERE l.to_statement_id = s.id) "
    "AND NOT EXISTS (SELECT 1 FROM when_nodes w WHERE w.statement_id = s.id)"
)
STATEMENT_WHERE: dict[StatementFilter, str] = {
    "isolated": _UNLINKED,
    "unmentioned": (
        "NOT EXISTS (SELECT 1 FROM statement_mentions m WHERE m.statement_id = s.id)"
    ),
    "unlabelled": (
        "NOT EXISTS (SELECT 1 FROM statement_audience_labels a "
        "WHERE a.statement_id = s.id)"
    ),
}
ENTITY_WHERE: dict[EntityFilter, str] = {
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
    #: Media older than the configured age or captured against an older
    #: product version.
    old_media: int


def counts(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    substrate: Callable[[], sqlite3.Connection],
) -> Counts:
    statement_counts = ", ".join(
        f"(SELECT COUNT(*) FROM statements s WHERE {where}) AS {name}"
        for name, where in STATEMENT_WHERE.items()
    )
    entity_counts = ", ".join(
        f"(SELECT COUNT(*) FROM entities e WHERE {where}) AS {name}"
        for name, where in ENTITY_WHERE.items()
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
        old_media=media.counts().old if media_store.is_configured() else 0,
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
    #: When the connect pass last looked at it, while neither its text nor
    #: its neighbourhood has changed since.
    settled_at: str | None


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


#: An attempt still holds for `s`: it was not skipped, its text is
#: unchanged, no statement the attempt weighed has changed or gone, and no
#: statement naming one of the same concepts has been written since.
SETTLED = (
    "EXISTS (SELECT 1 FROM curation_attempts c WHERE c.item_id = s.id "
    "AND c.outcome <> 'skipped' AND c.text = s.text "
    "AND NOT EXISTS (SELECT 1 FROM json_each(c.neighbours) j "
    "LEFT JOIN statements n ON n.id = j.value "
    "WHERE n.id IS NULL OR COALESCE(n.updated_at, n.created_at, '') > c.attempted_at) "
    "AND NOT EXISTS (SELECT 1 FROM statement_mentions m "
    "JOIN names mine ON mine.id = m.name_id "
    "JOIN names theirs ON theirs.entity_id = mine.entity_id "
    "JOIN statement_mentions om ON om.name_id = theirs.id "
    "JOIN statements o ON o.id = om.statement_id "
    "WHERE m.statement_id = s.id AND o.id <> s.id "
    "AND COALESCE(o.updated_at, o.created_at, '') > c.attempted_at))"
)

#: An outside agent holds `s` (see `curation`); bound to the current time.
CLAIMED = (
    "EXISTS (SELECT 1 FROM curation_claims k WHERE k.item_id = s.id "
    "AND k.expires_at > :now)"
)


def statements(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    which: StatementFilter,
    *,
    after: str | None = None,
    limit: int = 50,
) -> StatementPage:
    """A page of statements matching `which`, in id order."""
    rows = conn.execute(
        f"SELECT s.id, s.kind, s.text FROM statements s "
        f"WHERE s.id > ? AND {STATEMENT_WHERE[which]} ORDER BY s.id LIMIT ?",
        (after or "", limit + 1),
    ).fetchall()
    page = rows[:limit]
    return StatementPage(
        filter=which,
        items=_statement_items(conn, page, pending_statement_ids(drafts)),
        next_after=str(page[-1]["id"]) if len(rows) > limit else None,
    )


#: How many linked statements name one of the concepts `s` names. A
#: statement beside connected knowledge is the likeliest to find a partner;
#: one naming nothing, or only concepts nothing links around, the least.
_CONNECTED_NEIGHBOURS = (
    "(SELECT COUNT(DISTINCT om.statement_id) FROM statement_mentions m "
    "JOIN names mine ON mine.id = m.name_id "
    "JOIN names theirs ON theirs.entity_id = mine.entity_id "
    "JOIN statement_mentions om ON om.name_id = theirs.id "
    "WHERE m.statement_id = s.id AND om.statement_id <> s.id "
    "AND (EXISTS (SELECT 1 FROM statement_links l "
    "WHERE l.from_statement_id = om.statement_id) "
    "OR EXISTS (SELECT 1 FROM statement_links l "
    "WHERE l.to_statement_id = om.statement_id)))"
)


def to_connect(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    which: StatementFilter,
    *,
    limit: int,
) -> StatementPage:
    """The statements matching `which` the connect pass should take next,
    likeliest to connect first. Leaves out what it should not be offered
    again: statements an undecided draft covers, settled attempts, items
    an agent holds and statements a connect task waits on."""
    from .ingest import external

    pending = pending_statement_ids(drafts) | external.connecting(drafts)
    rows = conn.execute(
        f"SELECT s.id, s.kind, s.text FROM statements s "
        f"WHERE {STATEMENT_WHERE[which]} AND NOT {SETTLED} AND NOT {CLAIMED} "
        f"ORDER BY {_CONNECTED_NEIGHBOURS} DESC, s.id",
        {"now": kernel._now()},
    )
    chosen = [row for row in rows if str(row["id"]) not in pending][:limit]
    return StatementPage(
        filter=which, items=_statement_items(conn, chosen, pending), next_after=None
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
    settled = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            f"SELECT s.id, (SELECT attempted_at FROM curation_attempts "
            f"WHERE item_id = s.id) FROM statements s "
            f"WHERE s.id IN ({marks}) AND {SETTLED}",
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
            settled_at=settled.get(str(r["id"])),
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
        f"WHERE e.id > ? AND {ENTITY_WHERE[which]} ORDER BY e.id LIMIT ?",
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


def record_attempts(
    conn: sqlite3.Connection, attempts: Mapping[str, Sequence[str]]
) -> None:
    """Remember that the connect pass looked at each statement in `attempts`,
    with the statements it weighed for it."""
    now = kernel._now()
    conn.executemany(
        "INSERT OR REPLACE INTO curation_attempts "
        "(item_id, text, neighbours, attempted_at, outcome) "
        "SELECT id, text, ?, ?, 'looked' FROM statements WHERE id = ?",
        [
            (json.dumps(sorted(set(neighbours))), now, statement_id)
            for statement_id, neighbours in attempts.items()
        ],
    )


#: How the connect pass opens the knowledge gap asking for a statement to be
#: rephrased; the curation queue's `rephrase` kind finds those gaps by it.
REPHRASE_GAP_PREFIX = "Rephrase this statement before it is connected: "


def has_open_gap(conn: sqlite3.Connection, statement_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM knowledge_gaps WHERE statement_id = ? "
            "AND resolved_at IS NULL AND dismissed_at IS NULL",
            (statement_id,),
        ).fetchone()
        is not None
    )
