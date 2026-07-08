# Mycelium — Feature Reference

A single source document describing every current feature and behaviour of
the Mycelium substrate, intended as input for an extraction pass that will
populate Mycelium's own knowledge base. Written as prose so an extraction
agent can read each fact in context.

## Project posture

Mycelium is an AI-native knowledge base substrate. It is designed to be
written by AI, read by AI, and interfaced with by humans through AI rather
than directly. Storage is not human-readable in the SQL sense, and that is
intentional — the substrate is optimised for AI retrieval, not for human
browsing.

The MVP is built deliberately naive: correctness over speed, single-writer,
no concurrent-write safety, no production-grade guarantees. This is
acceptable because Mycelium is internal infrastructure during the MVP
phase. If it proves the thesis the substrate gets rebuilt with real
engineering; until then, naive wins on iteration speed and on letting the
data model evolve without fighting an engine.

The substrate skips every feature not explicitly requested. Constraint
vocabulary is open: there is no enumerated link type catalogue, no entity
type hierarchy, and no cycle prevention. The substrate trusts the writer
to use types coherently and adds new vocabulary as the data forces it.

## Data model

The substrate stores three record kinds (entities, names, statements)
and three link kinds (statement↔statement, entity↔entity,
entity↔statement). That is the whole substrate.

An **entity** is a record holding an opaque id and a description. Entities
are the nouns of the domain — features, concepts, capabilities, surfaces.
Entities do not carry a name field directly; their identity-as-text lives
in the names table.

A **name** is a record holding an opaque id, a text string, and a foreign
key to an entity. Each entity is reachable through one or more names; the
text column is globally unique so no two entities can share an alias.
Names are exact-match-only in v1 — they are not embedded.

A **statement** is a record holding an opaque id, a `kind` string, and a
chunk of text. The statement is the unit that carries meaning. A statement
can mention any number of entities and link to any number of other
statements with typed edges.

`kind` is a deliberate first-class discriminator on the *shape of claim*
the text makes. The starting vocabulary has three leaves:

- `event` — something happening (present-tense action verbs).
- `state` — a condition holding (verbs like *"is", "has", "remains"*).
- `capability` — a modal claim (*"can", "may", "is able to"*).

The substrate enforces only that `kind` is non-null. The vocabulary is
open — new kinds (`policy`, `requirement`, anything else) are valid the
moment one statement uses them. The substrate does not enforce kind-edge
compatibility (e.g., that `triggers` only joins events) — trust the
writer.

A **statement_mentions** row links a statement to a *name*, not directly to
an entity. This indirection preserves provenance: when a statement is
authored, the writer chose a specific name to refer to an entity, and that
choice is recorded so that future merges or splits do not lose the original
phrasing. The mention's effective entity is the entity that name currently
points at.

A **statement_link** is a directed edge from one statement to another with
a string label called the link_type. The link_type vocabulary is open;
common types include `contains`, `triggers`, `enables`, `requires`,
`varies-by`, `restricts`, `replaces`, and `configures`. Cycles are
allowed, multi-parent links are allowed, and the substrate does not
enforce any tree shape.

An **entity_link** is a directed edge from one entity to another with
a string label called the link_type. Use case: structural relationships
between long-lived entities — a parent corporation `contains` its
subsidiaries, a product is a `kind-of` something more abstract, two
providers `replace` each other, etc. The link_type vocabulary is open
(any string is valid) and lives in a separate namespace from statement_link
types — the same word can mean different things between domains. Self-loops
are rejected; otherwise the substrate enforces no shape.

Entity links are distinct from statement links because the domain is
different: entities are the long-lived hubs that statements *mention*,
while statements are the atomic facts that get embedded and searched.
Entity links don't appear in vector search — to find statements that
talk about a relationship, search statements that mention both entities.

A statement_link may carry an optional `when` — an **expression tree**
that reifies the *condition* under which the edge holds. A leaf is
`{"statement_id": "stm_…"}`; internal nodes are
`{"op": "and" | "or", "of": [<child>, …]}` and may nest arbitrarily.
This lets the substrate record statements like "A — triggers (when C) → B"
or "A — triggers (when C and (D or E)) → B" without burying the
condition inside the source or target statement's text. Each leaf is
itself a statement, so it can be searched, mentioned, and linked like
any other fact.

