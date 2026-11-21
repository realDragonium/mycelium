## ADDED Requirements

### Requirement: Statements per system
`GET /api/knowledge-health` SHALL return `systems`: one entry `{entity_id, name, statements}` per entity that is a statement's system, plus `main_statements` counting statements without a system, computed from current data on every request.

#### Scenario: Product with one integration
- **WHEN** 120 statements have no system and 30 belong to Paylark
- **THEN** `main_statements` is 120 and `systems` holds one entry for Paylark with `statements: 30`

### Requirement: Curation claims by system
`claim_curation_work` SHALL accept `system` (an entity id, an exact name, or `"main"`) for the statement-backed kinds `isolated`, `unnamed`, `rephrase` and `duplicate`, offering only items whose statements have that system; for `duplicate`, only statement pairs whose statements both have it, chosen before the claim's candidate bound applies so other systems' pairs cannot crowd them out. A `system` that does not resolve MUST fail the call. Passing `system` with any other kind MUST fail the call.

#### Scenario: Agent in the integration's repository
- **WHEN** a drafter calls `claim_curation_work("isolated", system: "Paylark")`
- **THEN** only isolated statements belonging to Paylark are leased

#### Scenario: Concept work
- **WHEN** a drafter calls `claim_curation_work("undescribed", system: "Paylark")`
- **THEN** the call fails saying `system` applies only to statement work

## MODIFIED Requirements

### Requirement: Statement duplicate audit
The system SHALL provide `find_duplicates(threshold?, limit=50)` for readers, over HTTP only, returning near-duplicate statement pairs `{a_id, a_text, b_id, b_text, score}` at or above the threshold (default from the embedding model, 0.92 for `nomic-embed-text` and 0.88 for `text-embedding-3-small`), each pair once, by score descending. Two statements with different systems MUST NOT be paired, and a statement side of a `duplicate` curation item SHALL carry its `system` when it has one.

#### Scenario: Two wordings of one claim
- **WHEN** two statements' vectors score 0.95 with the default threshold
- **THEN** the pair is reported once

#### Scenario: Same words in two systems
- **WHEN** "A webhook delivery is retried" belongs to our product and the same text belongs to Paylark
- **THEN** the pair is not reported and no `duplicate` item offers it

### Requirement: Health criteria
The system SHALL count and list a statement as `isolated` when no statement link leads from or to it and no link's `when` condition names it, as `unmentioned` when its text mentions no concept name or alias, and as `unlabelled` when it has no audience label; and a concept as `undescribed` when its description is empty or whitespace, and as `unused` when no statement mentions any of its names and no statement has it as its system.

#### Scenario: Statement used only as a condition
- **WHEN** a statement has no links of its own but is the `when` condition of another link
- **THEN** it is not counted as isolated

#### Scenario: Concept with a blank description
- **WHEN** a concept's description is three spaces
- **THEN** it is counted as undescribed

#### Scenario: Concept used only as a system
- **WHEN** no statement mentions Paylark but two statements have it as their system
- **THEN** Paylark is not counted as unused
