"""Adding and removing typed links between existing statements.

Both endpoints must already be statements; entity edges have their own
vocabulary and tools (`entities`). A link is identified by its endpoints, type
and canonical condition, so `remove_links` matches a condition by meaning
rather than by the literal shape `add_links` was sent.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import link_authoring, store, when_expression
from .registry import draftable_tool
from .runtime import _db
from .specs import EdgeSpec
from .write_checks import _collect_flip_errors


def _id_kind(id: str) -> str:
    """Classify an endpoint id by its statement or entity prefix."""
    if id.startswith("stm_"):
        return "statement"
    if id.startswith("ent_"):
        return "entity"
    raise ValueError(
        f"id {id!r} is not recognized as a statement (stm_…) or entity (ent_…)"
    )


def _statement_edges(
    links: list[EdgeSpec],
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Convert statement↔statement edges to store tuples.

    Raises ValueError on every entity endpoint and on unknown id prefixes.
    Entity↔entity edges belong on `add_entity_links`."""
    stmt_edges: list[tuple[str, str, str, dict[str, Any] | None]] = []
    for link in links:
        fk = _id_kind(link["from_id"])
        tk = _id_kind(link["to_id"])
        when = link.get("when")
        if fk == "statement" and tk == "statement":
            stmt_edges.append((link["from_id"], link["to_id"], link["link_type"], when))
        elif fk == "entity" and tk == "entity":
            raise ValueError(
                f"entity↔entity edge {link['from_id']!r} → {link['to_id']!r} is not "
                "supported by add_links/remove_links; use "
                "add_entity_links/remove_entity_links instead"
            )
        else:
            raise ValueError(
                f"entity↔statement edge {link['from_id']!r} → "
                f"{link['to_id']!r} is not supported: add_links/remove_links "
                "handle statement↔statement only"
            )
    return stmt_edges


def _validate_edge_endpoints(links: list[EdgeSpec]) -> dict[str, sqlite3.Row]:
    """Validate every endpoint and `when` leaf references a statement that exists.

    Raises ValueError on any unknown id. Returns the fetched statement rows
    keyed by id for downstream kind lookups."""
    needed_statements: set[str] = set()
    for link in links:
        needed_statements.update((link["from_id"], link["to_id"]))
        if "when" in link:
            when_expression.validate(link["when"])
            needed_statements.update(when_expression.leaves(link["when"]))
    statement_rows: dict[str, sqlite3.Row] = {}
    for sid in needed_statements:
        row = store.get_statement(_db(), sid)
        if row is None:
            raise ValueError(f"statement {sid!r} does not exist")
        statement_rows[sid] = row
    return statement_rows


@draftable_tool
def add_links(links: list[EdgeSpec]) -> dict[str, int]:
    """Insert one or more statement-to-statement typed edges.

    Use `add_entity_links` for entity↔entity edges.

    Direction note: source is the bigger/earlier/wrapping/primary side;
    target is the smaller/later/contained/dependent side. Before
    committing an edge, read it aloud as "FROM <link_type> TO" and check
    it against the link type's description. For constrained statement
    link types, provably flipped edges detected by statement kind are
    rejected; e.g. `teaches` is `procedure -> capability`, so
    `capability -> procedure` fails and should be swapped.

    Idempotent — pre-existing edges (matched on the canonical
    `(from, to, link_type, when_hash)`) are silently skipped, so the
    count returned can be smaller than the number of `links` you
    passed. Validates that every `from_id`, `to_id`, and every
    `statement_id` leaf inside any `when` tree exists before mutating;
    raises ValueError on any unknown id. `when` leaves are always
    statement ids, using the statement-link `when` grammar.

    No re-embedding is performed — this is the cheap path for adding
    relationships between existing nodes. To add a single edge, pass a
    one-element list.
    """
    if not links:
        return {"inserted": 0}

    link_authoring.reject_entity_statement_additions(links)

    stmt_edges = _statement_edges(links)

    statement_rows = _validate_edge_endpoints(links)

    flip_edges: list[tuple[str, str, str, str, str, str]] = []
    for i, link in enumerate(links):
        from_kind = statement_rows[link["from_id"]]["kind"]
        to_kind = statement_rows[link["to_id"]]["kind"]
        flip_edges.append(
            (
                f"links[{i}]",
                link["from_id"],
                link["to_id"],
                link["link_type"],
                from_kind,
                to_kind,
            )
        )
    flip_errors = _collect_flip_errors(flip_edges)
    if flip_errors:
        raise ValueError("flipped link direction:\n" + "\n".join(flip_errors))

    inserted = 0
    with store.transaction(_db()):
        inserted = store.insert_links(_db(), stmt_edges)
    return {"inserted": inserted}


@draftable_tool
def remove_links(links: list[EdgeSpec]) -> dict[str, int]:
    """Remove one or more typed statement↔statement edges.

    Both endpoints must be statement ids (`stm_…`). Every edge with an
    entity endpoint is rejected; entity↔entity edges use `remove_entity_links`.

    Match is by canonicalized when expression — the literal shape sent
    here doesn't have to match what was originally sent to `add_links`,
    only the canonical form does (e.g. `(A AND B)` and `(B AND A)` are
    the same edge). Returns the count of rows actually deleted; missing
    edges are silently skipped (so this is idempotent — calling it
    twice with the same input is fine). Does not validate that the
    endpoints exist; deleting an edge that references a non-existent
    node is just a no-op.
    """
    if not links:
        return {"removed": 0}

    stmt_edges = _statement_edges(links)

    removed = 0
    with store.transaction(_db()):
        removed = store.delete_links(_db(), stmt_edges)
    return {"removed": removed}