The substrate canonicalizes `when` trees on write — flattening nested
same-op nodes, deduping children, sorting by hash — and stores a
deterministic hash (`when_hash`) on the link row. The literal sentinel
`"NONE"` stands in for "no condition." Edges with the same
`(from, to, link_type)` but different canonical `when` values are
*distinct* edges; the unique key is `(from, to, link_type, when_hash)`.
The tree itself lives in the `when_nodes` table, one row per node,
cascading away with the link.

Propositions that hold *about* a statement or entity — permissions,
invariants, properties, compliance facts — are not a separate
primitive. They are statements like any other (`kind='rule'`,
`kind='property'`, …), connected to the statements and entities they
govern via ordinary typed links. (An earlier annotation subsystem
covered this ground; it was deprecated and removed. Legacy databases
may still carry its inert tables.)

There is no root statement, no canonical hierarchy, no global ordering.
Any statement is a valid entry point into the graph.

## Persistence

The substrate writes to two files inside `MYCELIUM_DATA_DIR` (default
`./.mycelium/`): `mycelium.db` is a SQLite database holding all entity,
name, statement, mention, and link records. `mycelium.vec` is an hnswlib
binary holding the vector index of statement embeddings.

The schema migration runs on every connect via `CREATE TABLE IF NOT EXISTS`
statements, so opening an existing data directory leaves its contents
intact. There are no migration scripts beyond the initial schema; if the
schema changes incompatibly, the supported upgrade path is to wipe the
data directory and re-ingest from the source payloads.

Foreign keys are declared in the schema as `REFERENCES` clauses and are
enforced via `PRAGMA foreign_keys = ON` set on every connection. This
catches dangling references at write time — a statement_link pointing at
a non-existent statement, a name pointing at a non-existent entity, an
entity deleted while names still attach to it — without restricting
the substrate's open `link_type` vocabulary or its single-writer
posture. The substrate still trusts the writer on what categories of
records exist and what they mean; it just doesn't allow lying about
references.

## Vector index

The vector index is the only non-naive component of the substrate.
Mycelium uses hnswlib in cosine space at 768 dimensions, configured with
`ef_construction=200`, `M=16`, and `ef_search=50`. Initial capacity is
10,000 elements; on overflow the index resizes to twice its current
capacity.

The index supports replace-after-delete: each element is created with
`allow_replace_deleted=True` so that an upsert with an existing id can
mark the old vector deleted and re-insert at the same numeric label. This
is how `upsert_statement` keeps a statement's vector in sync with edits to
its text without leaking dead embeddings.

Each statement is mapped to a numeric `vector_id` via the
`statement_vector_ids` table; the mapping is allocated on first insert by
taking `MAX(vector_id) + 1` and is permanent for the statement's lifetime.

The index is loaded into memory on server start, mutated in place during
writes, and saved to disk after every write. There is no incremental
persistence; each save rewrites the full file.

## Embedding

Embeddings come from a local Ollama instance. The default endpoint is
`http://localhost:11434` and the default model is `nomic-embed-text`,
which produces 768-dimensional vectors. Both can be overridden via the
`OLLAMA_URL` and `EMBED_MODEL` environment variables, but if you swap to
a model with a different output dimension you must also update the
`DIM` constant in `vector.py` — the two must match.

Only statement text is embedded. Names are stored as exact-match strings
without embeddings, and entity descriptions are not embedded either. Name
embeddings are an explicit deferred feature; descriptions follow because
v1 routes all retrieval through statements anyway.

## Tool surface

Mycelium exposes twenty-four tools through a registry that backs both the
MCP transport and the FastAPI HTTP transport. Adding a tool is a single
`@tool` decorator on a Python function in `server.py`; the decorator
appends the function to a registry that the HTTP module iterates to
auto-generate REST endpoints, while also registering it with the MCP
server.

The tool registry is the canonical surface. Anything not registered as a
tool — for example the HTTP-only browser-UI endpoints described below —
is intentionally unavailable to MCP consumers.

### search_statements

`search_statements(query, limit=10, min_score=-1.0, depth=0, direction="both", mentions=[], kind=None)`
embeds the query string, queries the hnswlib index for the nearest
statements by cosine distance, and returns up to `limit` direct hits whose
similarity score is at least `min_score`. The optional `kind` argument
restricts direct hits to that shape of claim (`event` / `state` /
`capability` or any open kind in use); expanded neighbors come back
regardless of kind. Cosine scores are in `[-1, 1]`;
the default `-1.0` keeps every hit, while practical floors are usually
`0.5` to `0.8`.

