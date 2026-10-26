# knowledge-model Specification

## Purpose
Defines the substrate's records (statements, entities, names), the links between them, the checks every write must pass, the mentions derived from statement text, merges and deletes, the change history and the editable vocabularies that describe statement kinds and link types.

## Requirements

### Requirement: Statement records
The system SHALL store each statement as an atomic unit of knowledge with an opaque id prefixed `stm_`, a required `kind` and a `text`. `upsert_statement` without `id` MUST always create a new statement with a fresh id and MUST NOT deduplicate by text. The kind vocabulary is open.

#### Scenario: Same text twice creates two statements
- **WHEN** a writer calls `upsert_statement` twice with `kind: "event"`, text "An invoice export is requested" and no `id`
- **THEN** each call returns a different `statement_id` starting with `stm_`
- **AND** both statements exist

#### Scenario: Unlisted kind is accepted
- **WHEN** a writer creates a statement with a `kind` that `list_statement_kinds` does not describe
- **THEN** the statement is created with that kind

### Requirement: Wholesale statement update
`upsert_statement` with an `id` SHALL replace the statement's kind and text and replace its outgoing links with exactly the `links` passed. `incoming_links` MUST only be inserted, idempotently, and never remove existing incoming links. An unknown `id` MUST fail the call without writing.

#### Scenario: Outgoing links are replaced, not appended
- **WHEN** a statement has outgoing links to A and B and a writer calls `upsert_statement` with its `id` and `links` containing only a link to C
- **THEN** the statement's only outgoing link is the link to C

#### Scenario: Incoming links are kept
- **WHEN** a writer updates a statement with `upsert_statement` and passes no `incoming_links`
- **THEN** links from other statements to it remain

#### Scenario: Unknown id
- **WHEN** `upsert_statement` is called with an `id` that does not exist
- **THEN** the call fails with an error naming the missing statement and nothing is written

### Requirement: Reference validation before mutation
Statement writes SHALL check, before changing anything, that every statement referenced by `links[].to_id`, `incoming_links[].from_id` and every `when` leaf exists. A missing reference MUST fail the whole call with an error naming its position, such as `links[0].to_id`.

#### Scenario: Typo in a link target
- **WHEN** `upsert_statement` is called with a `links` entry whose `to_id` does not exist
- **THEN** the call fails with an error that names `links[0].to_id` and the missing id
- **AND** no statement is created

### Requirement: Text-only statement edits
`replace_text(id, text)` SHALL change only a statement's text, phrasing-checked under its current kind, and MUST leave its kind and links untouched. It MUST fail on an unknown id.

#### Scenario: Fix wording without re-listing links
- **WHEN** a writer calls `replace_text` on a statement with three outgoing links
- **THEN** the text changes and all three links remain

### Requirement: Partial statement edits
`patch_statement(id, kind?, text?)` SHALL change only the fields passed and MUST NOT touch links. A text patch MUST be phrasing-checked under the effective kind (the new kind when both are passed). A kind-only patch MUST NOT re-embed or re-derive mentions. A call with neither field MUST return `{statement_id, no_change: true}`. An unknown id MUST fail the call.

#### Scenario: Re-classify without touching links
- **WHEN** a writer calls `patch_statement` with only `kind: "state"`
- **THEN** the statement's kind changes and its text, links and mentions are unchanged

#### Scenario: Kind and text patched together
- **WHEN** a writer calls `patch_statement` with `kind: "rule"` and text "An admin must approve the export"
- **THEN** the text is checked against the `rule` catalog rather than the statement's previous kind

#### Scenario: Empty patch
- **WHEN** `patch_statement` is called with only an `id`
- **THEN** it returns `no_change: true` and writes nothing

### Requirement: Writes succeed without embeddings
A statement write that sets text SHALL succeed when the embedding service is unavailable and MUST report `embedding_pending: true` (for `upsert_statements`, a list of the affected new ids). Pending embeddings are covered by the `embeddings-and-indexes` capability.

#### Scenario: Embedding service down
- **WHEN** a writer creates a statement while embeddings fail
- **THEN** the response carries `statement_id` and `embedding_pending: true`

### Requirement: Near-duplicate warnings
When new text is embedded, `upsert_statement`, `upsert_statements` and a text `patch_statement` SHALL return `near_duplicates`: up to 5 other statements `{id, text, score}` at or above the configured near-duplicate similarity (0.85 for `nomic-embed-text`). Near-duplicates MUST NOT block the write. `replace_text` does not report them.

#### Scenario: Similar statement exists
- **WHEN** a writer creates a statement whose text is nearly identical to an existing one
- **THEN** the statement is created
- **AND** the response lists the existing statement under `near_duplicates` with its score

#### Scenario: Batch keys warnings by new id
- **WHEN** one item of an `upsert_statements` batch has a near-duplicate
- **THEN** `near_duplicates` maps that item's new statement id to its hits

### Requirement: Batch statement creation
`upsert_statements` SHALL create several new statements in one call, where any `links[].to_id`, `incoming_links[].from_id` or `when` leaf may be `"@N"` to reference the Nth (0-based) item of the same batch. It SHALL return one entry per item, in order, under `results`.

