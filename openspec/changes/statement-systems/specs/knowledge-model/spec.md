## ADDED Requirements

### Requirement: Statement system
A statement SHALL have an optional system: the entity of the app or platform its behaviour or step belongs to. A statement without one belongs to the knowledge base's own product.

#### Scenario: A step in another platform
- **WHEN** a writer creates the action "Copy the signing secret from the Webhooks page" with `system: "Paylark"`
- **THEN** the statement's system is the Paylark entity

### Requirement: Writing a statement's system
`upsert_statement`, `upsert_statements` and `patch_statement` SHALL accept `system` as an entity id or an exact name resolved case-insensitively; `upsert_statements` SHALL also accept a batch `system` that an item's own `system` overrides. On an update, an omitted `system` MUST keep the current one and `system: null` MUST clear it. A `system` that does not resolve MUST fail the call before anything is written.

#### Scenario: Text fix keeps the system
- **WHEN** a statement's system is Paylark and a writer calls `upsert_statement` with its `id`, new text and no `system`
- **THEN** the text changes and the system is still Paylark

#### Scenario: Unknown system
- **WHEN** a writer passes `system: "Paylrk"` and no entity has that name
- **THEN** the call fails with an error naming it and nothing is written

#### Scenario: Batch default with an override
- **WHEN** a writer sends a batch with `system: "Paylark"` whose item 2 passes `system: null`
- **THEN** every item but item 2 belongs to Paylark and item 2 has no system

### Requirement: A system change is not a content change
Changing only a statement's system MUST NOT re-embed it, re-derive its mentions or change its `updated_at`, so curation and document freshness do not read it as a content change. The change SHALL be recorded in the statement's history, and setting the system it already has SHALL write nothing.

#### Scenario: Clearing the system
- **WHEN** a writer calls `patch_statement` with `system: null` on a statement whose system is Paylark
- **THEN** the statement has no system and its text, links and mentions are unchanged

#### Scenario: Assigning a system keeps settled curation settled
- **WHEN** a statement settled as `no_link` in curation gets `system: "Paylark"` and nothing else changes
- **THEN** its `updated_at` is unchanged, it is not offered again as `isolated`, and its history shows the change

### Requirement: Systems in drafts
A queued statement operation SHALL carry the `system` it was written with, show it in the draft's operations, and apply it on approval. `open_draft` SHALL take no default system.

#### Scenario: Reviewing a queued step
- **WHEN** a writer queues a statement with `system: "Paylark"` on their draft
- **THEN** the draft's operation shows the Paylark system and approving it creates the statement with that system

## MODIFIED Requirements

### Requirement: Partial statement edits
`patch_statement(id, kind?, text?, system?)` SHALL change only the fields passed and MUST NOT touch links. A text patch MUST be phrasing-checked under the effective kind (the new kind when both are passed). A kind-only or system-only patch MUST NOT re-embed or re-derive mentions. A call with none of these fields MUST return `{statement_id, no_change: true}`. An unknown id MUST fail the call.

#### Scenario: Re-classify without touching links
- **WHEN** a writer calls `patch_statement` with only `kind: "state"`
- **THEN** the statement's kind changes and its text, links and mentions are unchanged

#### Scenario: Kind and text patched together
- **WHEN** a writer calls `patch_statement` with `kind: "rule"` and text "An admin must approve the export"
- **THEN** the text is checked against the `rule` catalog rather than the statement's previous kind

#### Scenario: Empty patch
- **WHEN** `patch_statement` is called with only an `id`
- **THEN** it returns `no_change: true` and writes nothing

### Requirement: Merging statements
`merge_statements(from_id, into_id)` SHALL move the source's links and media onto the target, rewrite `when` leaves that referenced the source to the target, and delete the source, leaving the target's text unchanged. Moved links that would become self-loops, or that collide with an existing link of the same `(from, to, link_type, when)`, MUST be dropped. Merging a statement into itself MUST be a no-op; an unknown id MUST fail the call. Merging two statements with different systems MUST fail without writing, with an error naming both systems.

#### Scenario: Duplicate wording collapsed
- **WHEN** statements S1 and S2 say the same thing, S1 has an incoming `contains` link from P, and an admin merges S1 into S2
- **THEN** S1 no longer exists, P `contains` S2, and S2's text is unchanged
- **AND** the response is `{into_id, mentions_moved: 0, outgoing_links_moved, incoming_links_moved}` counting only links that survived

#### Scenario: Link between the pair
- **WHEN** S1 has a link to S2 and S1 is merged into S2
- **THEN** that link is dropped rather than becoming a self-loop

#### Scenario: Same wording in two systems
- **WHEN** "A webhook delivery is retried" belongs to our product and the same text belongs to Paylark, and an admin merges one into the other
- **THEN** the merge fails naming both systems and both statements remain

### Requirement: Merging entities
`merge_entities(from_entity_id, into_entity_id)` SHALL move every name, entity link, media attachment, generated-document anchor and statement system reference of the source to the target and delete the source, returning `{into_entity_id, names_moved, documents_unanchored}`. Entity links that would become self-loops or duplicates MUST be dropped. Merging an entity into itself is a no-op; an unknown id MUST fail the call.

#### Scenario: Two entities for one concept
- **WHEN** "Invoice" and "Bill" are separate entities and an admin merges "Bill" into "Invoice"
- **THEN** "Bill" becomes a name of the "Invoice" entity
- **AND** statements that mentioned "Bill" now mention the "Invoice" entity

#### Scenario: Anchor collision
- **WHEN** both entities anchor a generated document of the same guideline set and type
- **THEN** the source's document keeps its body but loses its anchor
- **AND** `documents_unanchored` counts it

#### Scenario: Merging a system
- **WHEN** "Paylark Dashboard" is the system of three statements and an admin merges it into "Paylark"
- **THEN** those three statements belong to Paylark

### Requirement: Deleting entities
`delete_entity(id)` SHALL permanently delete an entity with all its names, the mentions of those names and the entity links from or to it; anchored generated documents MUST keep their body and history but lose the anchor. It SHALL return `{deleted: true, names_removed, mentions_removed, outgoing_entity_links_removed, incoming_entity_links_removed, documents_unanchored}` and fail on an unknown id. Deleting an entity that is any statement's system MUST fail without writing, with an error giving how many statements use it.

#### Scenario: Retired concept
- **WHEN** an admin deletes an entity with the name "Legacy export" (and its plural) and one outgoing entity link
- **THEN** the response reports `names_removed: 2` and `outgoing_entity_links_removed: 1`

#### Scenario: Entity still used as a system
- **WHEN** Paylark is the system of five statements and an admin deletes it
- **THEN** the call fails saying five statements use it as their system and nothing is deleted
