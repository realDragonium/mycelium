"""Semantic statement search: ranked recall over the statement vector index.

One candidate ranker (`_search_statement_candidates`) serves search and route
finding. It adds an alias boost from the name index, so a query using an alias
still finds the statements that mention the entity. Writes call
`_near_duplicates` to warn about close matches, and `discover_facts` lets an
author check candidate texts before writing them.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import JsonValue

from .. import embed, statement_connections, store, survey
from ..store.connection_graph import ConnectionGraph
from ..tracing import trace_span
from .hydration import _REVERSE_EDGE_CAP, _expand_graph, _hydrate_statement_full
from .registry import tool
from .runtime import _db, _idx, _name_idx
from .specs import ResultLimit, _check_limit

logger = logging.getLogger(__name__)


def _entity_ids_for_names(name_texts: list[str]) -> set[str]:
    """Resolve a list of name texts to entity_ids. Raises on any unknown."""
    entity_ids: set[str] = set()
    for text in name_texts:
        row = store.get_name_by_text(_db(), text)
        if row is None:
            raise ValueError(f"name {text!r} does not exist")
        entity_ids.add(row["entity_id"])
    return entity_ids


#: Truncation cap for `text` snippets returned in `near_duplicates` and
#: `discover_facts.matches`. Long enough to recognise the fact, short
#: enough to keep batch responses lean. Callers wanting the full text
#: should follow up with `get_statements(ids)`.
SNIPPET_CHARS = 100


def _snippet(text: str) -> str:
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1] + "…"


def _near_duplicates(
    vec: list[float],
    *,
    exclude_id: str | None = None,
    threshold: float | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Return existing statements whose vector is at or above `threshold`
    cosine similarity to `vec`. The statement matching `exclude_id` is
    dropped (used to skip the upsert's own freshly-inserted vector).
    `text` is truncated to a snippet to keep batch responses lean.
    """
    threshold = embed.thresholds().near_duplicate if threshold is None else threshold
    # +1 to allow excluding the self-hit without dropping under k results.
    hits = _idx().search(vec, k=k + (1 if exclude_id else 0))
    out: list[dict[str, Any]] = []
    for vid, distance in hits:
        bid = store.get_statement_id_by_vector_id(_db(), vid)
        if bid is None or bid == exclude_id:
            continue
        score = 1.0 - distance
        if score < threshold:
            continue
        row = store.get_statement(_db(), bid)
        if row is None:
            continue
        out.append({"id": bid, "text": _snippet(row["text"]), "score": score})
        if len(out) >= k:
            break
    return out


def _alias_entity_boost(
    vec: list[float], name_boost: float, name_top_k: int, name_min_score: float
) -> dict[str, float]:
    """Alias-aware recall: search the name index too. Top-K names above
    `name_min_score` are resolved to their entity_ids; each entity gets
    the max-scoring name. Statements mentioning a boosted entity get
    final_score = cosine + name_boost * entity_score, lifting them
    against alias-using queries without harming canonical ones."""
    entity_boost: dict[str, float] = {}
    if name_boost > 0.0 and name_top_k > 0:
        for vid, dist in _name_idx().search(vec, k=name_top_k):
            sc = 1.0 - dist
            if sc < name_min_score:
                continue
            nid = store.get_name_id_by_vector_id(_db(), vid)
            if nid is None:
                continue
            name_row = store.get_name_by_id(_db(), nid)
            if name_row is None:
                continue
            eid = name_row["entity_id"]
            if sc > entity_boost.get(eid, 0.0):
                entity_boost[eid] = sc
    return entity_boost