#### Scenario: Umbrella and children in one call
- **WHEN** a writer sends a batch whose item 0 is a `capability` and items 1 and 2 are `event`s with `incoming_links: [{from_id: "@0", link_type: "contains"}]`
- **THEN** three statements are created and both `contains` links run from item 0's new id to items 1 and 2

#### Scenario: Empty batch
- **WHEN** `upsert_statements` is called with an empty list
- **THEN** it returns `{results: [], near_duplicates: {}}`

### Requirement: Batch reference errors fail the call
`upsert_statements` MUST fail the whole call before writing anything when a surviving item has a malformed `@N` reference, an `@N` outside the batch, or a reference to an existing statement that does not exist.

#### Scenario: Out-of-range reference
- **WHEN** a batch of two items references `@5`
- **THEN** the call fails with an error saying the batch index is out of range and nothing is written

### Requirement: Per-item batch rejection
`upsert_statements` SHALL reject items individually and still write the rest. An item failing the phrasing check without its own `allow_phrasing_violations: true` MUST yield `{rejected: true, violations}`; an item with a link-direction error MUST yield `{rejected: true, errors}`; an item that references a rejected item through `@N`, directly or transitively, MUST yield `{rejected: true, reason: "depends_on_rejected", depends_on}`.

#### Scenario: Dependent of a rejected item
- **WHEN** item 0's text is "An export usually finishes" and item 1 links to `@0`
- **THEN** item 0's result is rejected with a `hedge` violation
- **AND** item 1's result is `{rejected: true, reason: "depends_on_rejected", depends_on: [0]}`
- **AND** an unrelated item 2 is created with a `statement_id`

### Requirement: Phrasing check on statement text
Every write that creates or replaces statement text SHALL run the phrasing check for the statement's kind before mutating. When violations are found and `allow_phrasing_violations` is not true, the write MUST NOT happen and the call MUST return `{rejected: true, violations}`.

#### Scenario: Compound statement rejected
- **WHEN** a writer creates an `event` with text "An invoice is sent and the workspace owner receives a receipt"
- **THEN** the call returns `rejected: true` with a `compound` violation
- **AND** no statement is created

### Requirement: Violation shape
Each phrasing violation SHALL carry `category`, `matched_text`, `position`, `rule` and `recommendation`. The check MUST report every violation it finds in one response, ordered by position.

#### Scenario: Several problems at once
- **WHEN** an `event` reads "Every invoice is usually exported"
- **THEN** the response lists both a `universal_claim` and a `hedge` violation, in text order

### Requirement: Phrasing bypass
When `allow_phrasing_violations` is true the system SHALL perform the write anyway and MUST return the violations it found under `phrasing_violations` on the success response.

#### Scenario: Exact wording is the fact
- **WHEN** a writer passes text that trips the catalog with `allow_phrasing_violations: true`
- **THEN** the statement is written
- **AND** the response includes `phrasing_violations`

### Requirement: Phrasing catalog common to every kind
The phrasing check SHALL apply to every kind the categories `compound`, `precondition_in_text`, `universal_claim`, `hedge`, `hidden_event_state` and `sequencing`.

#### Scenario: Compound joins
- **WHEN** text contains a semicolon, "and" joining two verb clauses, "and then", "and also" or ", then"
- **THEN** a `compound` violation is reported

#### Scenario: Precondition in text
- **WHEN** text uses "when", "before", "after", "while", "until", "since", "if", "unless", "because" or "though" as a subordinating word, as in "The export starts when the admin confirms"
- **THEN** a `precondition_in_text` violation is reported

#### Scenario: Universal claim
- **WHEN** text uses the determiner "every", "all", "each" or "any", or a pronoun such as "everyone", "anyone", "nobody" or "none"
- **THEN** a `universal_claim` violation is reported

#### Scenario: "No" is not universal
- **WHEN** an `event` reads "No email is provided"
- **THEN** no violation is reported

#### Scenario: Hedge
- **WHEN** text contains "usually", "often", "mostly", "typically", "sometimes", "generally", "occasionally", "frequently", "rarely" or "in most cases"
- **THEN** a `hedge` violation is reported

#### Scenario: Hidden event and state
- **WHEN** text contains "is set to", "are set to", "become(s)", "transition(s) to" or "get(s) marked as", as in "The invoice status becomes paid"
- **THEN** a `hidden_event_state` violation is reported

#### Scenario: Future tense, even in a rule
- **WHEN** a `rule` reads "The export will start"
- **THEN** a `sequencing` violation is reported

### Requirement: Event phrasing rules
For `event` and every kind other than `state`, `capability` and `rule` (including `property`, `procedure`, `action`, `check`, `cause` and unlisted kinds), the phrasing check SHALL also flag `rule_shaped` and `property_shaped` text.

#### Scenario: Obligation in an event
- **WHEN** an `event` contains "must", "should", "shall", "ought", "never", "always", "needs to", "has to" or "is required to", as in "An admin must approve the export"
- **THEN** a `rule_shaped` violation is reported