When `depth` is greater than zero the search performs a breadth-first
walk from each direct hit up to `depth` hops along statement_links. The
`direction` argument controls which way the walk goes: `"children"`
follows outgoing links only, `"parents"` follows incoming links only, and
`"both"` (the default) follows both. Expanded statements are appended to
the response after the direct hits and carry no `score` field; direct
hits keep theirs.

An optional `mentions` parameter takes a list of name texts. When
non-empty, hits are restricted to statements that mention every entity
referenced by those names (AND semantics — a hit must mention all of
them, not any). Each name is resolved to an entity_id; the call raises
ValueError if any name does not exist. The mentions filter applies only
to direct hits, not to statements reached via `depth > 0` expansion.

Each hit's `mentions` field is a list of `{name_id, name, entity_id}`
objects so that a caller can address the underlying name and entity
directly without a follow-up lookup.

### upsert_entity

`upsert_entity(name, description)` looks up the name text in the names
table. If a name with that text exists, the entity's description is
updated and the existing entity's id is returned. Otherwise a new entity
is created with the given description and a new name pointing at it is
created in the same call.

### upsert_statement

`upsert_statement(kind, text, mentions, links, id?, incoming_links?)`
is the main write path for statements. `kind` is required on every
call (`event` / `state` / `capability` from the starting vocabulary,
or any open kind). Without `id` it always creates a brand-new statement
with a fresh UUID; there is no text-based deduplication, so calling it
twice with the same text produces two statements. To update an existing statement the caller must pass its
`id`, captured from a previous call's return value or from a
`search_statements` hit.

When `id` is given, the substrate replaces the statement at that id
wholesale. The new text is re-embedded via Ollama, the vector is replaced
in hnswlib at the same numeric label, and the `mentions` and outgoing
`links` lists are written wholesale rather than appended. Adding a single
mention or outgoing link therefore requires passing the full updated list.

If `id` is provided but does not match an existing statement the call
raises a `ValueError`, surfaced as HTTP 400 in FastAPI and as a tool
error in MCP. This strict statement prevents typos from silently creating
a statement with a forged id.

The `links` parameter is the OUTGOING typed edges from this statement:
each item is `{to_id, link_type, when?}` and the statement being created
or updated is the implicit `from`. The optional `incoming_links`
parameter is the INCOMING typed edges from existing sources: each item
is `{from_id, link_type, when?}` and this statement is the implicit
`to`. `incoming_links` lets a writer
wire a new child statement under existing parents in a single call
instead of creating it first and then calling `add_links`. The optional
`when` on either side reifies a condition as a third statement;
see "Conditions on edges" above. All three id fields validate that
referenced statements exist before any mutation; an unknown id raises
before anything is written, so a typo cannot half-apply.

The two sides have asymmetric semantics on update. Outgoing `links` is
wholesale-replaced because it represents the set this statement owns.
`incoming_links` is idempotent-insert only and never deletes, because
incoming edges live on other statements and shouldn't be removed by an
update that targets this one.

For each `mentions` text the substrate looks up the name; if no name
with that text exists, a fresh entity and a name pointing at it are
auto-created. The specific name used is recorded against the statement so
future merge or split operations preserve the original phrasing. Pass
`strict_mentions=True` to error on unknown names instead of
auto-creating — useful for authoring agents that expect every mention
to resolve to an existing entity and want typos surfaced.

### get_statements

`get_statements(ids)` is the direct lookup primitive: pass a list of
`statement_id`s and get back their full records without going through
vector search. The signature is plural by design — callers that have
several ids in hand (multiple `links`/`incoming_links` from one hit, a
frontier of `when` leaves) should batch them in a single call rather
than loop. A single lookup is just `get_statements([id])`.