def _score_candidates(
    raw_hits: list[tuple[int, float]],
    *,
    required_entity_ids: set[str],
    kind: str | None,
    entity_boost: dict[str, float],
    name_boost: float,
    min_score: float,
) -> list[tuple[str, float, float]]:
    """Fold raw vector hits into deduped, filtered, boosted candidates.
    Returns (statement_id, final_score, cosine) tuples sorted by final
    score descending. Applies the mentions-subset, kind, and min_score
    filters that only direct hits are subject to."""
    scored: list[tuple[str, float, float]] = []  # (statement_id, final, cosine)
    seen: set[str] = set()
    for vector_id, distance in raw_hits:
        cosine = 1.0 - distance
        statement_id = store.get_statement_id_by_vector_id(_db(), vector_id)
        if statement_id is None or statement_id in seen:
            continue
        mention_entity_ids = {
            m["entity_id"] for m in store.get_mentions(_db(), statement_id)
        }
        if required_entity_ids and not required_entity_ids.issubset(mention_entity_ids):
            continue
        if kind is not None:
            row = store.get_statement(_db(), statement_id)
            if row is None or row["kind"] != kind:
                continue
        boost = 0.0
        for eid in mention_entity_ids:
            if eid in entity_boost and entity_boost[eid] > boost:
                boost = entity_boost[eid]
        final = cosine + name_boost * boost
        if final < min_score:
            continue
        seen.add(statement_id)
        scored.append((statement_id, final, cosine))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _keyword_candidates(
    query: str,
    limit: int,
    kind: str | None,
    required_entity_ids: set[str],
) -> list[tuple[str, float, float]]:
    tokens = list(
        dict.fromkeys(
            token
            for token in re.findall(r"[^\W_]+", query.lower())
            if len(token) >= 3 and token not in survey.STOPWORDS
        )
    )
    if not tokens:
        return []
    rows = store.keyword_statement_candidates(
        _db(),
        tokens,
        kind=kind,
        required_entity_ids=required_entity_ids,
    )
    ranked: list[tuple[str, float, int, int]] = []
    for row in rows:
        text = str(row["text"]).lower()
        matched = sum(token in text for token in tokens)
        occurrences = sum(text.count(token) for token in tokens)
        ranked.append(
            (str(row["id"]), matched / len(tokens), occurrences, int(row["rid"]))
        )
    ranked.sort(key=lambda item: (-item[1], -item[2], item[3]))
    return [(statement_id, score, score) for statement_id, score, _n, _rid in ranked][
        :limit
    ]


def _keyword_fallback(
    query: str,
    limit: int,
    min_score: float,
    kind: str | None,
    required_entity_ids: set[str],
    error: embed.EmbeddingError,
) -> list[tuple[str, float, float]]:
    logger.warning("embedding search failed; using keyword retrieval: %s", error)
    candidates = _keyword_candidates(query, limit, kind, required_entity_ids)
    return [item for item in candidates if item[1] >= min_score]


def _search_statement_candidates_with_mode(
    query: str,
    limit: int,
    min_score: float,
    mentions: list[str] = [],
    kind: str | None = None,
    name_boost: float = 0.3,
    name_top_k: int = 5,
    name_min_score: float | None = None,
) -> tuple[list[tuple[str, float, float]], bool]:
    """Rank hits without hydrating them; return whether keyword fallback ran."""
    resolved_name_min_score = (
        embed.thresholds().name_match if name_min_score is None else name_min_score
    )
    required_entity_ids = _entity_ids_for_names(mentions) if mentions else set()
    try:
        with trace_span("embed"):
            vec = embed.embed(query)
    except embed.EmbeddingError as exc:
        return (
            _keyword_fallback(query, limit, min_score, kind, required_entity_ids, exc),
            True,
        )
    return (
        _vector_candidates(
            vec,
            limit,
            min_score,
            required_entity_ids,
            kind,
            name_boost,
            name_top_k,
            resolved_name_min_score,
        ),
        False,
    )


def _search_statement_candidates(
    query: str,
    limit: int,
    min_score: float,
    mentions: list[str] = [],
    kind: str | None = None,
    name_boost: float = 0.3,
    name_top_k: int = 5,
    name_min_score: float | None = None,
) -> list[tuple[str, float, float]]:
    """Rank vector hits, falling back to keyword candidates on provider failure."""
    return _search_statement_candidates_with_mode(
        query,
        limit,
        min_score,
        mentions,
        kind,
        name_boost,
        name_top_k,
        name_min_score,
    )[0]


def _vector_candidates(
    vec: list[float],
    limit: int,
    min_score: float,
    required_entity_ids: set[str],
    kind: str | None,
    name_boost: float,
    name_top_k: int,
    name_min_score: float,
) -> list[tuple[str, float, float]]:
    entity_boost = _alias_entity_boost(vec, name_boost, name_top_k, name_min_score)
    # Filtering and alias boosts need a wider pool before ranking.
    fetch_k = (
        max(limit * 4, 40) if entity_boost or required_entity_ids or kind else limit
    )
    with trace_span("vector_search"):
        raw_hits = _idx().search(vec, k=fetch_k)
    return _score_candidates(
        raw_hits,
        required_entity_ids=required_entity_ids,
        kind=kind,
        entity_boost=entity_boost,
        name_boost=name_boost,
        min_score=min_score,
    )[:limit]