#### Scenario: Structural claim in an event
- **WHEN** an `event` contains "is a", "has a", or a form of "consist", "belong" or "comprise", as in "An export is a background job"
- **THEN** a `property_shaped` violation is reported

### Requirement: State phrasing rules
For `state` the phrasing check SHALL also flag `rule_shaped` text and `capability_in_state` text ("can", "could", "may", "might", "is able to"), and MUST accept "is a" and "has a".

#### Scenario: Capability phrased as state
- **WHEN** a `state` reads "A workspace can use SSO"
- **THEN** a `capability_in_state` violation is reported

### Requirement: Capability phrasing rules
For `capability` the phrasing check SHALL also flag `rule_shaped` text and MUST accept capability modals such as "can" and "may".

#### Scenario: Capability modal accepted
- **WHEN** a `capability` reads "A workspace admin can enable SSO"
- **THEN** no violation is reported

### Requirement: Rule phrasing rules
For `rule` the phrasing check MUST apply only the common catalog, so obligations, permissions and definitions ("must", "may", "is required to", "never", "is a") are accepted.

#### Scenario: Obligation in a rule
- **WHEN** a `rule` reads "An admin must approve the export"
- **THEN** no violation is reported

### Requirement: Phrasing normalization
The phrasing check SHALL match against a normalized form of the text (case-folded, NFKC, curly quotes, dash variants and non-breaking or zero-width spaces folded to ASCII, whitespace runs collapsed), and MUST report `position` and `matched_text` against the original text.

#### Scenario: Typographic variants do not slip through
- **WHEN** a statement writes a hedge word in capitals next to an em dash and curly quotes
- **THEN** the hedge is still reported
- **AND** `matched_text` is the substring of the original text

### Requirement: Statement links
The system SHALL store statement links as directed, typed edges between two existing statements, identified by `(from, to, link_type, when)` with the condition compared in canonical form. Cycles, multiple parents and self-links MUST be allowed, and link types are an open vocabulary.

#### Scenario: Same endpoints, different conditions
- **WHEN** two links share endpoints and type but carry different `when` conditions
- **THEN** both are stored as distinct edges

### Requirement: Adding statement links
`add_links(links)` SHALL insert `{from_id, to_id, link_type, when?}` edges, MUST skip edges that already exist, and SHALL return `{inserted}` with the number actually added. It MUST validate every endpoint and `when` leaf before inserting, so any error leaves the whole batch unwritten.

#### Scenario: Re-adding an existing edge
- **WHEN** a writer calls `add_links` twice with the same `{from_id, to_id, link_type}`
- **THEN** the first call returns `inserted: 1` and the second `inserted: 0`

#### Scenario: Unknown endpoint
- **WHEN** one edge in an `add_links` batch names a statement that does not exist
- **THEN** the call fails and no edge in the batch is inserted

### Requirement: Statement links connect statements only
`add_links` and `remove_links` MUST reject any edge with an entity (`ent_`) endpoint or an id that is neither `stm_` nor `ent_`. Entity-to-statement links SHALL NOT exist; entity-to-entity edges belong to `add_entity_links` and `remove_entity_links`.

#### Scenario: Mixed batch
- **WHEN** an `add_links` batch contains one valid statement edge and one edge from an `ent_` id
- **THEN** the call fails with an error pointing to `add_entity_links`
- **AND** neither edge is inserted

### Requirement: Removing statement links
`remove_links` SHALL delete edges matched on `from_id`, `to_id`, `link_type` and the canonical form of `when`, and SHALL return `{removed}`. Missing edges and nonexistent endpoints MUST be skipped silently.

#### Scenario: Reordered condition matches
- **WHEN** an edge was added with `when: {op: "and", of: [A, B]}` and `remove_links` is sent `{op: "and", of: [B, A]}`
- **THEN** the edge is removed and `removed` is 1

### Requirement: Link direction rules
For link types whose ends have fixed statement kinds, the system SHALL reject an edge that is provably backwards (its kinds fail the rule but fit it with the ends swapped) with an error saying the direction looks flipped and to swap `from_id` and `to_id`. Edges that fit neither direction, and types without a rule, MUST NOT be rejected by this check.

#### Scenario: Rule table
- **WHEN** a caller reads the direction rules
- **THEN** they are: `teaches` procedure -> capability; `performs` action -> event; `verifies` check -> state; `violates` cause -> state; `confirms` and `refutes` check -> cause; `resolves` action -> cause; `obtained-by` property -> action or procedure; `accepts` any -> property; `establishes` any -> state; `valued-by` and `governed-by` any -> rule

#### Scenario: Flipped teaches
- **WHEN** `add_links` is called with a `teaches` edge from a `capability` to a `procedure`
- **THEN** the call fails with a flipped-direction error telling the caller to swap the ends

#### Scenario: Correct direction
- **WHEN** `add_links` is called with a `teaches` edge from a `procedure` to a `capability`
- **THEN** the edge is inserted

#### Scenario: Unconstrained type
- **WHEN** a `contains` edge links two `event` statements
- **THEN** the direction check does not reject it