Returns `{statements: [{id, kind, text, mentions, links,
incoming_links, when_references}, ...]}` in the same order
as the input ids, where `mentions` is `[{name_id, name, entity_id}]`,
`links` is the outgoing edges this statement owns, and `incoming_links`
is `[{from_id, link_type}]` listing every node that points at this one
(statement *or* entity — the substrate treats them uniformly on
hydration). Raises ValueError if `ids` is empty or if any id is unknown (no
partial results). Used by callers that already have ids in hand (from a
search hit's links field, an entity mention chain, etc.) and want the
full hydrated records.

### get_entity

`get_entity(id)` returns one entity hydrated with its names and every
kind of link it participates in: `{id, description, names: [{id, text}],
links, incoming_links, statement_links, incoming_statement_links}`.
`links` / `incoming_links` are the entity↔entity edges (separate
vocabulary, see `list_entity_link_types`). `statement_links` /
`incoming_statement_links` are mixed entity↔statement edges with the
same `{to_id|from_id, link_type, when?}` shape that `add_links`
produces. Raises ValueError on unknown id. To find statements that
mention an entity by name (rather than via a direct edge), use
`search_statements` with the `mentions` filter.

### list_entities and list_statements

`list_entities(prefix="", limit=50, offset=0)` pages through entities
sorted by their alphabetically-first attached name. Optional
case-insensitive `prefix` filter on that name. Returns `{total,
entities: [{id, name, description}]}` so callers can drive pagination.
The `name` field is the entity's primary alias; an entity with no names
falls back to its id.

`list_statements(limit=50, offset=0, entity_id?, name?, kind?)` pages
through statements in insertion order, returning `{total, statements:
[{id, kind, text}]}` — text only, no mentions or links. Without filters
it scans the entire corpus; with `entity_id` or `name` (pass at most one)
it restricts to statements that mention that entity. The optional `kind`
argument narrows further to one shape of claim and combines with the
entity filter under AND. A `name` is resolved
to whichever entity it points at, so all aliases of that entity
collapse into one filter — passing the canonical name and passing an
alias return the same set. The query joins `statements` to
`statement_mentions` and `names` and uses DISTINCT so a statement
mentioning multiple aliases of the same entity appears once. Unknown
name or unknown entity_id raises ValueError. For full statement
structure use `get_statements(ids)`.

### upsert_name

`upsert_name(text, entity_id)` attaches an alias to an existing entity.
The call is idempotent if the alias already points at the same entity —
the existing `name_id` is returned without changes. If the alias is
already taken by a different entity the call raises a `ValueError`,
surfaced as HTTP 400 with a hint to use `move_name` or `merge_entities`
to resolve the conflict. If the entity does not exist the call also
fails.

### merge_entities

`merge_entities(from_entity_id, into_entity_id)` reassigns every name
attached to the source entity onto the target entity in a single SQL
update, then deletes the source entity. Because statement mentions are
keyed on `name_id` rather than `entity_id`, mentions follow the names
automatically — every statement that previously mentioned a name of the
source now reports the target's `entity_id` while preserving the
original name text.

The call is a no-op when source and target are the same id. It returns
the count of names that were moved.

### move_name

`move_name(name_id, to_entity_id)` reassigns one name to a different
entity. Combined with `upsert_entity` to create a fresh target, this
gives the caller a clean split: the new entity is created, the alias is
moved, and statement mentions of the moved alias now report the new
entity's id while names left behind on the source entity are untouched.

### merge_statements

`merge_statements(from_id, into_id)` consolidates two statements into
one when the writer discovers they describe the same fact under
different wordings. Mentions are unioned onto the target, deduped on
`name_id`. Outgoing links are unioned and deduped on
`(to_id, link_type, when)`. Incoming links — every
other statement that pointed at the source — are rewritten to point at
the target, with the same dedup. Any edge elsewhere in the graph whose
`when` was the source is rewritten to the target before the
source is deleted, so the FK never blocks the merge. Self-loops created
by the merge are silently dropped: an existing `from → into` edge does
not become `into → into`.

The source's vector is marked deleted in the hnswlib index so it stops
surfacing in `search_statements`, and its record plus its
`statement_vector_ids` row are deleted. The target's text is unchanged
— call `upsert_statement(id=into, text=…)` afterwards if the surviving
wording should be synthesised.

Use `merge_statements` when the source's meaning lives on through the
target — duplicates, parallel drafts, "this was wrong, replaced by X."
For statements that should simply cease to exist (feature removed, fact
obsolete, no replacement), see `delete_statement` below.

The call returns counts of rows actually moved (excluding duplicates
and self-loops). It is a no-op when source and target are the same
id; it raises ValueError if either id does not exist.

### delete_statement

`delete_statement(id)` permanently removes a statement whose meaning has
no replacement — the feature it described was deleted, the claim is
obsolete, the flow was scrapped. Use `merge_statements` instead when
the source duplicates or restates another statement; merging preserves
the relationships through the target. Deletion drops them.

The cascade is bounded so deletion can't leave dangling references.
Mentions of this statement are removed. Incoming links (every edge
pointing at this statement) are removed — they no longer have a target
and aren't meaningful in isolation. Outgoing links are removed. Any
edge anywhere in the graph that referenced this statement as its
`when` is removed too: once the condition is gone, the
conditional relationship can't hold. (If the condition should live on
under a different identity, `merge_statements` first to rewrite the
references onto the target, then delete; or simply merge, which
already removes the source.) The vector slot is marked deleted in
hnswlib and the freed numeric `vector_id` is reused on the next
insert.