def _decomposed_candidates(
    query: str,
    limit: int,
    min_score: float,
    mentions: list[str],
    kind: str | None,
    name_boost: float,
    name_top_k: int,
    name_min_score: float,
) -> tuple[list[tuple[str, float]], bool]:
    """Search each clause of `query` separately and rank the union: first by
    how many clauses surfaced a statement, then by its best score. Returns
    whether keyword fallback ran."""
    required_entity_ids = _entity_ids_for_names(mentions) if mentions else set()
    parts: list[tuple[str, list[float]]] = []
    try:
        with trace_span("embed"):
            for part in survey.decompose(query):
                if survey.usable(part):
                    parts.append((part, embed.embed(part)))
            parts = survey.dedup_subqueries(
                parts, threshold=embed.thresholds().subquery_dedup
            )
            if not parts:
                parts = [(query, embed.embed(query))]
    except embed.EmbeddingError as exc:
        keyword = _keyword_fallback(
            query, limit, min_score, kind, required_entity_ids, exc
        )
        return [(sid, score) for sid, score, _cosine in keyword], True
    union: dict[str, tuple[int, float]] = {}
    for _part, vec in parts:
        for sid, final, _cosine in _vector_candidates(
            vec,
            limit,
            min_score,
            required_entity_ids,
            kind,
            name_boost,
            name_top_k,
            name_min_score,
        ):
            count, best = union.get(sid, (0, float("-inf")))
            union[sid] = (count + 1, max(best, final))
    return survey.rank_statements(union), False