### Requirement: Direction checks on every link-writing path
The direction check SHALL run on `add_links` (failing the whole call), on `upsert_statement` for both `links` and `incoming_links` using the kind being written (failing the whole call), and on `upsert_statements` per item including `@N` siblings (rejecting that item and its dependents).

#### Scenario: Kind change in the same upsert
- **WHEN** `upsert_statement` with an `id` changes the kind and passes a `links` entry that is only correct for the new kind
- **THEN** the check uses the new kind and the write succeeds

### Requirement: Link type listing
`list_link_types` SHALL return every statement link type that is in the glossary or in use, sorted alphabetically, each with `link_type`, `type`, `description` (empty when not in the glossary), `usage_count`, `in_use` (`"true"` or `"false"`) and, for types with a direction rule, `direction: {source_kinds, target_kinds}` where `null` means any kind.

#### Scenario: Direction shown for teaches
- **WHEN** a reader calls `list_link_types`
- **THEN** the `teaches` entry has `direction: {source_kinds: ["procedure"], target_kinds: ["capability"]}`

### Requirement: Link conditions
A statement link MAY carry a `when` condition: a tree whose leaves are `{"statement_id": "stm_..."}` and whose inner nodes are `{"op": "and" | "or", "of": [...]}` with at least one child or `{"op": "not", "of": [<one child>]}`. The system MUST reject a malformed tree. A link without `when` is unconditional.

#### Scenario: Conditional trigger
- **WHEN** a writer adds a `triggers` link with `when: {op: "not", of: [{statement_id: <"The invoice is already paid">}]}`
- **THEN** the link is stored with that condition

#### Scenario: Malformed trees
- **WHEN** a `when` node has both or neither of `statement_id` and `op`, extra keys, an unknown `op`, an empty `of`, a `not` with other than one child, or an empty leaf id
- **THEN** the write fails with an error describing the problem

### Requirement: Condition canonicalization
The system SHALL store conditions in canonical form: nested same-op `and`/`or` nodes flattened, duplicate children removed, children sorted deterministically, single-child `and`/`or` collapsed to the child, and `not(not(X))` reduced to `X`. Conditions with the same canonical form MUST identify the same edge.

#### Scenario: Equivalent shapes are one edge
- **WHEN** a writer adds an edge with `when: {op: "and", of: [A, {op: "and", of: [B, A]}]}` and then the same edge with `when: {op: "and", of: [B, A]}`
- **THEN** the second `add_links` returns `inserted: 0`

### Requirement: Merging statements
`merge_statements(from_id, into_id)` SHALL move the source's links and media onto the target, rewrite `when` leaves that referenced the source to the target, and delete the source, leaving the target's text unchanged. Moved links that would become self-loops, or that collide with an existing link of the same `(from, to, link_type, when)`, MUST be dropped. Merging a statement into itself MUST be a no-op; an unknown id MUST fail the call.

#### Scenario: Duplicate wording collapsed
- **WHEN** statements S1 and S2 say the same thing, S1 has an incoming `contains` link from P, and an admin merges S1 into S2
- **THEN** S1 no longer exists, P `contains` S2, and S2's text is unchanged
- **AND** the response is `{into_id, mentions_moved: 0, outgoing_links_moved, incoming_links_moved}` counting only links that survived

#### Scenario: Link between the pair
- **WHEN** S1 has a link to S2 and S1 is merged into S2
- **THEN** that link is dropped rather than becoming a self-loop

### Requirement: Deleting statements
`delete_statement(id)` SHALL permanently delete a statement with its mentions, its outgoing and incoming links, every link whose `when` condition references it, its vector and its media attachments, and SHALL return `{deleted: true, mentions_removed, incoming_links_removed, outgoing_links_removed, when_references_removed}`. An unknown id MUST fail the call.

#### Scenario: Statement used as a condition
- **WHEN** statement C is a `when` leaf on a link between A and B and an admin deletes C
- **THEN** the link between A and B is removed
- **AND** `when_references_removed` is 1

### Requirement: Entities
The system SHALL store entities as long-lived referents with an opaque `ent_` id, a description and an optional preferred name; an entity's textual identity lives in its names. Entity descriptions are not embedded.

#### Scenario: Entity without names
- **WHEN** an entity's last name is deleted
- **THEN** the entity remains and is displayed by its id

### Requirement: Creating and updating entities by name
`upsert_entity(name, description)` SHALL resolve `name` case-insensitively against all names. When a name matches it MUST update that name's entity's description and return its `entity_id`; otherwise it MUST create a new entity with that name and its generated plural.

#### Scenario: Case-variant resolves to the existing entity
- **WHEN** an entity is named "Workspace" and a writer calls `upsert_entity` with name "WORKSPACE"
- **THEN** the existing entity's description is updated and its id returned
- **AND** no new entity is created

### Requirement: Entity detail
`get_entity(id)` SHALL return `id`, `missing: []`, `description`, `preferred_name_id`, the created/updated timestamps and actors, `names` as `[{id, text}]` with the preferred name first then alphabetical, `links` as `[{to_entity_id, link_type}]` and `incoming_links` as `[{from_entity_id, link_type}]`. For an unknown id it MUST return only `{id, missing: [id]}`.