The call returns the cascade counts: `{deleted, mentions_removed,
incoming_links_removed, outgoing_links_removed,
when_references_removed}`. It is permanent — no undo path. Raises
ValueError on unknown id.

### add_links

`add_links(links)` accepts a list of `{from_id, to_id, link_type,
when?}` items and inserts each as an edge. Endpoints may be statement
ids (`stm_…`) or entity ids (`ent_…`) in any combination — except
entity↔entity, which has its own vocabulary and lives behind
`add_entity_links`. Statement↔statement edges land in `statement_links`;
any edge touching an entity lands in `entity_statement_links`.
Externally the caller sees a single uniform link API; the routing is
internal storage.

The operation is bulk-by-default — passing a single edge is just a
one-element list — and idempotent: pre-existing rows are silently
skipped via `INSERT OR IGNORE`, so the returned `inserted` count can be
smaller than the input length. The same `(from, to, type)` with vs
without a `when` are *distinct* edges and both can coexist;
canonicalization collapses equivalent when-trees to one row.

Before mutating, the call validates that every referenced id (every
endpoint, plus every `statement_id` leaf inside any `when` tree) exists
in the substrate. If any is unknown the call raises `ValueError` and
inserts nothing, so a typo cannot half-apply a bulk insert. `when`
leaves are always statement ids — an entity has no notion of
"holding" — and the grammar is identical across both link kinds.

No embedding work is performed — this is the cheap path for adding
relationships between nodes that already exist. By contrast,
`upsert_statement` with an `id` re-embeds the statement text on every
call, so `add_links` is the right tool when only the link structure is
changing.

### remove_links

`remove_links(links)` accepts the same `{from_id, to_id, link_type,
when?}` shape and deletes each matching row. Match is exact on `when` — omitting the field
removes only the unconditional edge, leaving any same-typed conditional
edges in place. Missing edges are a no-op rather than an error, which
makes the call idempotent — calling it twice with the same input is
fine. The returned `removed` count reflects rows actually deleted. The
call does not validate that the referenced statements exist; deleting an
edge that references a non-existent statement simply removes nothing.

### list_link_types

`list_link_types()` returns the distinct `link_type` values currently
materialised on at least one `statement_links` row, sorted
alphabetically. The result is a snapshot of what is IN USE, not the
substrate's allowed vocabulary — the vocabulary is open, any string is
a valid `link_type`, and new ones appear in the result as soon as a
statement_link uses them. To learn what specific types mean or which
types are conceptually available, search for statements that describe
`link_type` instead.

### add_entity_links and remove_entity_links

`add_entity_links(links)` and `remove_entity_links(links)` manage
directed entity↔entity edges. Each item is `{from_entity_id,
to_entity_id, link_type}`. Use case: structural relationships between
long-lived entities — parent/subsidiary corporations, kind-of
hierarchies, partner-of, replaces, etc. — that don't fit cleanly as
either an alias (`upsert_name`) or a statement link.

Inserts are idempotent (`INSERT OR IGNORE` against the `(from, to,
link_type)` PK). Self-loops (`from == to`) are rejected up front.
Every referenced entity id is validated before any mutation; if any
is unknown the call raises ValueError and inserts nothing. Removal
matches the triple exactly and is a no-op for missing edges.

Entity links cascade with `merge_entities`: when one entity is merged
into another, every entity_link referencing the source (as either
endpoint) is rewritten to reference the target before the source is
deleted, deduping against existing edges and dropping any self-loops
the merge would create. Without that rewrite, FK enforcement would
block the source's deletion.

### list_entity_link_types

`list_entity_link_types()` returns the distinct `link_type` values
currently materialised on at least one `entity_links` row, sorted
alphabetically. Statement link types and entity link types live in
separate namespaces (different tables) — the same word can mean
different things between domains. Use this to discover entity-link
conventions and `list_link_types()` for statement-link conventions.

### discover_facts

`discover_facts(texts, exists_threshold=0.85, near_threshold=0.6,
matches_per_text=5)` is a bulk pre-write classifier: for each
candidate fact text, it embeds the text once, queries the vector
index, and returns one of three statuses based on the top match:

- `"exists"` — top match score is at least `exists_threshold`. The
  substrate already has this fact under different wording. Don't write
  a duplicate; link to the existing record or refine it via
  `upsert_statement(id=…)`.