@tool
def search_statements(
    query: str,
    limit: ResultLimit = 10,
    min_score: float = -1.0,
    depth: int = 0,
    direction: Literal["both", "children", "parents"] = "both",
    mentions: list[str] = [],
    kind: str | None = None,
    name_boost: float = 0.3,
    name_top_k: int = 5,
    name_min_score: float | None = None,
    decompose: bool = False,
) -> list[dict[str, Any]]:
    """Vector-search statements by semantic similarity to `query`.

    Returns up to `limit` (at most 100) direct hits with score >= `min_score`,
    sorted by score descending. Useful floors depend on the embedding model;
    0.5–0.8 is typical for nomic-embed-text.

    Scoring is cosine similarity + an alias-aware boost: the query is
    also searched against the entity-name index, and statements that
    mention entities whose names score high pick up additional weight.
    This means a query phrased with an alias ("bot", "machine user")
    still surfaces statements that only contain the canonical name
    ("service account", "token") in their text. Set `name_boost=0` to
    fall back to pure cosine ranking.

    Each hit is FULLY HYDRATED — the same shape `get_statements` returns:
    `{id, kind, text, mentions, links, incoming_links, when_references}`,
    plus a `score` on direct hits. So you do NOT need a follow-up
    `get_statements` on a hit's own id just to see what points at it — only
    to follow a link to a DIFFERENT id. The reverse-edge lists
    (`incoming_links` / `when_references`) are capped per hit; an
    `incoming_links_truncated` / `when_references_truncated` count appears
    when a convergence hub has more, in which case `get_statements([id])`
    returns the complete set.

    `mentions` is an optional entity filter — a list of name texts. When
    non-empty, hits must mention every entity referenced by those names
    (AND semantics — a hit matches only if it mentions all of them, not
    any of them). Each name is resolved to an entity_id; the call raises
    ValueError if any name does not exist. Useful for "find statements
    about X specifically" without relying on the query string to surface
    the right entity.

    If `depth > 0`, also walks the link graph from each direct hit up to
    `depth` hops. `direction` controls which way: `children` follows
    outgoing links only, `parents` follows incoming links only, `both`
    (default) follows both. Expanded statements are appended after the
    direct hits and carry no `score` field — direct hits do. The mentions
    and kind filters apply only to direct hits; expansions ignore them.

    Depth pitfall: convergence hubs (statements with many `configures` or
    `governed-by` parents — e.g. an "edge conditions are evaluated" node)
    leak unrelated subgraphs into the result when expanded. If you're
    chasing a specific causal chain, prefer `depth=1` from a well-targeted
    hit and use `get_statements(ids)` to step further. Reserve `depth=2+`
    for breadth scans where noise is acceptable.

    Each hit's `mentions` is `[{name_id, name, entity_id}]` so callers can
    address the underlying name and entity directly (e.g., for `merge_entities`
    or `move_name`).

    Optional `kind` ("event" / "state" / "capability") restricts direct
    hits to that kind.

    `decompose=True` is for a question that covers several distinct things.
    The query is split on conjunctions and strong punctuation, each part is
    searched as above (up to `limit` hits each, same filters and boost), and
    the union comes back deduped: statements surfaced by more parts first,
    then by best score. The result can therefore hold more than `limit` hits.

    If embedding is unavailable, keyword matching is used, hits carry
    `retrieval: "keyword"`, and scores are the fraction of query words matched.

    Boost tunables (defaults usually fine):
      `name_boost`     — weight applied to the best matching entity-name
                         score. 0 disables alias-aware retrieval.
      `name_top_k`     — how many top names to consider from the name index.
      `name_min_score` — drop name matches below this cosine. Keeps
                         canonical queries unaffected when no name is
                         clearly relevant. The configured model supplies the
                         default (0.5 for nomic-embed-text).
    """
    _check_limit(limit)
    if decompose:
        ranked, keyword_fallback = _decomposed_candidates(
            query,
            limit,
            min_score,
            mentions,
            kind,
            name_boost,
            name_top_k,
            embed.thresholds().name_match if name_min_score is None else name_min_score,
        )
    else:
        scored, keyword_fallback = _search_statement_candidates_with_mode(
            query,
            limit,
            min_score,
            mentions,
            kind,
            name_boost,
            name_top_k,
            name_min_score,
        )
        ranked = [(sid, final) for sid, final, _cos in scored]

    direct: list[dict[str, Any]] = []
    for sid, score in ranked:
        hit = _hydrate_statement_full(sid, score=score, reverse_cap=_REVERSE_EDGE_CAP)
        if keyword_fallback:
            hit["retrieval"] = "keyword"
        direct.append(hit)
    seen = {sid for sid, _score in ranked}

    if depth <= 0:
        return direct

    expanded = _expand_graph(seen, depth, direction)
    return direct + expanded


