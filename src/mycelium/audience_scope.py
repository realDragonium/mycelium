"""The hard audience boundary around a documentation run's substrate reads.

While a scoped read runs, TEMP views shadow the substrate tables on the
calling thread's connection. SQLite resolves an unqualified table name to
the temp schema first, so every read primitive, its counts and its link
hydration see only what the audience may see, and the statement vector
index ranks only visible statements. A read tool needs no audience logic of
its own, and a write against a shadowed table fails instead of leaking.

What an audience sees:

* statements its labels grant (unlabelled ones only for internal audiences);
* statement links whose ends, and every statement in their condition, are
  visible;
* entities that a visible statement mentions. Entity descriptions and entity
  links are unlabelled curator prose, so they fail closed exactly like an
  unlabelled statement: internal audiences see them, external ones do not;
* for external audiences, only the names visible statements were matched
  through, so an internal alias or codename of a visible entity stays out.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from . import store
from .agentloop import substrate_has
from .ask.substrate import SubstrateReader, ToolSpec
from .audiences import Audience


@dataclass(frozen=True)
class Scope:
    audience: Audience
    statement_ids: frozenset[str]
    vector_ids: frozenset[int]


_active: ContextVar[Scope | None] = ContextVar("audience_scope", default=None)


def active() -> Scope | None:
    return _active.get()


def capture(conn: sqlite3.Connection, audience: Audience) -> Scope:
    """Snapshot what `audience` may see. Held for the whole run, so the
    citation gate and every read agree even while labels change."""
    ids = store.visible_statement_ids(conn, audience.id, audience.internal)
    vectors = frozenset(
        int(row["vector_id"])
        for row in conn.execute(
            "SELECT statement_id, vector_id FROM statement_vector_ids"
        )
        if row["statement_id"] in ids
    )
    return Scope(audience, ids, vectors)


_VIEWS: tuple[tuple[str, str], ...] = (
    (
        "statements",
        "SELECT * FROM main.statements WHERE id IN (SELECT id FROM temp.audience_visible)",
    ),
    (
        "statement_vector_ids",
        "SELECT * FROM main.statement_vector_ids "
        "WHERE statement_id IN (SELECT id FROM temp.audience_visible)",
    ),
    (
        "statement_links",
        "SELECT * FROM main.statement_links l "
        "WHERE l.from_statement_id IN (SELECT id FROM temp.audience_visible) "
        "AND l.to_statement_id IN (SELECT id FROM temp.audience_visible) "
        "AND NOT EXISTS (SELECT 1 FROM main.when_nodes w WHERE w.link_id = l.link_id "
        "AND w.statement_id IS NOT NULL "
        "AND w.statement_id NOT IN (SELECT id FROM temp.audience_visible))",
    ),
    (
        "when_nodes",
        "SELECT * FROM main.when_nodes WHERE link_id IN (SELECT link_id FROM temp.statement_links)",
    ),
    (
        "statement_mentions",
        "SELECT * FROM main.statement_mentions "
        "WHERE statement_id IN (SELECT id FROM temp.audience_visible)",
    ),
    (
        "pending_mentions",
        "SELECT * FROM main.pending_mentions "
        "WHERE statement_id IN (SELECT id FROM temp.audience_visible)",
    ),
)


def _entity_views(internal: bool) -> tuple[tuple[str, str], ...]:
    entities = (
        "SELECT DISTINCT n.entity_id FROM main.names n "
        "JOIN temp.statement_mentions m ON m.name_id = n.id"
    )
    names = (
        f"SELECT * FROM main.names WHERE entity_id IN ({entities})"
        if internal
        else "SELECT * FROM main.names WHERE id IN "
        "(SELECT name_id FROM temp.statement_mentions)"
    )
    description = "description" if internal else "NULL AS description"
    return (
        ("names", names),
        (
            "name_vector_ids",
            "SELECT * FROM main.name_vector_ids WHERE name_id IN (SELECT id FROM temp.names)",
        ),
        (
            "entities",
            f"SELECT e.id, {description}, "
            "CASE WHEN e.preferred_name_id IN (SELECT id FROM temp.names) "
            "THEN e.preferred_name_id END AS preferred_name_id, "
            "e.created_at, e.updated_at, e.created_by, e.updated_by "
            f"FROM main.entities e WHERE e.id IN ({entities})",
        ),
        (
            "entity_links",
            "SELECT * FROM main.entity_links "
            "WHERE from_entity_id IN (SELECT id FROM temp.entities) "
            "AND to_entity_id IN (SELECT id FROM temp.entities)"
            if internal
            else "SELECT * FROM main.entity_links WHERE 0",
        ),
    )


@contextmanager
def applied(conn: sqlite3.Connection, scope: Scope) -> Iterator[None]:
    """Shadow the substrate on `conn` for the duration of the block."""
    if _active.get() is not None:
        raise RuntimeError("audience scope is already applied on this context")
    opened = not conn.in_transaction
    views = _VIEWS + _entity_views(scope.audience.internal)
    conn.execute("CREATE TEMP TABLE audience_visible (id TEXT PRIMARY KEY)")
    try:
        conn.executemany(
            "INSERT INTO temp.audience_visible VALUES (?)",
            [(item,) for item in scope.statement_ids],
        )
        for name, select in views:
            conn.execute(f"CREATE TEMP VIEW {name} AS {select}")
        token = _active.set(scope)
        try:
            yield
        finally:
            _active.reset(token)
    finally:
        for name, _select in reversed(views):
            conn.execute(f"DROP VIEW IF EXISTS temp.{name}")
        conn.execute("DROP TABLE IF EXISTS temp.audience_visible")
        # The temp inserts opened a transaction; holding it would pin this
        # connection's read snapshot for the next caller on the thread.
        if opened and conn.in_transaction:
            conn.commit()


class ScopedSubstrate:
    """A `SubstrateReader` whose every call runs inside the audience scope."""

    def __init__(self, inner: SubstrateReader, scope: Scope) -> None:
        self._inner = inner
        self.scope = scope

    def tool_specs(self) -> list[ToolSpec]:
        return self._inner.tool_specs()

    def has(self, name: str) -> bool:
        return substrate_has(self._inner, name)

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        with applied(store.substrate_connection(), self.scope):
            return self._inner.call(name, arguments)


def scoped(inner: SubstrateReader, audience: Audience) -> ScopedSubstrate:
    return ScopedSubstrate(inner, capture(store.substrate_connection(), audience))