#### Scenario: Missing entity
- **WHEN** a reader calls `get_entity` with an id that does not exist
- **THEN** the response is `{id, missing: [id]}` with no `names` or `links`

### Requirement: Entity listing
`list_entities(prefix="", limit=50, offset=0)` SHALL return `{total, entities: [{id, name, description}]}`, matching `prefix` case-insensitively against any of an entity's names, where `name` is the preferred name, falling back to the alphabetically first name and then the id. `limit` MUST be between 1 and 100.

#### Scenario: Prefix matches an alias
- **WHEN** an entity's preferred name is "Single sign-on", it has the alias "SSO", and a reader lists with `prefix: "ss"`
- **THEN** the entity is returned under the name "Single sign-on"

### Requirement: Entity search
`search_entities(query, k=10, min_score?)` SHALL search the name index and return each entity once, under its best-scoring name, as `{entities: [{id, name, matched_name, score, description}]}` sorted by score, at most `k`. Names below `min_score` (default from the embedding model, 0.3 for `nomic-embed-text`) MUST be ignored. An empty query MUST be rejected.

#### Scenario: Alias match reported
- **WHEN** a reader's query best matches the alias "Login" of an entity whose preferred name is "Sign-in"
- **THEN** the entity is returned with `name: "Sign-in"` and `matched_name: "Login"`

### Requirement: Entity search keyword fallback
When the query cannot be embedded, `search_entities` SHALL fall back to case-insensitive name substring matching, scoring an exact name 1.0 and other matches 0.5, and MUST mark each result `retrieval: "keyword"`.

#### Scenario: Embedding outage
- **WHEN** the embedding service is down and a reader searches "invoice"
- **THEN** entities with a name containing "invoice" are returned with `retrieval: "keyword"`

### Requirement: Merging entities
`merge_entities(from_entity_id, into_entity_id)` SHALL move every name, entity link, media attachment and generated-document anchor of the source to the target and delete the source, returning `{into_entity_id, names_moved, documents_unanchored}`. Entity links that would become self-loops or duplicates MUST be dropped. Merging an entity into itself is a no-op; an unknown id MUST fail the call.

#### Scenario: Two entities for one concept
- **WHEN** "Invoice" and "Bill" are separate entities and an admin merges "Bill" into "Invoice"
- **THEN** "Bill" becomes a name of the "Invoice" entity
- **AND** statements that mentioned "Bill" now mention the "Invoice" entity

#### Scenario: Anchor collision
- **WHEN** both entities anchor a generated document of the same guideline set and type
- **THEN** the source's document keeps its body but loses its anchor
- **AND** `documents_unanchored` counts it

### Requirement: Deleting entities
`delete_entity(id)` SHALL permanently delete an entity with all its names, the mentions of those names and the entity links from or to it; anchored generated documents MUST keep their body and history but lose the anchor. It SHALL return `{deleted: true, names_removed, mentions_removed, outgoing_entity_links_removed, incoming_entity_links_removed, documents_unanchored}` and fail on an unknown id.

#### Scenario: Retired concept
- **WHEN** an admin deletes an entity with the name "Legacy export" (and its plural) and one outgoing entity link
- **THEN** the response reports `names_removed: 2` and `outgoing_entity_links_removed: 1`

### Requirement: Entity links
The system SHALL store entity links as directed, typed, unconditional edges between two existing entities, keyed by `(from_entity_id, to_entity_id, link_type)`, with a vocabulary separate from statement link types. Entity links are not embedded.

#### Scenario: Structural relationship
- **WHEN** a writer adds `{from_entity_id: <Workspace>, to_entity_id: <Invoice>, link_type: "contains"}`
- **THEN** `get_entity(<Workspace>)` lists it under `links`

### Requirement: Adding and removing entity links
`add_entity_links` MUST reject a self-loop and any unknown entity before inserting anything, MUST skip existing edges, and SHALL return `{inserted}`. `remove_entity_links` SHALL delete exact triples, skip missing ones without validating entities, and return `{removed}`.

#### Scenario: Self-loop
- **WHEN** `add_entity_links` is called with the same entity at both ends
- **THEN** the call fails and nothing is inserted

### Requirement: Names are unique across the substrate
Each name SHALL belong to exactly one entity, carry an opaque `nam_` id, and be unique case-insensitively across the whole substrate.

#### Scenario: Alias taken by another entity
- **WHEN** "SSO" belongs to entity A and a writer calls `upsert_name("sso", B)`
- **THEN** the call fails with an error suggesting `move_name` or `merge_entities`

### Requirement: Adding names
`upsert_name(text, entity_id)` SHALL attach a name and its generated plural to an existing entity and return `{name_id}`. It MUST fail when the entity does not exist, and MUST return the existing `name_id` unchanged when the text, in any casing, already belongs to that entity.

#### Scenario: Idempotent alias
- **WHEN** "SSO" belongs to entity A and a writer calls `upsert_name("SSO", A)`
- **THEN** the existing name id is returned

### Requirement: Generated plurals
When a name is created the system SHALL also create its regular English plural as a generated name of the same entity, unless the plural text is taken or no confident plural exists. A generated plural MUST follow its source name when the source is moved, deleted or respelled.