@tool
def find_statement_connections(
    source: str,
    target: str,
    direction: Literal["both", "forward"] = "both",
    max_hops: int = 4,
    max_routes: int = 5,
    max_expansions: int = 2000,
    link_types: list[str] | None = None,
    required: list[str] | None = None,
) -> dict[str, JsonValue]:
    """Find bounded routes, optionally connecting required statements on branches.

    `required` accepts up to 8 additional IDs or search texts, in any order.
    With requirements, return one graph connecting source, target and those
    statements. Each branch follows a shortest discovered route from source,
    within max_hops; stop once all are covered. `found` means all requested
    statements connected; `partial` retains some connections. Inspect
    connected_ids, unconnected_ids and stop_reasons. Context-only statements
    do not count as connected. All branches share the same work/output limits.
    Without requirements, return several alternative source-to-target routes.

    Each endpoint is a `stm_...` ID or search text. Text uses alias-aware
    semantic search with a floor supplied by the configured embedding model
    (0.5 for nomic-embed-text). The best match is selected only if it leads
    the runner-up by at least 0.05. Otherwise status is `needs_resolution`:
    inspect the endpoint candidates and retry with IDs. Scores are ranking
    values, not probabilities. IDs never need embeddings.

    Returns matched endpoints, routes, and their merged statements and edges.
    Routes retain ordered steps; each step references an edge by `edge_id`.
    Edges retain their stored from_id, to_id, link_type and full `when` tree.
    `both` follows either arrow direction and condition participation, labeled
    separately as `forward`, `reverse`, or `condition` steps. `forward` follows
    only stored source-to-target arrows; conditions remain attached context.
    Condition participation does not imply truth, enablement or execution.
    Referenced condition statements are included, even off the route.

    Routes are found breadth-first, with stable edge-ID ordering, not ranked
    by relevance. `link_types` filters traversed edges (None means all, []
    means none). Entities and shared mentions never create graph hops.
    `found` may still be truncated. `not_found_within_limits` means no route
    under the chosen direction, types and hop limit; `incomplete` means a
    budget stopped a search that found none. Always inspect `stop_reasons`.

    Bounds: hops 0–8, routes 1–20, expansions 1–10000. The expansion budget
    also separately caps loaded adjacency rows. Output is capped near 64K
    characters; statement text is capped at 2000 with `text_truncated`.
    Conditions over 128 tree nodes are skipped with `condition_limit`.
    Fetch full text through get_statements. Nothing is written.
    """
    limits = statement_connections.Limits(
        max_hops=max_hops,
        max_routes=max_routes,
        max_expansions=max_expansions,
    )
    if direction not in ("both", "forward"):
        raise ValueError("direction must be 'both' or 'forward'")
    if required is not None and len(required) > 8:
        raise ValueError("required must contain at most 8 statements")
    if any(
        not value.strip() or len(value) > 2000
        for value in (source, target, *(required or []))
    ):
        raise ValueError("endpoints must contain 1–2000 characters")
    if link_types is not None and (
        len(link_types) > 100
        or any(not lt.strip() or len(lt) > 200 for lt in link_types)
    ):
        raise ValueError(
            "link_types must contain at most 100 nonblank names of at most 200 characters"
        )
    conn = _db()
    graph = ConnectionGraph(conn, direction, link_types)

    def candidates(query: str) -> list[statement_connections.Candidate]:
        matches: list[statement_connections.Candidate] = []
        for sid, score, _cosine in _search_statement_candidates(
            query, 3, embed.thresholds().endpoint_match
        ):
            statement = graph.statement(sid)
            if statement is not None:
                matches.append(
                    statement_connections.Candidate(
                        **statement.model_dump(),
                        score=score,
                    )
                )
        return matches

    resolved: dict[str, statement_connections.Endpoint] = {}
    for value in (source, target, *(required or [])):
        value = value.strip()
        if value not in resolved:
            resolved[value] = statement_connections.resolve_endpoint(
                value,
                graph.statement,
                candidates,
            )
    result = statement_connections.Result(
        source=resolved[source.strip()],
        target=resolved[target.strip()],
        required=[resolved[value.strip()] for value in (required or [])],
        status="needs_resolution",
        direction=direction,
        link_types=link_types,
        limits=limits,
    )
    if len(result.model_dump_json()) > statement_connections.MAX_OUTPUT_CHARS - 2048:
        raise ValueError(
            "endpoint candidates and filters exceed the response limit; "
            "use statement IDs or fewer link types"
        )
    # Embedding happens above; hold a consistent read snapshot only for the walk.
    conn.execute("SAVEPOINT find_statement_connections")
    try:
        for endpoint in result.endpoints:
            if endpoint.selected_id and graph.statement(endpoint.selected_id) is None:
                endpoint.selected_id = None
                endpoint.status = "missing"
                endpoint.candidates = []
        return (
            statement_connections.Search(graph.neighbors, graph.statement, result)
            .run()
            .model_dump(mode="json")
        )
    finally:
        conn.execute("RELEASE SAVEPOINT find_statement_connections")


