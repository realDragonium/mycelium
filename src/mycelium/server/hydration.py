"""Hydrating a statement id into the shape every statement read returns.

`get_statements`, the search surfaces and the graph walk all hydrate through
`_hydrate_statement_full`, so a hit arrives with its mentions, links and
reverse edges and needs no follow-up fetch. The wide surfaces cap the reverse
edges per hit; a targeted `get_statements` does not.
"""

from __future__ import annotations

from typing import Any

from .. import store
from ..require import require
from .runtime import _db


def _link_dict(
    *,
    to_id: str | None = None,
    from_id: str | None = None,
    link_type: str,
    when: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the response dict for an edge, omitting `when` when None so
    unconditional edges keep the simpler shape callers expect.

    The endpoint field is `from_id` / `to_id`, and its value is a
    statement id (`stm_…`)."""
    out: dict[str, Any] = {"link_type": link_type}
    if to_id is not None:
        out["to_id"] = to_id
    if from_id is not None:
        out["from_id"] = from_id
    if when is not None:
        out["when"] = when
    return out


def _hydrate_statement(statement_id: str, score: float | None) -> dict[str, Any]:
    row = require(store.get_statement(_db(), statement_id), "statement to hydrate")
    mentions = [
        {"name_id": m["name_id"], "name": m["name"], "entity_id": m["entity_id"]}
        for m in store.get_mentions(_db(), statement_id)
    ]
    links = [
        _link_dict(to_id=to_id, link_type=lt, when=when)
        for to_id, lt, when in store.get_links(_db(), statement_id)
    ]
    out: dict[str, Any] = {
        "id": row["id"],
        "kind": row["kind"],
        "text": row["text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "mentions": mentions,
        "links": links,
    }
    if score is not None:
        out["score"] = score
    return out


#: Per-hit cap on reverse-graph edges (incoming_links + when_references) when a
#: statement is hydrated by a wide surface such as search. Bounds the
#: convergence-hub blowup `search_statements` warns about: a hub with hundreds
#: of incoming `configures` / `governed-by` edges would otherwise dominate the
#: result. When capped, a `*_truncated` count tells the caller to
#: `get_statements([id])` for the complete set. `get_statements` is uncapped —
#: it is an explicit, targeted fetch.
_REVERSE_EDGE_CAP = 25


def _hydrate_statement_full(
    statement_id: str, score: float | None, *, reverse_cap: int | None = None
) -> dict[str, Any]:
    """`_hydrate_statement` plus the reverse-graph edges (`incoming_links` and
    `when_references`) — the full shape `get_statements` returns.

    The single hydration path shared by `get_statements` and
    `search_statements`, so a search hit arrives fully hydrated and needs no
    follow-up `get_statements` on the same id just to learn what points at it.
    `reverse_cap` bounds each reverse-edge list (search passes it;
    `get_statements` passes None)."""
    out = _hydrate_statement(statement_id, score=score)

    incoming = [
        _link_dict(from_id=from_id, link_type=lt, when=when)
        for from_id, lt, when in store.get_incoming_links(_db(), statement_id)
    ]
    when_refs: list[dict[str, Any]] = [
        {"from_id": from_id, "to_id": to_id, "link_type": lt, "when": when_tree}
        for from_id, to_id, lt, when_tree in store.get_when_references(
            _db(), statement_id
        )
    ]
    if reverse_cap is not None and len(incoming) > reverse_cap:
        out["incoming_links_truncated"] = len(incoming)
        incoming = incoming[:reverse_cap]
    if reverse_cap is not None and len(when_refs) > reverse_cap:
        out["when_references_truncated"] = len(when_refs)
        when_refs = when_refs[:reverse_cap]
    out["incoming_links"] = incoming
    out["when_references"] = when_refs
    return out


def _expand_graph(seen: set[str], depth: int, direction: str) -> list[dict[str, Any]]:
    """BFS neighborhood expansion from the direct hits, up to `depth` hops.
    Mutates `seen` as it walks so a node is hydrated at most once. Expanded
    statements carry no `score` field."""
    follow_children = direction in ("both", "children")
    follow_parents = direction in ("both", "parents")

    expanded: list[dict[str, Any]] = []
    frontier: set[str] = set(seen)
    for _ in range(depth):
        next_frontier: set[str] = set()
        for bid in frontier:
            if follow_children:
                for to_id, _lt, _when in store.get_links(_db(), bid):
                    if to_id not in seen:
                        seen.add(to_id)
                        next_frontier.add(to_id)
            if follow_parents:
                for from_id, _lt, _when in store.get_incoming_links(_db(), bid):
                    if from_id not in seen:
                        seen.add(from_id)
                        next_frontier.add(from_id)
        for bid in next_frontier:
            expanded.append(
                _hydrate_statement_full(bid, score=None, reverse_cap=_REVERSE_EDGE_CAP)
            )
        if not next_frontier:
            break
        frontier = next_frontier

    return expanded