#### Scenario: Plural rules
- **WHEN** names "invoice batch", "company", "SSO token" and "export" are created
- **THEN** "invoice batches", "companies", "SSO tokens" and "exports" are generated, inflecting the last word ("ss", "x", "z", "ch", "sh" add "es"; consonant plus "y" becomes "ies"; others add "s")

#### Scenario: Ambiguous plural skipped
- **WHEN** a writer creates the name "status"
- **THEN** no plural is generated, as for any name ending in a single "s" or a non-letter

### Requirement: Moving names
`move_name(name_id, to_entity_id)` SHALL rebind a name and its generated plurals to another existing entity, keeping their text and ids, so statements that mentioned them now mention the new entity. It MUST fail on an unknown name or entity.

#### Scenario: Move keeps references
- **WHEN** a writer moves the name "Billing portal" from entity A to entity B
- **THEN** statements whose text contains "Billing portal" mention entity B

### Requirement: Respelling names
`rename_name(name_id, new_text)` SHALL change a name's spelling in place, keeping its id and entity, stop matching the old spelling and regenerate its plural. It MUST fail when the new text belongs to a different name.

#### Scenario: Respell
- **WHEN** a writer renames "Invoce" to "Invoice"
- **THEN** statements containing only "Invoce" stop mentioning the entity
- **AND** statements containing "Invoice" come to mention it once the background recompute runs

### Requirement: Removing names
`delete_name(name_id)` SHALL remove a name, its generated plurals and their mentions, return `{deleted: true, mentions_removed}`, and leave the entity in place even with no names. It MUST fail on an unknown id.

#### Scenario: Wrong alias removed
- **WHEN** a writer deletes an alias attached by mistake
- **THEN** statements stop mentioning the entity through it and the entity keeps its other names

### Requirement: Preferred names
Each entity SHALL have at most one preferred name used for display. A new entity's first authored name MUST become preferred, and adding an alias MUST NOT change it. When the preferred name is moved or deleted the system MUST select a remaining authored name in case-insensitive order, or another remaining name if no authored one remains.

#### Scenario: Preferred name removed
- **WHEN** the preferred name "Workspace" is deleted from an entity that also has the alias "Team space"
- **THEN** "Team space" becomes the preferred name

### Requirement: Names workspace preview and apply
The Names & aliases API SHALL offer the actions `add`, `correct`, `prefer`, `move`, `split`, `merge` and `remove` through `POST /api/names-workspace/preview` and `POST /api/names-workspace/apply`. Apply MUST require the preview's `expected_revision` and MUST answer HTTP 409 when entities, names, statements or entity links changed since. No action rewrites statement text.

#### Scenario: Stale preview
- **WHEN** a curator previews adding the alias "Bill" and another writer edits a statement before the curator applies
- **THEN** apply returns HTTP 409 and asks for a fresh preview

#### Scenario: Generated plural targeted
- **WHEN** a curator tries to move, correct, prefer or remove a generated plural
- **THEN** the request is refused with a message to edit the source name

#### Scenario: Merge and split choices
- **WHEN** a curator merges two concepts or splits names off one
- **THEN** the curator chooses the surviving description and preferred name, and a merge reports `documents_unanchored`

### Requirement: Names workspace permissions
Names workspace reads SHALL be open to any authenticated caller. Preview and apply MUST require a real writer, so drafters cannot apply edits, and `merge` and `remove` MUST require an admin.

#### Scenario: Writer cannot merge
- **WHEN** a writer who is not an admin previews a `merge`
- **THEN** the request is refused for lack of the admin role

### Requirement: Derived mentions
The system SHALL derive a statement's mentions from its text against all current names, and callers MUST NOT be able to assert or set mentions. A mention records which name matched; its entity is whichever entity that name currently belongs to, with at most one mention per entity.

#### Scenario: Mentions are not an input
- **WHEN** a writer creates a statement whose text contains the name "service account"
- **THEN** the statement mentions that entity without the writer listing it

### Requirement: Mention matching
Mention matching SHALL compare normalized tokens (maximal runs of letters or digits after the phrasing normalization), match multi-word names as consecutive token runs, keep the longest span (leftmost on ties) and drop shorter overlapping matches. Names that cover exactly the same span MUST all be kept as co-mentions.

#### Scenario: Token boundaries
- **WHEN** an entity is named "invoice" and a statement says "The invoicer runs nightly"
- **THEN** the statement does not mention that entity

#### Scenario: Longest match wins
- **WHEN** entities are named "service account" and "account" and a statement says "A service account is created"
- **THEN** the statement mentions "service account" and not "account"

### Requirement: Ambiguous names are not mentions
A single-token name SHALL be ambiguous when its token is a stop word, at most 6 characters long, or at least 5 characters long and ending in "ed"; multi-word names never are. A match through an ambiguous name MUST NOT become a mention unless a historical curator approval for that statement and name exists and still matches. Neither mentions nor possible matches create statement links.

#### Scenario: Short alias
- **WHEN** the alias "SSO" matches a statement and no approval exists
- **THEN** the statement does not mention that entity through "SSO"
- **AND** the match appears as `possible` in mention candidates