- `"near"` — top match score is between `near_threshold` and
  `exists_threshold`. Related facts exist; the new statement is likely
  distinct but probably wants to `link` to one of the matches.
- `"new"` — nothing within `near_threshold`. Safe to write fresh.

Each result carries the supporting matches inline: `{text, status,
matches: [{id, text, score}]}`. `matches` is sorted by score
descending and capped at `matches_per_text`; `"new"` results carry an
empty list. The `text` field on each match is truncated to a snippet
(default 100 characters) to keep batch responses lean — follow up
with `get_statements(ids)` for full text and structure.

This compresses the per-fact discovery loop the authoring skill
prescribes: instead of N sequential `search_statements` calls, callers
pass every text they intend to write in one shot and receive a
per-text decision. No SQL writes; the call is read-only.

The `near_duplicates` field on `upsert_statement` and `upsert_statements`
uses the same snippet truncation for the same reason.

### grep_statements

`grep_statements(query, case_sensitive=False, entity_id?, name?, kind?,
limit=50, offset=0)` is a literal substring search tool — the
deterministic counterpart to vector search. It accepts the same `kind`
filter as `list_statements` and `search_statements`.

When semantic search returns a fuzzy ranked list, grep returns every
record whose `text` contains the query as a literal substring, in
insertion order. Reach for grep when you need exact phrases,
identifiers (a feature flag name, a service name), quoted strings, or
specific tokens that semantic similarity might bury under broader
matches. Reach for `search_statements` when you want concept-level
recall.

Implementation note: substring matching uses SQLite's `instr()` rather
than `LIKE`. SQLite's default `LIKE` is case-insensitive for ASCII
regardless of `COLLATE NOCASE`, which makes a `case_sensitive=True`
flag meaningless under `LIKE`. `instr()` is binary by default, so
case folding via `lower()` on both sides cleanly toggles between
modes — and glob/regex characters in the query (`%`, `_`, `*`, `?`)
match literally without escape gymnastics. Empty `query` raises
ValueError to avoid degenerating into a slow `list_*` scan.

Filters mirror the corresponding `list_*` tools: `entity_id` / `name`
(mutually exclusive) and `kind`. The response shape also matches
`list_statements`, so a consumer can swap in either lookup without
restructuring its result handling.

Performance: linear scan of the relevant text column. At MVP scales
(low thousands of records) it's sub-10ms. The natural upgrade path,
when grep starts dominating the bench, is SQLite FTS5 — a virtual
table that gives word-level prefix queries with proper indexing.
Not worth the complexity for v1.

## Phrasing validation

Every write that produces or replaces statement text — `upsert_statement`,
`upsert_statements` (per item), and `replace_text` — runs the candidate
text through `phrasing.check(text, kind=…)` before any mutation. The
validator dispatches by the statement's `kind`. A common catalog runs
for every kind, then a per-kind catalog adds the structural rules that
are inappropriate for that kind.

Common (every kind):

- **compound** — semicolons, `and` joining two VERB heads, *"and then"*,
  *"and also"*, *", then"*. Splits an event into two; should be two
  statements.
- **precondition_in_text** — subordinating conjunctions (`when`,
  `before`, `after`, `while`, `until`, `if`, `unless`, `because`,
  `since`, `though`) anywhere in the text. The condition belongs on the
  link as a `when` expression, not in the statement text.
- **universal_claim** — `every`, `all`, `each`, `any`, plus pronoun
  forms (`everyone`, `nobody`, `none`, `everybody`). Describes a
  population, not one instance — usually wants a linked rule
  statement. The
  determiner `No` is allowed (legitimate atomic-event text uses it:
  *"no flow is specified"*, *"no email is provided"*).
- **hedge** — `usually`, `often`, `mostly`, `typically`, `sometimes`,
  `generally`, `occasionally`, `frequently`, `rarely`, `in most cases`.
- **hidden_event_state** — *"is set to"*, *"are set to"*, *"becomes"*,
  *"transitions to"*, *"gets marked as"*. These conceal an event +
  state pair into one statement; should be two statements (one
  `event`, one `state`) connected by a link.

Per-kind:

