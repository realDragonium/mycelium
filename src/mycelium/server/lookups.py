"""Statement reads that do not rank: by id, by kind or mention, by literal text.

These are the exact reads that complement semantic search. `grep_statements`
finds identifiers and quoted strings that embeddings miss, and
`retrieve_context` bundles name lookup, entity reads, search and fetch into
one call to fit the Ask loop's turn budget.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from pydantic import Field, JsonValue

from .. import store
from .entities import get_entity, list_entities, search_entities
from .hydration import _hydrate_statement_full
from .registry import tool
from .runtime import _db
from .search import search_statements
from .specs import ResultLimit, _check_limit


@tool
def get_statements(ids: list[str]) -> dict[str, Any]:
    """Fetch one or more statements by id, each hydrated with mentions,
    both link directions, and reverse `when` references.

    `ids` is a list — pass `[id]` for a single lookup, or batch many ids
    in one call when walking a graph. Order is preserved. Duplicates in
    `ids` produce duplicate entries in the result.

    Returns `{statements: [{id, kind, text, mentions, links,
    incoming_links, when_references}, ...]}`. `mentions` is `[{name_id,
    name, entity_id}]`. `links` is the outgoing edges this statement
    owns; `incoming_links` is `[{from_id, link_type}]` listing every
    statement that points at this one. Endpoint values (`to_id` on `links`,
    `from_id` on `incoming_links`) are statement ids (`stm_…`).

    `when_references` is `[{from_id, to_id, link_type, when}]` —
    every statement↔statement edge whose `when` condition mentions THIS
    statement as a leaf. Use it to answer "what does this state gate?"
    Condition states often
    have no outgoing links of their own (intentionally — see authoring
    §9); `when_references` is how you trace forward from them anyway.

    The natural follow-up to a `search_statements` hit (or any opaque
    ids you got from links — `links[].to_id`,
    `incoming_links[].from_id`, or a `when` reference).
    **Batch the hop**: if a hit has multiple outgoing links you want to
    follow, hydrate them all in one `get_statements` call rather than
    looping. To trace a causal chain, alternate: search once, then
    `get_statements` each frontier. This is cleaner than
    `search_statements(depth=2+)`, which mixes direct hits with a flat
    blob of expanded nodes and pulls in noise through convergence hubs.

    `link_type` strings on `links` / `incoming_links` (e.g. `configures`,
    `varies-by`, `establishes`, `proceeds`) have specific semantics — call
    `list_link_types()` for the glossary if unsure. Links may also carry
    a `when` condition (a tree of `{op: "and"/"or"/"not", of: [...]}`
    and `{statement_id: ...}` leaves) that gates when the edge fires;
    `list_link_types()` also documents that grammar.

    Also returns `missing` — the subset of `ids` that no statement carries,
    always present and empty when everything resolved. An id that does not
    exist is an answer, not a failure: you get every statement that did
    resolve, so a single bad id in a batch does not cost you the rest, and
    `missing` tells you exactly which ones to stop asking for. An empty `ids`
    yields empty everything.
    """
    missing = [i for i in ids if store.get_statement(_db(), i) is None]
    ids = [i for i in ids if i not in set(missing)]
    # Uncapped reverse edges: get_statements is an explicit, targeted fetch, so
    # it returns the complete neighborhood (search/survey cap it — see
    # `_hydrate_statement_full`).
    statements = [_hydrate_statement_full(sid, score=None) for sid in ids]
    return {"statements": statements, "missing": missing}


@tool(role="reader")
def retrieve_context(
    query: Annotated[str, Field(min_length=1)],
    names: Annotated[list[str], Field(min_length=1, max_length=3)],
    entity_limit: Annotated[int, Field(ge=1, le=3)] = 3,
    statement_limit: Annotated[int, Field(ge=1, le=8)] = 6,
    linked_limit: Annotated[int, Field(ge=1, le=12)] = 8,
) -> dict[str, JsonValue]:
    """Resolve 1–3 names/aliases and retrieve relevant entity and statement context
    in one bounded operation. Prefer this to separate name lookup, entity fetch,
    mention-filtered search and linked-statement fetch turns. Prefix candidates
    (semantic name search if absent) are candidates, not confirmed referents.

    Searches each selected entity using query, then follows ONE hop including
    outgoing, incoming and condition-state references. Statements are deduplicated
    by ID; separate conditional edges and full AND/OR/NOT trees are preserved.
    Read stored direction from from_id/to_id, never infer it from traversal.
    Limits: 1–3 entities, 1–8 direct statements, 1–12 linked statements, 20 items
    per edge/name/mention list. Truncation and missing targets are explicit;
    get_statements/get_entity can fetch omitted context. This is targeted
    retrieval, NOT concept-seeded adjacency research. Re-search gathered concepts
    separately when required. `reads` records the primitives actually performed.
    """
    from ..ai.types import JSON_OBJECT
    from ..ask.retrieval import retrieve_context as retrieve

    readers: dict[str, Callable[..., object]] = {
        "list_entities": list_entities,
        "search_entities": search_entities,
        "get_entity": get_entity,
        "search_statements": search_statements,
        "get_statements": get_statements,
    }

    def read(name: str, arguments: dict[str, JsonValue]) -> JsonValue:
        from pydantic import TypeAdapter

        from ..ask.events import current_stream

        stream = current_stream.get()
        if stream:
            stream.check()
        return TypeAdapter(JsonValue).validate_python(readers[name](**arguments))

    return JSON_OBJECT.validate_python(
        retrieve(
            read,
            query=query,
            names=names,
            entity_limit=entity_limit,
            statement_limit=statement_limit,
            linked_limit=linked_limit,
        )
    )


@tool
def list_statements(
    limit: ResultLimit = 50,
    offset: int = 0,
    entity_id: str | None = None,
    name: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Page through statements in insertion order.

    Without filters, returns every statement. With `entity_id` or `name`,
    restricts to statements that mention that entity. A `name` is
    resolved to whichever entity it points at, so all aliases of the
    same entity collapse into one filter — passing `"Login"` and
    passing `"sign-in"` (an alias of the same entity) yield the same
    set. Pass at most one of `entity_id` / `name`; both raises
    ValueError, because there is no answer to a request that filters
    two ways at once.

    A `name` or `entity_id` that does not exist is a filter matching
    nothing, not a failure: you get `total: 0` and the unresolved value
    in `missing`, so you can fix the spelling rather than retry.

    `kind` ("event" / "state" / "capability") restricts to statements
    of that kind. Combines with the entity filter under AND.

    Returns `{total, statements: [{id, kind, text}], missing}` — text only,
    with no mentions or links to keep the response light. To inspect a
    single statement's full structure use `get_statements([id])`. `limit` is
    at most 100; page with `offset`.
    """
    _check_limit(limit)
    if entity_id is not None and name is not None:
        raise ValueError("pass at most one of entity_id / name, not both")
    if name is not None:
        row = store.get_name_by_text(_db(), name)
        if row is None:
            return {"total": 0, "statements": [], "missing": [name]}
        entity_id = row["entity_id"]
    if entity_id is not None and store.get_entity_by_id(_db(), entity_id) is None:
        return {"total": 0, "statements": [], "missing": [entity_id]}
    rows = store.list_statements(
        _db(), limit=limit, offset=offset, entity_id=entity_id, kind=kind
    )
    return {
        "missing": [],
        "total": store.count_statements(_db(), entity_id=entity_id, kind=kind),
        "statements": [
            {"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows
        ],
    }


@tool
def grep_statements(
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    match_aliased_mentions: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Literal substring search over statement `text`, alias-aware.

    Complements `search_statements` (vector / semantic) with deterministic
    case-insensitive substring matching. Reach for grep when you need
    exact phrases, identifiers, quoted strings, or specific tokens that
    semantic search may not surface reliably.

    By default also returns statements that mention an entity whose
    *name* contains the query as a literal substring — so grepping
    `"bot"` surfaces statements about the Service Account entity
    (which carries `bot` as an alias) even when the statement text
    says only `"service account"`. This mirrors the alias awareness in
    `search_statements`. Each result carries `matched_via`:

      `"text"`    — statement text contains the query.
      `"mention"` — statement mentions an entity whose name contains
                    the query; statement text does not.
      `"both"`    — both of the above.

    Set `match_aliased_mentions=False` to get only text-matches (the
    pre-alias-awareness behavior).

    `query` is matched literally — `%` and `_` are escaped, no glob or
    regex syntax is honored. Pass `case_sensitive=True` for an
    exact-case match. Empty `query` raises ValueError.

    Optional `entity_id` / `name` (mutually exclusive) restricts results
    to statements that mention that entity. When set, alias-mention
    expansion is suppressed — the explicit entity filter already
    specifies the mention scope. A `name` or `entity_id` that does not
    exist is a filter matching nothing, not a failure: you get
    `total: 0` and the unresolved value in `missing`.

    Returns `{total, statements: [{id, kind, text, matched_via}], missing}`.
    `missing` is always present and empty when the filters resolved. Use
    `get_statements(ids)` for full mentions and links.
    """
    if not query:
        raise ValueError("query must be a non-empty string")
    if entity_id is not None and name is not None:
        raise ValueError("pass at most one of entity_id / name, not both")
    if name is not None:
        row = store.get_name_by_text(_db(), name)
        if row is None:
            return {"total": 0, "statements": [], "missing": [name]}
        entity_id = row["entity_id"]
    if entity_id is not None and store.get_entity_by_id(_db(), entity_id) is None:
        return {"total": 0, "statements": [], "missing": [entity_id]}

    # Text-match path — the historical behavior. When entity_id is set,
    # this is the only path; explicit filters suppress alias expansion.
    text_rows = store.grep_statements(
        _db(),
        query,
        case_sensitive=case_sensitive,
        entity_id=entity_id,
        kind=kind,
        limit=10_000 if (match_aliased_mentions and entity_id is None) else limit,
        offset=0 if (match_aliased_mentions and entity_id is None) else offset,
    )

    if not match_aliased_mentions or entity_id is not None:
        total = store.count_grep_statements(
            _db(),
            query,
            case_sensitive=case_sensitive,
            entity_id=entity_id,
            kind=kind,
        )
        return {
            "missing": [],
            "total": total,
            "statements": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "text": r["text"],
                    "matched_via": "text",
                }
                for r in text_rows
            ],
        }

    mention_rows = store.grep_statements_via_mentions(
        _db(), query, case_sensitive=case_sensitive, kind=kind
    )
    mention_ids = {r["id"]: r for r in mention_rows}

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in text_rows:
        sid = r["id"]
        seen.add(sid)
        matched_via = "both" if sid in mention_ids else "text"
        combined.append(
            {
                "id": sid,
                "kind": r["kind"],
                "text": r["text"],
                "matched_via": matched_via,
                "_rid": r["rid"],
            }
        )
    for r in mention_rows:
        sid = r["id"]
        if sid in seen:
            continue
        seen.add(sid)
        combined.append(
            {
                "id": sid,
                "kind": r["kind"],
                "text": r["text"],
                "matched_via": "mention",
                "_rid": r["rid"],
            }
        )

    combined.sort(key=lambda x: x["_rid"])
    total = len(combined)
    sliced = combined[offset : offset + limit]
    return {
        "missing": [],
        "total": total,
        "statements": [
            {
                "id": s["id"],
                "kind": s["kind"],
                "text": s["text"],
                "matched_via": s["matched_via"],
            }
            for s in sliced
        ],
    }