### Requirement: Mention recomputation
The system SHALL derive mentions synchronously whenever a statement's text is created or changed. When names are added, moved, respelled or deleted, or entities merged or deleted, it SHALL recompute affected statements' stored mentions in the background and MUST retry interrupted work after a restart.

#### Scenario: New alias picked up
- **WHEN** a writer adds the alias "Bill" to the "Invoice" entity
- **THEN** existing statements containing "Bill" come to mention the "Invoice" entity once the background recompute runs

### Requirement: Mention candidates
`get_mention_candidates(entity_id, after=0, limit=50)` SHALL scan at most 2,000 statements after the `after` cursor and return `{matches, next_after, has_more, scanned}`, each match `{statement_id, text, kind, names, match}` with `match` one of `derived`, `approved` or `possible`. It MUST reject a negative `after`, a `limit` outside 1..200 and an unknown entity, and MUST NOT write.

#### Scenario: Empty page with more to scan
- **WHEN** the first 2,000 statements after the cursor contain no match for the entity
- **THEN** the page has no matches, `has_more: true` and a `next_after` to continue from

#### Scenario: HTTP access
- **WHEN** a signed-in reader calls `GET /api/mention-candidates?entity_id=...`
- **THEN** the same page is returned as the MCP tool returns

### Requirement: Vocabulary glossaries
The system SHALL keep three editable glossaries: statement kinds (`kind`, `description`, `when_to_use`), statement link types and entity link types (`link_type`, `description`). Glossary entries are documentation and MUST NOT restrict which kinds or link types a write accepts or change phrasing or direction enforcement.

#### Scenario: Deleted kind entry
- **WHEN** a writer deletes the glossary entry for `cause` and statements of kind `cause` exist
- **THEN** those statements are unchanged and `list_statement_kinds` still lists `cause` with an empty description and its `usage_count`

### Requirement: Glossary seeding
A glossary table SHALL be seeded only when it is first created, so later edits and deletions persist across restarts and new seed entries do not reach existing databases.

#### Scenario: Fresh substrate
- **WHEN** a new data directory starts
- **THEN** the kinds `event`, `state`, `capability`, `rule`, `property`, `procedure`, `action`, `check`, `cause` are described
- **AND** 28 statement link types are described, including `contains`, `triggers`, `establishes`, `requires`, `governed-by`, `teaches`, `next`, `on-success` and `on-failure`
- **AND** the entity link types `contains`, `replaces`, `sub-type`, `has` and `uses` are described

### Requirement: Vocabulary listing
`list_statement_kinds` SHALL return `[{kind, description, when_to_use, usage_count}]` and `list_entity_link_types` `[{link_type, type, description, usage_count, in_use}]`, each covering every glossary entry and every value in use, sorted alphabetically.

#### Scenario: Kind in use without glossary entry
- **WHEN** statements use a kind with no glossary entry
- **THEN** `list_statement_kinds` lists it with empty `description` and `when_to_use`

### Requirement: Vocabulary editing
`upsert_statement_kind`, `upsert_link_type` and `upsert_entity_link_type` SHALL create or update a glossary entry and MUST reject an empty key or description. `delete_statement_kind`, `delete_link_type` and `delete_entity_link_type` SHALL be idempotent and MUST leave records carrying the value untouched.

#### Scenario: Empty description
- **WHEN** a writer calls `upsert_link_type` with `description: " "`
- **THEN** the call fails and the glossary is unchanged

### Requirement: Link type aliases
The system SHALL keep alternative phrasings for canonical statement link types, each `{link_type, alias, provenance, score, direction}`, while links always store the canonical type. The same alias MAY be registered under several types. An empty alias table SHALL be seeded with built-in phrasings (provenance `seed`), including reverse-reading ones such as "is part of" for `contains`.

#### Scenario: Listing aliases
- **WHEN** a reader calls `list_link_type_aliases` with `link_type: "requires"`
- **THEN** the seeded alias "is required for" is listed with `direction: "reverse"` and `score: null`

### Requirement: Editing link type aliases
`upsert_link_type_alias` SHALL normalize the alias (case-folded, whitespace collapsed) and return `{link_type, alias, provenance, score, direction, created}`. It MUST accept `provenance` only as `curator` (default), `auto` or `auto:low-confidence`, require a `score` in [-1, 1] for the automatic ones, and accept `direction` only as `forward` (default) or `reverse`. `delete_link_type_alias` SHALL be idempotent.

#### Scenario: Reverse phrasing
- **WHEN** a curator registers "Is Billed Under" for `contains` with `direction: "reverse"`
- **THEN** the alias is stored as "is billed under", reading the edge from the far side

#### Scenario: Automatic alias without score
- **WHEN** `upsert_link_type_alias` is called with `provenance: "auto"` and no score
- **THEN** the call fails

### Requirement: Change history
The system SHALL record substrate changes in the history database in the same transaction as the write, each event carrying `at`, `actor`, `op` (`create`, `update`, `delete`, `link`, `unlink`), `target_kind`, `target_id` and `before`/`after`/`context` snapshots. A rolled-back write MUST leave no history event.

