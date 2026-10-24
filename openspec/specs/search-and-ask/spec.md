# search-and-ask Specification

## Purpose
Lets agents and people find and read knowledge: semantic and literal statement search, exact reads, pre-write discovery, entity lookup, bounded route finding between statements, graph views, and the Ask loop that answers a question from cited statements.

## Requirements

### Requirement: Semantic statement search
The system SHALL provide the reader tool `search_statements(query, limit=10, min_score=-1.0, ...)` that ranks statements by cosine similarity between the query embedding and each statement embedding, returns at most `limit` direct hits whose score is at or above `min_score`, sorted by score descending, and rejects a `limit` outside 1–100.

#### Scenario: Ranked hits above the floor
- **WHEN** a reader calls `search_statements` with `query: "invoice export format"`, `limit: 5` and `min_score: 0.6`
- **THEN** the response is a list of at most 5 statements, each carrying a `score` of at least 0.6
- **AND** the list is ordered by `score` descending

#### Scenario: Limit out of range
- **WHEN** a caller passes `limit: 0` or `limit: 101`
- **THEN** the call fails with an error naming the allowed range 1–100

### Requirement: Alias-aware search boost
The system SHALL also search the entity-name index with the query embedding, take the top `name_top_k` (default 5) names scoring at or above `name_min_score` (default: the embedding model's name-match threshold, see the `embeddings-and-indexes` capability), and add `name_boost` (default 0.3) times the best such name score of any entity a statement mentions to that statement's score.

#### Scenario: Query uses an alias
- **WHEN** the entity "single sign-on" has the alias "SSO" and a statement mentions that entity without containing "SSO"
- **AND** a reader searches for "SSO login"
- **THEN** that statement's score includes the boost from the matching alias and it can outrank statements that only share wording

#### Scenario: Boost disabled
- **WHEN** a reader passes `name_boost: 0`
- **THEN** every hit's `score` equals its cosine similarity to the query

### Requirement: Search hits are fully hydrated
Each statement returned by `search_statements` SHALL have the same shape as a `get_statements` record: `id`, `kind`, `text`, `created_at`, `updated_at`, `created_by`, `updated_by`, `mentions` (`[{name_id, name, entity_id}]`), `links`, `incoming_links` and `when_references`, with `incoming_links` and `when_references` each capped at 25 entries per hit.

#### Scenario: Convergence hub in the results
- **WHEN** a hit has 40 incoming links
- **THEN** its `incoming_links` holds 25 entries and `incoming_links_truncated` is 40

#### Scenario: Ordinary hit
- **WHEN** a hit has 3 incoming links
- **THEN** all 3 appear in `incoming_links` and no `incoming_links_truncated` field is present

### Requirement: Search mention and kind filters
`search_statements` SHALL accept `mentions`, a list of name texts, and keep only direct hits that mention every entity those names resolve to (AND semantics), and SHALL accept `kind` to keep only direct hits of that statement kind. A name in `mentions` that does not exist MUST fail the call with an error naming it.

#### Scenario: Two required concepts
- **WHEN** a reader searches with `mentions: ["Workspace", "Invoice"]`
- **THEN** every direct hit mentions both the workspace entity and the invoice entity, through any of their names

#### Scenario: Unknown mention name
- **WHEN** `mentions` contains a name that no entity carries
- **THEN** the call fails with an error saying the name does not exist

### Requirement: Search graph expansion
When `depth` is greater than 0, `search_statements` SHALL append, after the direct hits, the statements reached by walking statement links up to `depth` hops, following outgoing links for `direction: "children"`, incoming links for `"parents"` and both for `"both"` (the default). Expanded statements MUST carry no `score`, MUST appear at most once, and ignore the `mentions`, `kind` and `min_score` filters.

#### Scenario: One hop of children
- **WHEN** a reader searches with `depth: 1` and `direction: "children"`
- **THEN** the result lists the scored direct hits first, followed by each statement those hits link to, without a `score`

### Requirement: Decomposed search
With `decompose: true`, `search_statements` SHALL split the query into clauses on conjunctions and strong punctuation, search each usable clause with the same filters and boost (up to `limit` hits per clause), and return the deduplicated union ranked first by how many clauses surfaced a statement and then by its best score, so the result MAY hold more than `limit` hits.

#### Scenario: Multi-part question
- **WHEN** a reader searches "how are invoices exported and who can enable SSO" with `decompose: true`
- **THEN** statements about invoice export and statements about enabling SSO both appear
- **AND** a statement surfaced by both clauses ranks ahead of statements surfaced by one

### Requirement: Keyword fallback for statement search
When the embedding provider cannot embed the query, `search_statements` (with or without `decompose`) SHALL rank statements by keyword matching instead of failing, scoring each statement by the fraction of query words of at least 3 characters, excluding stopwords, that its text contains case-insensitively, and marking every hit `retrieval: "keyword"`. The `mentions`, `kind` and `min_score` filters MUST still apply.

#### Scenario: Provider down during search
- **WHEN** the embedding provider is unavailable and a reader searches "invoice export schedule"
- **THEN** a statement containing all three words is returned with `score: 1.0` and `retrieval: "keyword"`
- **AND** a statement containing two of them scores about 0.67 and ranks below it

#### Scenario: Equal keyword scores
- **WHEN** two statements match the same fraction of words
- **THEN** the one with more total occurrences ranks first, and remaining ties follow insertion order

#### Scenario: No usable words
- **WHEN** the provider is down and every query word is shorter than 3 characters or a stopword
- **THEN** the search returns no hits

#### Scenario: Normal search carries no retrieval marker
- **WHEN** the embedding provider is available
- **THEN** search hits carry no `retrieval` field

### Requirement: Fetch statements by id
The system SHALL provide the reader tool `get_statements(ids)` that returns `{statements, missing}`: one fully hydrated record per id that exists, in input order and repeated for repeated ids, with `incoming_links` and `when_references` uncapped, and `missing` listing the ids that no statement carries. A missing id MUST NOT fail the call.

#### Scenario: Batch with an unknown id
- **WHEN** a reader calls `get_statements` with two existing ids and one unknown id
- **THEN** `statements` holds the two existing records in input order
- **AND** `missing` is the unknown id

#### Scenario: Empty request
- **WHEN** `ids` is empty
- **THEN** both `statements` and `missing` are empty

### Requirement: Literal statement grep
The system SHALL provide the reader tool `grep_statements(query, case_sensitive=False, entity_id, name, kind, match_aliased_mentions=True, limit=50, offset=0)` that matches `query` as a literal substring of statement text, with no wildcard, glob or regex meaning, and returns `{total, statements: [{id, kind, text, matched_via}], missing}` in insertion order. An empty `query` MUST be rejected.

#### Scenario: Wildcard characters are literal
- **WHEN** a reader greps for "100%"
- **THEN** only statements containing the literal text "100%" match

#### Scenario: Empty query
- **WHEN** a caller greps for ""
- **THEN** the call fails with an error

### Requirement: Grep matches through aliases
With `match_aliased_mentions` on (the default) and no entity filter, `grep_statements` SHALL also return statements that mention an entity any of whose names contains the query, reporting `matched_via` as `"text"`, `"mention"` or `"both"`; with `match_aliased_mentions: false` or an `entity_id` or `name` filter, it MUST match statement text only.

#### Scenario: Alias match without the word in the text
- **WHEN** the export entity carries the alias "CSV dump" and a statement mentions that entity without the word "dump"
- **AND** a reader greps for "dump"
- **THEN** that statement is returned with `matched_via: "mention"`

#### Scenario: Explicit entity filter
- **WHEN** a reader greps with `name: "Invoice"`
- **THEN** only statements whose text contains the query and that mention the invoice entity are returned, all with `matched_via: "text"`

### Requirement: Unresolved read filters match nothing
`grep_statements` and `list_statements` SHALL accept at most one of `entity_id` and `name`, rejecting a call that passes both, and SHALL treat an `entity_id` or `name` that does not resolve as a filter matching nothing, returning `total: 0`, no statements and the unresolved value in `missing`.

#### Scenario: Misspelt concept name
- **WHEN** a reader calls `list_statements` with `name: "Invioce"` and no such name exists
- **THEN** the response is `total: 0`, an empty `statements` list and `missing: ["Invioce"]`

#### Scenario: Both filters
- **WHEN** a caller passes both `entity_id` and `name`
- **THEN** the call fails with an error

### Requirement: List statements
The system SHALL provide the reader tool `list_statements(limit=50, offset=0, entity_id, name, kind)` that pages statements in insertion order, optionally restricted to those mentioning one entity and to one kind, and returns `{total, statements: [{id, kind, text}], missing}` where `total` counts all matches and `limit` MUST be 1–100. A `name` filter resolves to its entity, so every alias gives the same set.

#### Scenario: Paging by alias
- **WHEN** "sign-in" is an alias of the login entity and a reader lists with `name: "sign-in"`, `limit: 10`, `offset: 10`
- **THEN** the response holds the second page of statements mentioning the login entity and `total` counts all of them

#### Scenario: Listing a draft
- **WHEN** a caller passes a `draft_id`
- **THEN** the draft's queued statement operations are listed instead of the knowledge base (see the `drafts-and-review` capability)

### Requirement: Bulk fact discovery
The system SHALL provide the reader tool `discover_facts(texts, exists_threshold, near_threshold, matches_per_text=5)` that returns, per input text in order, `{text, status, matches: [{id, text, score}]}`, where `matches` holds up to `matches_per_text` nearest statements scoring at or above `near_threshold`, sorted by score descending, with `text` cut to 100 characters. The thresholds default to the embedding model's values; nothing is written.

#### Scenario: Pre-write check
- **WHEN** an author checks "Admins can export invoices as CSV" and the knowledge base holds "An admin can download invoices as a CSV file" scoring above `exists_threshold`
- **THEN** that text's status is `"exists"` and its matches include that statement

#### Scenario: Related but distinct
- **WHEN** the best match scores between `near_threshold` and `exists_threshold`
- **THEN** the status is `"near"`

#### Scenario: Nothing similar
- **WHEN** no statement scores at or above `near_threshold` for a text
- **THEN** its status is `"new"` and `matches` is empty

#### Scenario: Inverted thresholds
- **WHEN** a caller passes `exists_threshold: 0.5` and `near_threshold: 0.7`
- **THEN** the call fails with an error

#### Scenario: Provider unavailable
- **WHEN** the embedding provider cannot embed the texts
- **THEN** `discover_facts` fails with an error rather than guessing by keywords

### Requirement: Semantic entity search
The system SHALL provide the reader tool `search_entities(query, k=10, min_score)` that searches the entity-name index, keeps names scoring at or above `min_score` (default: the embedding model's entity-search threshold), reports each entity once under its best-scoring name, and returns `{entities: [{id, name, matched_name, score, description}]}` sorted by score descending and capped at `k`. An empty `query` MUST be rejected.

#### Scenario: Conceptual entity lookup
- **WHEN** a reader searches entities for "billing document"
- **THEN** the invoice entity can be returned with `name` set to its preferred name and `matched_name` to whichever of its names scored best

### Requirement: Entity search keyword fallback
When the embedding provider cannot embed the query, `search_entities` SHALL return entities with a name containing the query case-insensitively, scoring an exactly equal name 1.0 and any other match 0.5, still applying `min_score` and `k`, and marking each result `retrieval: "keyword"`.

#### Scenario: Provider down
- **WHEN** the embedding provider is unavailable and a reader searches entities for "invoice"
- **THEN** an entity named exactly "Invoice" is returned with `score: 1.0` and `retrieval: "keyword"`
- **AND** an entity named "Invoice archive" is returned with `score: 0.5`

### Requirement: Entity prefix listing
The system SHALL provide the reader tool `list_entities(prefix="", limit=50, offset=0)` that pages entities sorted by their alphabetically first name and, when `prefix` is non-empty, keeps entities any of whose names, aliases included, starts with `prefix` case-insensitively, returning `{total, entities: [{id, name, description}]}` with `limit` 1–100.

#### Scenario: Prefix matches an alias
- **WHEN** the workspace entity carries the alias "Tenant" and a reader lists entities with `prefix: "ten"`
- **THEN** the workspace entity is returned

### Requirement: Combined context retrieval
The system SHALL provide the reader tool `retrieve_context(query, names, entity_limit=3, statement_limit=6, linked_limit=8)`, served over HTTP and to the server's loops but not advertised over MCP, that resolves 1–3 names by case-insensitive name prefix, or semantic name search when no prefix matches, reads each selected entity, searches statements mentioning it with `query`, and fetches one hop of linked statements, condition references included.

#### Scenario: Alias resolved by prefix
- **WHEN** a reader calls `retrieve_context` with `query: "who can export"` and `names: ["CSV dump"]`, an alias of the export entity
- **THEN** `resolutions` records the name with `method: "name_prefix"` and the export entity as a candidate
- **AND** `statements` holds statements mentioning the export entity relevant to the query plus their directly linked statements

#### Scenario: Response fields
- **WHEN** a call completes
- **THEN** the response contains `resolutions`, `entities`, `statements`, `direct_ids`, `missing`, `limits`, `truncated` and `reads`

### Requirement: Combined retrieval bounds
`retrieve_context` SHALL reject a blank query, a blank name, or a limit outside `entity_limit` 1–3, `statement_limit` 1–8 and `linked_limit` 1–12 before doing any read; the limits MUST apply across all names together; and every `links`, `incoming_links`, `when_references`, `names` and `mentions` list MUST be cut to 20 entries with a `<list>_truncated` total that keeps any larger earlier total.

#### Scenario: Out-of-range limit
- **WHEN** a caller passes `statement_limit: 9`
- **THEN** the call fails before any read is made

#### Scenario: Large reverse-edge list
- **WHEN** a returned statement has 30 incoming links
- **THEN** its `incoming_links` holds 20 entries and `incoming_links_truncated` is 30

### Requirement: Connection endpoint resolution
The system SHALL provide the reader tool `find_statement_connections(source, target, direction="both", max_hops=4, max_routes=5, max_expansions=2000, link_types, required)` whose endpoints are each a `stm_` id, looked up exactly without embedding and never falling back to text search, or search text, resolved by alias-aware semantic search with the embedding model's endpoint floor to at most 3 candidates.

#### Scenario: Endpoints by id
- **WHEN** both endpoints are existing `stm_` ids
- **THEN** both endpoints have status `id` and the embedding provider is not called

#### Scenario: Unknown id
- **WHEN** `source` is a `stm_` id that does not exist
- **THEN** the source endpoint has status `missing` and the result status is `needs_resolution`

### Requirement: Ambiguous endpoints stop the search
A text endpoint SHALL be selected only when its best candidate's score leads the runner-up by at least 0.05; when any endpoint is ambiguous or missing, the result status MUST be `needs_resolution`, no walk is run, and each endpoint reports `input`, `status` (`id`, `matched`, `ambiguous` or `missing`), `selected_id` and `candidates` with statement text and scores.

#### Scenario: Ambiguous text endpoint
- **WHEN** `source` is "export" and the two best candidates score 0.71 and 0.69
- **THEN** status is `needs_resolution`, the source endpoint is `ambiguous` with both candidates and no `selected_id`
- **AND** `routes` is empty

### Requirement: Connection routes
With both endpoints resolved and no requirements, `find_statement_connections` SHALL return up to `max_routes` alternative source-to-target routes found breadth-first within `max_hops`, ordered by hop count with stable edge-id ordering rather than relevance. Each route lists ordered `statement_ids` and `steps` of `{from_id, to_id, edge_id, traversal}`, and MUST NOT repeat a statement or reuse an edge.

#### Scenario: Two routes over the same statements
- **WHEN** two edges of different link types connect the same pair of statements
- **THEN** two routes with the same `statement_ids` but different `edge_id`s can be returned

#### Scenario: Same statement twice
- **WHEN** `source` and `target` are the same id and no requirements are given
- **THEN** one route with that single statement and no steps is returned

### Requirement: Connection result contents
A `find_statement_connections` result SHALL include the selected routes' deduplicated `edges`, each with `id`, `from_id`, `to_id`, `link_type` and its full `when` expression or null, and `statements` holding every statement on those routes plus every statement their edges' conditions reference, even off-route, with no unrelated neighbouring edges. Nothing is written.

#### Scenario: Conditional edge on a route
- **WHEN** a route uses an edge whose `when` is "workspace has SSO enabled AND NOT trial workspace"
- **THEN** `edges` carries the full AND/NOT tree and `statements` includes both condition statements

### Requirement: Connection direction and conditions
With `direction: "both"`, `find_statement_connections` SHALL traverse stored links either way, labelling steps `forward` or `reverse`, and SHALL treat participation in an edge's `when` condition as a one-hop `condition` step; with `direction: "forward"` it MUST follow only stored source-to-target arrows, keeping condition statements as context only. Entities and shared mentions MUST never create hops, and no condition is evaluated.

#### Scenario: Shared input connects two actions
- **WHEN** two actions each link to the same input statement and `direction` is `"both"`
- **THEN** a route between the actions passes through the input, with one `forward` and one `reverse` step

#### Scenario: Forward only
- **WHEN** the same request uses `direction: "forward"`
- **THEN** no route goes against a stored arrow

#### Scenario: Unknown direction
- **WHEN** a caller passes `direction: "backward"`
- **THEN** the call fails with an error

### Requirement: Connection link-type filter
`find_statement_connections` SHALL restrict traversed edges, condition participation included, to the stored link type names in `link_types`: omitted or null means all types and `[]` means none. More than 100 names, or a blank name or one longer than 200 characters, MUST be rejected.

#### Scenario: Only sequencing links
- **WHEN** a caller passes `link_types: ["next", "triggers"]`
- **THEN** every step in every route uses an edge of type `next` or `triggers`

### Requirement: Connections through required statements
`find_statement_connections` SHALL accept `required`, up to 8 additional ids or search texts resolved like the endpoints, and then return one connecting graph whose branches are each a shortest discovered route from `source` within `max_hops`, stopping once target and all requirements are covered. More than 8 entries MUST be rejected; omitting `required`, or passing null or `[]`, keeps the two-endpoint behaviour.

#### Scenario: Requirements on separate branches
- **WHEN** the source reaches the target and two required statements along different branches within the hop limit and route budget
- **THEN** status is `found` and the routes cover target and both requirements

#### Scenario: Too many requirements
- **WHEN** `required` holds 9 entries
- **THEN** the call fails with an error

### Requirement: Connection coverage reporting
`find_statement_connections` SHALL report `connected_ids` and `unconnected_ids` over the distinct requested statements (source, target and requirements), counting the source as connected and counting only statements reached by traversal steps, never condition context; both lists MUST be empty when any input needs resolution.

#### Scenario: Target unreachable but a requirement reached
- **WHEN** the source reaches a required statement but not the target within the hop limit
- **THEN** status is `partial`, the required statement is in `connected_ids` and the target is in `unconnected_ids`

### Requirement: Connection work limits and statuses
`find_statement_connections` SHALL accept `max_hops` 0–8, `max_routes` 1–20 and `max_expansions` 1–10000, which bounds both examined traversal steps and loaded adjacency rows (reported as `expansions` and `edge_reads`), and SHALL report `status` as `found`, `partial`, `not_found_within_limits` or `incomplete`, with `truncated` and `stop_reasons` from `max_routes`, `max_expansions`, `max_edge_reads`, `output_limit` and `condition_limit`.

#### Scenario: No route in scope
- **WHEN** no route exists within `max_hops: 2` and no budget was hit
- **THEN** status is `not_found_within_limits` and `truncated` is false

#### Scenario: Budget stops an empty search
- **WHEN** the expansion budget runs out before any route is found
- **THEN** status is `incomplete` and `stop_reasons` contains `max_expansions`

#### Scenario: Hop limit out of range
- **WHEN** a caller passes `max_hops: 9`
- **THEN** the call fails with a validation error

### Requirement: Connection output bounds
`find_statement_connections` SHALL keep its response near 64,000 characters by keeping or omitting whole routes, cut statement text at 2,000 characters marked `text_truncated: true`, and skip edges whose condition exceeds 128 tree nodes, reporting `condition_limit`. Endpoint inputs MUST be 1–2,000 characters, and when endpoint candidates and filters alone exceed the ceiling the call MUST fail asking for ids or fewer filters.

#### Scenario: Long statement on a route
- **WHEN** a statement on a route has 3,000 characters of text
- **THEN** its returned text is 2,000 characters and `text_truncated` is true

### Requirement: Graph concept list
The system SHALL serve `GET /api/graph/concepts`, returning `{concepts: [{id, name, statements, links}], statements}` for every entity the caller may see, where `statements` per concept counts the statements mentioning it and `links` its entity links, ordered by statement count, then link count, both descending, then name.

#### Scenario: Most mentioned first
- **WHEN** the workspace entity is mentioned by 2 statements and the invoice entity by 1
- **THEN** workspace is listed before invoice

### Requirement: Graph neighbourhood
The system SHALL serve `GET /api/graph/neighbourhood?focus=<id>`, returning the `/api/data` shape restricted to the focus: for an entity, the statements mentioning it, the entities linked to it and the entities those statements mention; for a statement, the statements it links to or from and the entities they mention. Links MUST be kept only when both ends are kept, and an unknown focus MUST return 404.

#### Scenario: Neighbourhood of a statement
- **WHEN** a person opens the graph on a statement that links to one statement and is linked from another
- **THEN** the neighbourhood holds those three statements, the entities they mention and the links among them

#### Scenario: Unknown focus
- **WHEN** `focus` names no entity or statement
- **THEN** the response is 404

### Requirement: Ask tool and compact result
The system SHALL provide the tool `ask(question, depth="standard", verbose=False)`, the only tool the `asker` role reaches, that answers from the knowledge base and by default returns `{outcome: "answered", answer, confidence}`, with `confidence` one of `high`, `medium` or `low`, or `{outcome: "needs_clarification", question}`.

#### Scenario: Default answer
- **WHEN** an asker calls `ask` with "Who can export invoices?"
- **THEN** the response has exactly `outcome`, `answer` and `confidence`

### Requirement: Ask verbose result
With `verbose: true`, `ask` SHALL return the full result: for an answer, also `interpretation` (`as_asked`, `resolved_to`, `reframed`, `reframe_reason`), `gaps`, `provenance` and `trace`; for a clarification, also `candidates` (`[{interpretation, would_pull}]`), `known_so_far` and `trace`. Verbosity MUST change only the response, not retrieval or reasoning.

#### Scenario: Verbose answer
- **WHEN** an asker calls `ask` with `verbose: true`
- **THEN** the response also holds `interpretation`, `gaps`, `provenance` and `trace`

### Requirement: Ask never raises for retrieval or closure reasons
Apart from cancellation, the Ask loop SHALL always finish with an `answered` or `needs_clarification` result, even when reads fail, the model errors, the model never calls a terminal tool, or a budget runs out, by forcing one low-confidence answer turn or, failing that, returning a synthetic low-confidence answer whose provenance lists only statements actually supplied to the model.

#### Scenario: Model never submits
- **WHEN** the model answers with text and no tool call on two consecutive turns
- **THEN** the run force-finalizes and returns `outcome: "answered"` with `confidence: "low"` and a gap naming the forced finalization

#### Scenario: Forced turn also fails
- **WHEN** the forced answer turn fails as well
- **THEN** the answer states that the knowledge base did not yield enough to resolve the question with confidence, with `confidence: "low"`

### Requirement: Ask recon
Every Ask run SHALL begin with one decomposed `search_statements` call for the literal question with `limit` equal to the saved Ask `recon_k` (default 8), counted toward the operation cap; the compacted recon hits are the model's first evidence, and a recon failure MUST be recorded and treated as no hits.

#### Scenario: Recon counts as an operation
- **WHEN** an Ask run completes
- **THEN** its trace's first tool call is the recon `search_statements` with `decompose: true`, and it is counted in `op_count`

### Requirement: Ask read tools
The Ask model SHALL be offered the reader-role tools that describe the knowledge domain, plus the terminal tools `submit_answer` and `request_clarification`, and MUST NOT be offered writes, `ask` itself, `report_knowledge_gap`, or tools describing instance state such as drafts, documentation runs, documents, prompts, destinations or media.

#### Scenario: Offered set
- **WHEN** an Ask run starts
- **THEN** the model is offered `discover_facts`, `find_duplicates`, `find_entity_duplicates`, `find_statement_connections`, `get_entity`, `get_mention_candidates`, `get_statements`, `grep_statements`, `list_entities`, `list_entity_link_types`, `list_link_type_aliases`, `list_link_types`, `list_statement_kinds`, `list_statements`, `retrieve_context`, `search_entities` and `search_statements`

### Requirement: Ask read failures are reported
A read the Ask model requests that fails SHALL be retried once and, if it fails again, returned to the model as an error result and recorded as failed in the trace, never presented as an empty success.

#### Scenario: Read fails twice
- **WHEN** `get_statements` raises on both attempts during an Ask run
- **THEN** the model receives an error result for that call and the trace records the call as failed

### Requirement: Ask evidence floor in standard depth
At `depth: "standard"` the system SHALL accept `submit_answer` only after a successful recon, at least one successful targeted read after recon (`search_statements`, `get_statements`, `grep_statements`, `get_entity`, `retrieve_context` or `find_statement_connections`), and at least one adjacency re-search; a premature submit MUST be refused up to 3 times, after which the run force-finalizes with `floor_stuck`.

#### Scenario: Premature submit
- **WHEN** the model calls `submit_answer` right after recon at standard depth
- **THEN** the submit is refused and the model is told which retrievals are still missing

### Requirement: Ask adjacency re-search
An adjacency re-search SHALL be a `search_statements` call whose `adjacency_sources` name refs of statements supplied by a targeted read completed in an earlier turn and whose query differs from the literal question. Sources supplied only by recon, by a read in the same turn, or not supplied at all MUST be refused with an error listing the refs that qualify.

#### Scenario: Recon-only source rejected
- **WHEN** the model's search names as `adjacency_sources` a ref that only recon supplied
- **THEN** the search is refused with an error naming the refs that qualify, and it does not count as adjacency research

### Requirement: Ask quick depth
At `depth: "quick"` the system SHALL drop the evidence floor, accepting the first well-formed `submit_answer`, and cap the run at the lower of the saved limits and 8 operations, 25 seconds wall clock and 20 seconds per model request.

#### Scenario: Quick answer after one read
- **WHEN** an asker calls `ask` with `depth: "quick"` and the model submits after recon and one read
- **THEN** the answer is accepted without an adjacency re-search

### Requirement: Ask budgets
Each Ask run SHALL stop reading and force-finalize when it reaches the saved Ask operation cap (default 25), wall-clock budget (default 90 seconds) or the cap plus 12 model turns, with each model request bounded by the saved request timeout (default 75 seconds); reads requested after exhaustion MUST get a "Retrieval budget exhausted" error. The limits are saved settings (see the `ai-providers` capability).

#### Scenario: Operation cap reached
- **WHEN** a run has used 25 operations
- **THEN** no further read runs and the run returns a low-confidence answer whose trace has `forced_finalize: "op_cap"`

### Requirement: Ask clarification
The system SHALL return `needs_clarification` only when the model calls `request_clarification` with a non-empty question and at least two candidate interpretations, each with a non-empty `interpretation` and `would_pull`; an under-specified clarification MUST be sent back once and, if still under-specified, the run MUST force-finalize to an answer instead.

#### Scenario: One candidate only
- **WHEN** the model requests clarification twice with a single candidate
- **THEN** the run returns a low-confidence `answered` result, never a clarification with fewer than two candidates

### Requirement: Ask terminal turns stand alone
A terminal tool call (`submit_answer` or `request_clarification`) made in the same turn as any other tool call SHALL be refused, after the turn's reads have run, and the model told to finish in a separate turn after reading the results.

#### Scenario: Read and submit together
- **WHEN** the model calls `get_statements` and `submit_answer` in one turn
- **THEN** the read runs, the submit is refused, and the run continues

### Requirement: Ask provenance references
Each complete statement record supplied to the Ask model SHALL receive a run-local ref (`s1`, `s2`, …), and only those refs, or full ids of supplied statements, MUST be accepted as provenance or adjacency sources. An unknown ref, an entity id or an unread link target MUST be rejected; an invalid or malformed submit is sent back once before the run degrades to a low-confidence answer.

#### Scenario: Unknown provenance ref
- **WHEN** the model cites `s9` and no `s9` was supplied
- **THEN** the submit is refused and the model is asked to correct it

### Requirement: Ask provenance output
The returned `provenance` SHALL hold full statement ids in citation order, and refs left in the answer prose MUST be rewritten as bracketed positions in `provenance`, dropping refs to supplied statements the answer does not cite and leaving text that names no supplied ref untouched.

#### Scenario: Refs in the prose
- **WHEN** the model submits "Admins can export invoices [s3]." with provenance `["s1", "s3"]`
- **THEN** the returned answer reads "Admins can export invoices [2]." and `provenance` holds the two full statement ids

### Requirement: Ask context budget
Each tool result given to the Ask model SHALL be bounded to 20,000 characters by omitting whole entries and reporting `omitted_items`, never cutting a statement's text or a condition tree, and omitted records MUST NOT receive refs.

#### Scenario: Oversized search result
- **WHEN** a search returns more hydrated statements than fit in 20,000 characters
- **THEN** the model receives the leading whole statements and an `omitted_items` count, and the omitted statements cannot be cited

### Requirement: Ask confidence rules
The system SHALL adjust a submitted answer's confidence in code: when any supplied context was omitted or truncated it adds a gap saying so and lowers `high` to `medium`; an answer citing no statement becomes `low` with the gap "No statement evidence was cited."; a forced finalization becomes `low` with a gap naming the reason.

#### Scenario: Truncated evidence
- **WHEN** a read returned more records than fit and the model submits with `confidence: "high"`
- **THEN** the result has `confidence: "medium"` and a gap saying some evidence was omitted

### Requirement: Ask over HTTP as JSON
`POST /ask` with a JSON body `{question, depth, verbose}` and no `Accept: text/event-stream` SHALL respond normally, with its real HTTP status, when the run finishes or fails within 5 seconds; a slower run MUST respond 200 with whitespace sent every 15 seconds followed by the JSON result, and a later failure MUST end the body with `{"detail": "..."}`.

#### Scenario: Slow run
- **WHEN** an Ask run takes 40 seconds
- **THEN** the client receives status 200, leading whitespace, and then the JSON result

#### Scenario: Late failure
- **WHEN** a run fails after 10 seconds
- **THEN** the status is 200 and the body ends with a `detail` message, never a partial success

### Requirement: Ask server-sent events
`POST /ask` with `Accept: text/event-stream` SHALL stream frames of `event: <type>` and one JSON `data:` payload, with types `progress` (`phase`: `retrieval`, `evidence_check` or `composition`; `message`), `answer_delta` (`text`), `answer_reset` (`message`), `complete` (`result`), `error` (`message`) and `cancelled` (`message`), plus `: keepalive` comments every 15 seconds. Only `complete` commits an answer; there is no replay or resume.

#### Scenario: Streamed answer
- **WHEN** a browser asks with `Accept: text/event-stream`
- **THEN** it receives `progress` frames, then zero or more `answer_delta` frames, then one `complete` frame
- **AND** the `complete` result has the same verbosity-shaped content the JSON response would carry

#### Scenario: Failure mid-stream
- **WHEN** the run fails after streaming began
- **THEN** the stream ends with an `error` event and no `complete` event

### Requirement: Ask provisional answer text
Ask SHALL stream as `answer_delta` only the `answer` string of the model's `submit_answer` input, never thinking or other narrative, and at standard depth nothing until the evidence floor is satisfied. It MUST emit `answer_reset` whenever streamed text is not accepted, but not when refs are rewritten into provenance numbers.

#### Scenario: Invalid provenance after streaming
- **WHEN** answer text has streamed and the submit is then refused for an unknown ref
- **THEN** an `answer_reset` event is sent before the model retries

#### Scenario: Clarification
- **WHEN** a run ends in clarification
- **THEN** no `answer_delta` text remains committed and the `complete` result is the clarification

### Requirement: Ask cancellation
Ask SHALL stop a run cooperatively when an HTTP client disconnects, an MCP request is cancelled, or a connected stream consumer leaves events undelivered for 30 seconds (the event queue holds 64 events); once cancellation is observed no model call or forced finalization may start, and a still-connected SSE client receives `cancelled`. An in-flight blocking call MAY finish or time out first.

#### Scenario: Browser navigates away
- **WHEN** the client disconnects during retrieval
- **THEN** the run stops before its next read or model turn and no answer is finalized

### Requirement: Ask over MCP
Over MCP, `ask` SHALL return one completed structured result, in the same compact or verbose shape as HTTP, without progress or answer-delta events.

#### Scenario: MCP client asks
- **WHEN** an MCP client calls `ask`
- **THEN** it receives a single result with `outcome`, `answer` and `confidence`

### Requirement: Ask trace log
Each Ask run, including one that ends cancelled or in error, SHALL append one JSON trace line to the file named by `MYCELIUM_ASK_TRACE_LOG` or, when unset, `ask_trace.jsonl` in the data directory.

#### Scenario: Default location
- **WHEN** `MYCELIUM_ASK_TRACE_LOG` is unset and a run answers
- **THEN** a line with outcome `answered` is appended to `ask_trace.jsonl` in the data directory

### Requirement: Ask trace contents
An Ask trace record SHALL have `version: 2` and hold the question, model, provider, prompts, `outcome`, `op_count`, `op_cap`, `latency_ms`, `model_turns`, `phase_ms`, `model_turn_ms`, `tool_calls`, `floor`, `evidence_checks`, `combined_reads`, `evidence_refs`, `supplied_context_chars`, `tokens`, `cost_usd`, `forced_finalize`, `degraded`, `notes` and `stream_timing_ms`.

#### Scenario: Cancelled run timing
- **WHEN** a run is cancelled after answer text streamed
- **THEN** its trace has outcome `cancelled`, a `stream_timing_ms.first_answer_text_ms` and no `completion_ms`

### Requirement: Ask through the caller's own agent
While Ask is set to External agent, the system SHALL run no model for `ask`: it MUST leave `ask` out of every caller's `tools/list` and refuse a call over MCP or `POST /ask` with a message telling the caller to research with the read tools as the `mycelium-research` skill describes. The web app SHALL hide Ask and keep Find.

#### Scenario: Ask called while external
- **WHEN** Ask is set to External agent and a reader posts a question to `/ask`
- **THEN** the request is refused naming the `mycelium-research` skill and no model is called

#### Scenario: Tool list while external
- **WHEN** Ask is set to External agent and a reader lists tools over MCP
- **THEN** `ask` is not listed and the read tools are
