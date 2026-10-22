"""Typed parameter shapes that several tool signatures share.

They are part of the public contract: MCP and the REST mirror derive their
JSON schemas from these classes, docstrings included, so a field or docstring
edit here changes what every client is sent.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from pydantic import Field


class LinkSpec(TypedDict):
    """An outgoing typed edge from this statement to an existing target.

    Used inside `upsert_statement` for the `links` parameter, where "this
    statement" is implicit (the one being created or updated).

    `when` is an optional condition expression — a tree of AND/OR/NOT
    over statement_id leaves:

        {"statement_id": "stm_X"}                            # leaf
        {"op": "and", "of": [<expr>, <expr>, ...]}          # AND (>=1 child)
        {"op": "or",  "of": [<expr>, <expr>, ...]}          # OR  (>=1 child)
        {"op": "not", "of": [<expr>]}                       # NOT (exactly 1 child)

    Reads "this — link_type → target when <expression>". Two edges with
    the same `(from, to, link_type)` but different `when` are distinct
    conditional pathways. The substrate canonicalizes every when-tree
    on write (sorts AND/OR children, dedupes, flattens same-op nesting,
    collapses single-child AND/OR, folds NOT(NOT(X)) → X) and identifies
    links by `(from, to, link_type, hash(canonical_when))` — so `(A AND
    B)` and `(B AND A)` are the same link, but `(A AND B)` and `(A OR
    B)` are distinct. NOT lets you express "this edge fires when
    condition C is absent" — e.g. `{"op": "and", "of": [{"statement_id":
    "stm_X"}, {"op": "not", "of": [{"statement_id": "stm_Y"}]}]}`.
    """

    to_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class IncomingLinkSpec(TypedDict):
    """An incoming typed edge from an existing statement to this statement.

    Used inside `upsert_statement` for the `incoming_links` parameter so a
    new child statement can be wired in under existing parents in a single
    call. The `to` side of the edge is implicit (the statement being
    created or updated).

    `when` is an optional condition expression; see `LinkSpec`.
    """

    from_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class EdgeSpec(TypedDict):
    """A typed edge with both endpoints addressed.

    Used by `add_links` and `remove_links`. Both endpoints must be
    statements (`stm_…`).

    Entity↔entity edges are **not** handled here — those live in their
    own vocabulary and are managed by `add_entity_links` /
    `remove_entity_links`.

    `when` is an optional condition expression; see `LinkSpec`. Identity
    on read/delete is by canonicalized hash, so the literal shape sent
    to `remove_links` doesn't have to match what was originally sent to
    `add_links` — only the canonical form must match.

    Direction note: source is the bigger/earlier/wrapping/primary side;
    target is the smaller/later/contained/dependent side. Before
    committing an edge, read it aloud as "FROM <link_type> TO" and check
    it against the link type's description. For constrained statement
    link types, provably flipped edges detected by statement kind are
    rejected; e.g. `teaches` is `procedure -> capability`, so
    `capability -> procedure` fails and should be swapped.
    """

    from_id: str
    to_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class BatchStatementSpec(TypedDict):
    """One statement in a batch upsert.

    Same shape as the parameters of single-record `upsert_statement`, with
    one extension: any `to_id` (in `links`) or `from_id`
    (in `incoming_links`) can be either an existing statement id like
    `"stm_abc..."` or the literal string `"@N"` (where N is a 0-based
    integer) to refer to the Nth statement in the same batch. This lets
    callers wire siblings together in one call without round-tripping for
    ids first.
    """

    kind: str
    text: str
    links: NotRequired[list[LinkSpec]]
    incoming_links: NotRequired[list[IncomingLinkSpec]]
    allow_phrasing_violations: NotRequired[bool]


#: Ceiling on rows a paged or ranked read returns: hits are hydrated, so an
#: unbounded `limit` can overrun a caller's context in one call.
_MAX_LIMIT = 100
ResultLimit = Annotated[int, Field(ge=1, le=_MAX_LIMIT)]


def _check_limit(limit: int) -> None:
    """Enforce `ResultLimit` for in-process callers, which skip validation."""
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}; got {limit}")


class EntityEdgeSpec(TypedDict):
    from_entity_id: str
    to_entity_id: str
    link_type: str