#### Scenario: Recorded changes
- **WHEN** a caller inspects the history
- **THEN** it finds statement and entity creates, updates and deletes; name creates and updates; statement and entity links added, replaced, removed or rewritten by a merge; invalidated historical mention approvals; and each Names & aliases apply with its action in `context`

#### Scenario: Not recorded
- **WHEN** audience labels, knowledge gaps, glossaries, link type aliases or duplicate dismissals change
- **THEN** no history event is recorded

#### Scenario: Rollback leaves no trace
- **WHEN** a statement write fails partway through its transaction
- **THEN** neither the statement change nor a history event persists

#### Scenario: Merge provenance
- **WHEN** S1 is merged into S2
- **THEN** the history holds a `delete` event for S1 whose context names S2 as `merged_into`

### Requirement: Knowledge-model tool roles
Knowledge-model tools SHALL be gated by name: `list_`, `get_`, `search_`, `find_`, `grep_` and `discover_` tools need a reader, `delete_` and `merge_` tools need an admin, and other writes need a writer (see the `access-control` capability). For a drafter, every substrate write tool MUST queue the call on a draft instead of changing the substrate (see the `drafts-and-review` capability).

#### Scenario: Writer cannot delete
- **WHEN** a writer calls `delete_statement`
- **THEN** the call is refused for lack of the admin role

#### Scenario: Drafter write is queued
- **WHEN** a drafter calls `upsert_statement`
- **THEN** the substrate is unchanged and the operation is queued on the drafter's open draft

### Requirement: Knowledge-model tool surfaces
Every knowledge-model tool SHALL be served over HTTP at its kebab-case name (for example `POST /upsert-statement`). Of the knowledge-model tools, MCP MUST advertise only `get_entity`, `list_entities`, `search_entities`, the three vocabulary listings, `upsert_entity`, `upsert_name`, `upsert_statement`, `upsert_statements`, `patch_statement`, `add_links`, `remove_links`, `add_entity_links`, `remove_entity_links`, `merge_statements`, `merge_entities` and `delete_statement`.

#### Scenario: HTTP-only tools
- **WHEN** an MCP client lists tools
- **THEN** `replace_text`, `move_name`, `rename_name`, `delete_name`, `delete_entity`, `get_mention_candidates` and the glossary and alias editing tools are absent
- **AND** they remain callable over HTTP

### Requirement: History feed
`GET /api/history` SHALL return `{events, total, limit, offset}` newest first, each event `{event_id, at, actor, op, target_kind, target_id, before, after, context}`, with statement-link events addressed as `from|to|link_type`. `limit` MUST be clamped to 1..500 (default 50). Optional filters are comma-separated `op` and `target_kind` and a case-insensitive literal substring `q` on `target_id`.

#### Scenario: Filter deletes
- **WHEN** a reader requests `/api/history?op=delete&target_kind=statement`
- **THEN** only statement delete events are returned, newest first

#### Scenario: Reader sees earlier versions
- **WHEN** a reader reads the feed for a statement whose text was edited
- **THEN** the edit event carries its `before` and `after` values

### Requirement: Failing mention recomputes
The system SHALL redo a failing chunk of queued mention recomputes one at a time, so the rest complete, and SHALL pass over a queued recompute that failed more often than `mention_retries` (Automation limits, default 2), listing it as stopped until an admin retries it.

#### Scenario: One recompute keeps failing
- **WHEN** one queued recompute fails every time and others are queued behind it
- **THEN** the others complete, and the failing one is listed as stopped once past its limit

### Requirement: Names workspace over MCP
The system SHALL advertise `get_names_workspace(view, q?, entity_id?, status?)` to readers, returning the names catalogue, one concept with the `revision` an edit needs, dismissed duplicate pairs or the AI's alias suggestions. It SHALL advertise `edit_names(request)` to real writers and admins, which previews and applies the workspace's changes against that revision, dismisses or restores a duplicate pair, and scans for or reviews alias suggestions.

#### Scenario: Drafter edits names
- **WHEN** a drafter calls `edit_names`
- **THEN** the call is refused, since these edits land live

### Requirement: Names workspace roles over MCP
Through `edit_names`, merge and remove SHALL need a real admin and reviewing an alias suggestion a human writer, as in the web app.

#### Scenario: Writer merges concepts
- **WHEN** a writer agent previews a merge of two concepts
- **THEN** the call is refused for want of the admin role

#### Scenario: Stale preview
- **WHEN** an admin agent applies a change with a revision from before another edit
- **THEN** the change is refused and nothing is written

### Requirement: Glossary over MCP
The system SHALL advertise `edit_vocabulary(request)` and `list_link_type_aliases`, saving or deleting a statement kind, link type, link-type alias or entity link type as the Glossary screen does. Deleting SHALL need an admin, and a drafter's edit SHALL be queued on their draft.

#### Scenario: Drafter adds a link type
- **WHEN** a drafter saves a new link type through `edit_vocabulary`
- **THEN** the answer is a draft receipt and the glossary is unchanged until the draft is applied
