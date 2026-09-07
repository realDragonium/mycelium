# Find connections between statements

`find_statement_connections` returns several routes between two statements,
or one connecting graph that also covers required statements on branches.
It includes actions, typed relationships and their conditions. It is a reader-role
MCP tool, also available as `POST /find-statement-connections` and to the internal
reasoning tools.

```json
{
  "source": "click Save",
  "target": "the changes become visible",
  "max_hops": 4,
  "max_routes": 5
}
```

Each endpoint accepts a statement ID starting with `stm_` or search text. Mixing
an ID and text is supported. IDs are exact lookups and never call the embedding
service. Text reuses `search_statements`' semantic ranking and alias boost, with
a score floor of 0.5. The tool reports up to three candidates per endpoint. It
selects the best only when its score leads the runner-up by at least 0.05;
otherwise it returns `needs_resolution` without walking the graph. These scores
are ranking values, not probabilities. Inspect the candidates and retry using
IDs when the match is ambiguous or incorrect. A missing ID never falls back to
text search. For kind or entity filters, use `search_statements` first and pass
the selected IDs.

## Include required statements

Use `required` when several statements must connect, without prescribing an
order or forcing them onto one path:

```json
{
  "source": "how the workflow runs",
  "target": "why the outcome changes",
  "required": ["configure the setting on page Z", "stm_relevant_rule"],
  "max_hops": 4,
  "max_routes": 5
}
```

Each required entry accepts text or an ID using the same resolution rules as
source and target. Up to eight entries are allowed. Repeated inputs are resolved
once; repeated statement IDs do not consume extra branches. Any missing or
ambiguous input returns `needs_resolution` with candidates before the walk runs.

With requirements, the tool searches outward from **source** and retains routes
that reach target and the required statements. Each branch is a shortest
discovered route from source, with stable edge-ID tie breaking. A page, setting,
workflow and outcome can connect on separate branches. A route that extends an
earlier branch replaces that branch's shorter prefix. Requirements are covered
only by actual traversal steps, not merely by appearing as condition context.

This mode returns one connecting graph and stops when all requirements and
target are covered. It does not enumerate alternative graphs or guarantee the
smallest possible connecting graph. `max_hops` applies from source to each
requested statement, not to the total graph size or separately between successive
requirements. All branches share the route, expansion, read and output budgets.
For example, with `max_routes=1`, two separate required branches may yield
`partial`; increase the limit to allow both.

`connected_ids` and `unconnected_ids` report coverage of the distinct requested
IDs, including source and target. The resolved source is the anchor and counts
as connected to itself. A disconnected target does not discard useful required
branches; the result is `partial`. Coverage lists are empty when any input needs
resolution. Entries in `required` retain their original order and resolution
details, but that order does not affect traversal.

Omitting `required`, passing null, or passing an empty list preserves the
two-endpoint behavior: return several alternative source-to-target routes.

## Read the result

- `source`, `target`, and `required` show each input, resolution status, selected ID, and
  candidates with statement text and scores.
- `routes` contain ordered `statement_ids` and `steps`. Each step has the
  traversal's `from_id`, `to_id`, `edge_id`, and `traversal` kind.
- `edges` contain the selected routes' deduplicated stored edges: `id`,
  `from_id`, `to_id`, `link_type`, and full `when` expression, or null.
- `statements` contain the statements on those routes plus every statement
  needed to read their edges and conditions. Condition context can be off-route.
  No unrelated neighboring edges are attached.
- `connected_ids` and `unconnected_ids` describe coverage of the requested
  statements, excluding intermediate statements and condition-only context.

Two routes can have the same statement sequence but different edge types or
conditions. Edge IDs preserve those alternatives; do not deduplicate routes
using statement IDs alone. Returned routes do not repeat a statement or reuse
an edge. Identical endpoints return one zero-hop route when there are no
additional distinct requirements.

## Direction and conditions

The default `direction="both"` explores incoming and outgoing statement links.
For example, two actions requiring the same input are connected through that
input even though one hop goes against its stored arrow. Steps distinguish
`forward` from `reverse`; stored edges always retain their original direction.

Condition participation is a separate `condition` step between a statement
referenced in an edge's `when` expression and either endpoint or another
condition statement on that edge. It is one hop. The result includes the full
edge and condition expression so an AND, OR, or NOT cannot be mistaken for a
positive, sufficient prerequisite. Participation says nothing about whether a
condition currently holds. No conditions are evaluated.

`direction="forward"` follows only stored source-to-target arrows. Conditions
and their statements remain in the result as context, but are not traversal
hops in this mode. Neither mode establishes an executable or causal sequence:
interpret each relationship using its type. Shared mentions, aliases, and
entity edges never create graph hops.

Use `link_types` to restrict which stored relationships participate:

```json
{
  "source": "stm_source",
  "target": "stm_target",
  "direction": "forward",
  "link_types": ["next", "performs", "proceeds"],
  "max_hops": 6
}
```

Omitting `link_types` includes all types; an empty list includes none. The filter
also applies to edges used for condition participation. Names refer to the
stored link types, not their aliases.

## Limits and completeness

Routes are searched breadth-first, ordered by hop count with stable edge-ID
ordering. Required mode keeps the first path to each visited statement; the
two-endpoint mode explores alternatives. Routes are not ranked by relevance. A short connection through a shared
general rule may explain less than a longer sequence of actions.

| Argument | Default | Allowed |
|---|---:|---:|
| `max_hops` | 4 | 0–8 |
| `max_routes` | 5 | 1–20 |
| `max_expansions` | 2000 | 1–10000 |

`max_expansions` bounds examined traversal steps, including rejected cycles,
and separately bounds adjacency edge records loaded during the search. Outgoing,
incoming and condition lookups each probe at most the remaining budget plus one
edge ID before merging. Cached adjacency is reused across routes. Counts are
returned as `expansions` and `edge_reads`.
These are work limits, not a wall-clock timeout or a guarantee about SQLite's
internal query cost. The walk reads one consistent database snapshot; embeddings
are resolved before that snapshot begins.

| Status | Meaning |
|---|---|
| `needs_resolution` | At least one endpoint or requirement is missing or ambiguous; no walk ran. |
| `found` | All requested statements connected. Check `truncated` for search incompleteness. |
| `partial` | Some routes were retained, but target or required statements remain unconnected. |
| `not_found_within_limits` | No route under the chosen hop limit, direction and types. |
| `incomplete` | A resource limit prevented completion and no route was returned. |

`truncated` and `stop_reasons` disclose route, expansion, adjacency-read,
condition-size or output limits. The hop limit defines the requested search
scope; it does not by itself mark the result truncated. An empty result never
proves that the statements are unrelated outside that scope.
`partial` without truncation means some requested statements were not reachable
within the hop limit and selected direction/types. With truncation, the search
may have stopped before reaching them; neither case is reported as full success.

The response has an approximately 64,000-character ceiling. Whole routes are
retained or omitted so an output limit cannot silently cut a condition tree.
Statement text is limited to 2,000 characters and marked `text_truncated`; use
`get_statements` for the full text. Edges with conditions larger than 128 tree
nodes are skipped and reported with `condition_limit`. Endpoint inputs are
limited to 2,000 characters, and at most 100 link-type filters are accepted.
If endpoint candidates and filters alone exceed the response ceiling, the tool
returns an error asking for IDs or fewer filters.