@tool
def find_duplicates(
    threshold: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Audit the whole substrate for near-duplicate statement pairs.

    Walks every statement, queries the vector index for its closest
    neighbours, and returns pairs with cosine similarity at or above
    `threshold`. Sorted by score descending, paged by `offset` and `limit`. Pairs
    are reported once (not as both `(A,B)` and `(B,A)`).

    The configured embedding model supplies the default (0.92 for
    nomic-embed-text), tuned for high-confidence duplicate matches. Its
    write-time near-duplicate default is 0.85; this tool is the periodic
    backfill audit.

    Each pair: `{a_id, a_text, b_id, b_text, score}`. Use
    `merge_statements(from, into)` to consolidate, or `replace_text` /
    `add_links` if the duplication is structural rather than textual.
    """

    threshold = (
        embed.thresholds().statement_duplicate if threshold is None else threshold
    )
    seen_pairs: set[tuple[str, str]] = set()
    pairs: list[dict[str, Any]] = []

    for bid in store.all_statement_ids(_db()):
        vid = store.get_vector_id(_db(), bid)
        if vid is None:
            continue
        vec = _idx().get_vector(vid)
        if vec is None:
            # Slot is stranded — SQLite mapping points at an id the
            # hnsw file doesn't have. Skip rather than crash the audit.
            continue
        # k=20 is a balance between catching all candidates and per-call
        # cost. At MVP scales this comfortably covers any cluster of
        # near-duplicates.
        hits = _idx().search(vec, k=20)
        for other_vid, distance in hits:
            if other_vid == vid:
                continue
            score = 1.0 - distance
            if score < threshold:
                continue
            other_bid = store.get_statement_id_by_vector_id(_db(), other_vid)
            if other_bid is None:
                continue
            key = (bid, other_bid) if bid < other_bid else (other_bid, bid)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            a_row = store.get_statement(_db(), key[0])
            b_row = store.get_statement(_db(), key[1])
            if a_row is None or b_row is None:
                continue
            pairs.append(
                {
                    "a_id": key[0],
                    "a_text": a_row["text"],
                    "b_id": key[1],
                    "b_text": b_row["text"],
                    "score": score,
                }
            )

    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs[offset : offset + limit]


@tool
def discover_facts(
    texts: list[str],
    exists_threshold: float | None = None,
    near_threshold: float | None = None,
    matches_per_text: int = 5,
) -> list[dict[str, Any]]:
    """Bulk discovery for many candidate facts at once.

    Two uses, same call:
    - Pre-write: before authoring new statements, check which already
      exist under different wording.
    - Audit / coverage check: given a list of claims (e.g. extracted from
      a doc), find out which the substrate confirms, which are near-misses
      worth a closer look, and which are absent. Faster and more honest
      than running `search_statements` per claim — one call, structured
      verdicts.

    For each input text, embeds it, queries the vector index, and
    classifies the closest existing statement into one of three buckets:

    - `"exists"`: top match score >= `exists_threshold`.
      The substrate already has this fact under different wording. Don't
      write a new statement; either link to it, refine it via
      `upsert_statement(id=…)`, or merge afterwards if you wrote
      anyway.
    - `"near"`: top match score is between `near_threshold` and
      `exists_threshold`. Related facts exist; the new statement is
      likely distinct but probably should `link` to one or more of the
      matches instead of standing alone.
    - `"new"`: nothing within `near_threshold`. Safe to write fresh.

    Threshold defaults come from the configured embedding model (0.85 exists
    and 0.6 near for nomic-embed-text).

    Replaces the per-fact loop of sequential `search_statements` calls
    that the discovery phase otherwise prescribes. Pass every text you
    intend to write in one go; the response gives you a per-text
    decision plus the supporting matches.

    Each result: `{text, status, matches: [{id, text, score}]}`.
    `matches` is capped at `matches_per_text` (default 5) and includes
    every hit at or above `near_threshold`, sorted by score descending
    — so `"new"` results carry an empty `matches` list. `text` snippets
    are truncated to keep batch responses lean; follow up with
    `get_statements(ids)` for full text.

    Cheap-ish: one embed + one vector search per input text. No SQL
    writes.
    """

    if exists_threshold is None:
        exists_threshold = embed.thresholds().fact_exists
    if near_threshold is None:
        near_threshold = embed.thresholds().fact_near
    if exists_threshold < near_threshold:
        raise ValueError(
            "exists_threshold must be >= near_threshold "
            f"(got {exists_threshold} < {near_threshold})"
        )

    out: list[dict[str, Any]] = []
    for text in texts:
        vec = embed.embed(text)
        hits = _idx().search(vec, k=matches_per_text)

        matches: list[dict[str, Any]] = []
        for vid, distance in hits:
            score = 1.0 - distance
            if score < near_threshold:
                continue
            bid = store.get_statement_id_by_vector_id(_db(), vid)
            if bid is None:
                continue
            row = store.get_statement(_db(), bid)
            if row is None:
                continue
            matches.append({"id": bid, "text": _snippet(row["text"]), "score": score})

        if matches and matches[0]["score"] >= exists_threshold:
            status = "exists"
        elif matches:
            status = "near"
        else:
            status = "new"

        out.append({"text": text, "status": status, "matches": matches})

    return out