- **event** (and any open kind): rejects rule-shaped (`must`, `should`,
  `shall`, `ought`, prohibition adverbs `never`/`always`, periphrastic
  modals `needs to`/`has to`, copula-rule constructs `is required to` /
  `is allowed to`), sequencing (`will` — names a follow-up that belongs
  as its own statement), and property-shaped (*"is a / is an"*, *"has a
  / has an"*, structural verbs `consists of` / `belongs to` / `comprises`).
- **state**: rejects rule modals, sequencing, and `capability_in_state`
  (modal verbs `can` / `may` / `could` / `might`, plus the *"is able
  to <verb>"* construct). Allows copula property, possession, and
  structural verbs — those describe states.
- **capability**: rejects rule modals and sequencing. Allows capability
  modals (*"can"*, *"may"*, *"is able to"*).

Detection mixes spaCy dependency parsing for the structural categories
with literal regex passes for hedges, compound phrases, and
hidden_event_state. All matching runs against a normalized form of the
text — case-folded, NFKC, with curly quotes, dash variants, and
non-breaking spaces folded to ASCII — so callers can't slip past with
fancy unicode. The reported `position` and `matched_text` map back to
the original text via a per-character position map so consumers can
display offsets that line up with what the writer typed.

By default any violation rejects the call: the response is
`{"rejected": true, "violations": [...]}` with no mutation. Pass
`allow_phrasing_violations=true` to bypass and proceed; the success
response then carries the same violations under `phrasing_violations`
as a warning. Use the bypass only for verbatim quotes, contract
clauses, or other text whose exact wording is the fact.

## Transports

Mycelium ships two transports for the same tool surface. Both processes
share the same data directory but the substrate is single-writer, so
running both with write traffic against the same directory simultaneously
is unsupported.

### MCP over stdio

The MCP transport speaks JSON-RPC over standard input and output. It is
launched as `uv run python -m mycelium`, which is what Claude Desktop
spawns when the user adds Mycelium to `claude_desktop_config.json`. The
process appears to hang when started by hand because stdio is occupied by
the protocol — that is expected.

The MCP server uses the official Anthropic `mcp` package and the
`FastMCP` server class. Tools are registered via `mcp.tool()` inside the
`@tool` decorator, which means every registered tool's signature and
docstring become the tool's MCP schema and description automatically.

### HTTP via FastAPI

The HTTP transport is launched as `uv run mycelium-http` and listens on
`127.0.0.1:8765` by default. The host and port can be overridden via the
`MYCELIUM_HTTP_HOST` and `MYCELIUM_HTTP_PORT` environment variables.

Endpoints are auto-generated from the tool registry: each tool name is
kebab-cased to form the path (so `search_statements` becomes
`/search-statements`), the HTTP method is `GET` for tools with no
arguments and `POST` otherwise, and the request body's Pydantic schema
is built at import time from the function signature using
`pydantic.create_model`. A typed-dict `LinkSpec` ensures that
`upsert_statement`'s `links` parameter renders in OpenAPI as a structured
schema rather than a free-form list of dicts.

Errors raised as `ValueError` in any tool are caught by a single FastAPI
exception handler and rendered as HTTP 400 with the exception message
in the `detail` field.

The interactive OpenAPI docs are served at `/docs`.

### HTTP-only endpoints

A small set of endpoints exist purely to back the bundled web UI and are
not registered as MCP tools. `GET /` 307-redirects to `/ui/`. `GET
/ui/*` serves static files from `src/mycelium/ui/`. `GET /api/data`
returns the entire substrate as a JSON document with the shape
`{entities, names, statements, links}`, where each entity is given a
synthesised `name` field by picking the alphabetically first text from
its names (falling back to the entity_id if it has none) and each
statement's `mentions` is a deduplicated list of `entity_ids` since the
UI renders mentions as entity chips.

## Browser UI

The browser UI is a read-only React application bundled inside
`src/mycelium/ui/` and served as static files. It does not have a build
step: React, ReactDOM, and Babel-Standalone are loaded from the unpkg
CDN, and Babel transpiles the JSX in the browser at page load.

The UI is a single-page application backed by hash-based routing. It
loads the entire substrate in one fetch from `/api/data` at startup,
indexes the data into in-memory lookup tables, and renders all
subsequent navigation client-side. This works for the MVP scale of
hundreds of statements but does not paginate; for substantially larger
substrates the UI would need per-route fetching.

The UI's design language is "instrument" rather than "document":
near-black backgrounds with an acid-mycelium-green accent in dark mode,
Geist Sans for prose and JetBrains Mono for structural metadata,
Linear/Vercel/Stripe-style dev-tool aesthetic. A tweaks panel lets the
user toggle theme (dark or light), density (compact, comfortable, or
roomy), and an "edit affordances" preview toggle.

The statement detail page is the most important screen. It opens with a
dense top header bar containing a kind-square mark, the statement id, a
four-cell stat strip showing incoming-link, outgoing-link, link-type,
and entity counts, an inline neighborhood thumbnail, and operations
buttons. Below the bar sits a generous body pane with the statement text
in 19px serifless prose and entity mentions linkified as dotted-underline
spans.

A lineage strip sits under the body text and walks the chain of
incoming primary-typed links — by default `contains` — so the user can see
where this statement sits in the structural hierarchy. The strip is
cycle-safe and capped at six hops.

The connections panel is the page's showpiece. A row of type-filter
chips above the panel lists every link type present on this statement,
with `contains` selected by default and marked as "primary" with a `▣`
indicator. Clicking a chip toggles the type's visibility; the `all` chip
is a shortcut. Selected non-primary types render as secondary edges and
nodes — thinner lines, dashed borders, dimmer colour — so that the
primary-typed structural skeleton remains visible when other types are
overlaid.

The connections graph itself is a custom horizontal SVG visualisation.
Incoming statements flow in from the left edge, outgoing statements flow
out to the right, and the current statement glows at the centre. Edges
are coloured by their `link_type` using a dedicated palette and labelled
with the type as small monospace text. A toggle in the panel header
swaps to a list view for users who prefer columns.

A peek tooltip lets the user read the full text of a connected statement
without leaving the page. Each connection node has a small `⌖` button
that appears on hover; in graph mode clicking it pops a tooltip above
the node, in list mode it expands an inline quoted block under the row.

A related-entities strip shows the entities mentioned by the statement as
clickable monospace chips, leading to entity detail.

The entity detail page shows the entity's name, description, every alias
attached to it, and the list of statements that mention it. The left rail
lists every entity in the substrate for direct navigation.

The search results page displays results across all three record kinds
in a single table with kind tabs at the top. Search is performed
client-side over the in-memory data using simple substring scoring;
unlike the MCP tool, the UI's search is not vector-based.

A graph view renders a force-directed layout of the entire substrate
with edges coloured by `link_type` and a focus-mode that shows only the
neighborhood of a selected node. It is a secondary surface — the
detail views are where real reading happens.

## Tooling and tests

The project uses `uv` as its only package manager and dependency tool;
there is no `pip install`, no `requirements.txt`, no Poetry. `uv sync`
reads `pyproject.toml` and `uv.lock`, creates a `.venv/`, and installs
everything pinned.

Three test files run under pytest: `tests/test_store.py` covers the
SQLite CRUD layer including the `statement_mentions` and `names` tables
and the `merge_entities` and `move_name` helpers in `store.py`;
`tests/test_vector.py` covers hnswlib add, replace, search, save, and
load round-trips; `tests/test_http.py` exercises every HTTP endpoint
including the new `min_score`, `depth`, and `direction` arguments on
search and the `merge_entities` and `move_name` flows. The Ollama
embedding client is monkeypatched in HTTP tests so the suite runs
without a live Ollama. The current count is fifteen tests, all passing.

A separate `scripts/smoke.py` exercises the substrate end-to-end against
a temporary data directory using a fake embedding, and is the canonical
sanity check that nothing has broken at the integration level.

## Configuration

All runtime configuration is via environment variables; no config files
beyond `pyproject.toml` are read. The substrate honours `MYCELIUM_DATA_DIR`
for the database directory (default `./.mycelium/`), `OLLAMA_URL` for the
Ollama endpoint (default `http://localhost:11434`), `EMBED_MODEL` for the
embedding model (default `nomic-embed-text`), `MYCELIUM_HTTP_HOST` for
the FastAPI bind host (default `127.0.0.1`), and `MYCELIUM_HTTP_PORT`
for the FastAPI port (default `8765`).

## Non-goals

Several features are explicitly out of scope for the MVP and will only
land if real usage forces them. Concurrent-write safety is not provided.
A reranker for search results is not implemented; vector search alone
returns top-k results. Fuzzy duplicate detection on entity creation is
not implemented; exact-name match is the only dedup. Name embeddings
are not implemented; names are exact-match-only at write time and
search time. Authentication on the MCP and HTTP servers is not
implemented; the deployment posture is local-first. A query language is
explicitly never going to be exposed; the tool primitives are the
surface. Migrations beyond the initial schema are not supported; the
expected upgrade path is to wipe the data directory and re-ingest. There
is no CLI inspection tool or human-readable dump format other than the
browser UI.
