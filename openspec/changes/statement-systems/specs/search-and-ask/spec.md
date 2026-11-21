## ADDED Requirements

### Requirement: Statements show their system
An unscoped read SHALL return a statement's system as `system: {entity_id, name}`, where `name` is the entity's preferred name, on `get_statements` records, `search_statements` hits and `list_statements` and `grep_statements` rows, and SHALL leave the field out for a statement without one. Ask reads statements through these tools and sees the same field.

#### Scenario: A step in another platform
- **WHEN** a reader fetches a statement whose system is Paylark
- **THEN** the record carries `system: {entity_id, name: "Paylark"}`

#### Scenario: A statement about our product
- **WHEN** a reader fetches a statement without a system
- **THEN** the record has no `system` field

### Requirement: Filtering by system
`search_statements`, `list_statements` and `grep_statements` SHALL accept `system` as an entity id, an exact name, or `"main"`, keeping only direct hits or rows with that system, or with no system for `"main"`. Linked context that search expansion adds MAY come from any system. A `system` that does not resolve SHALL match nothing: `list_statements` and `grep_statements` return no statements and the unresolved value in `missing`, and `search_statements` returns no hits.

#### Scenario: Only the payment platform
- **WHEN** a reader lists statements with `system: "Paylark"`
- **THEN** every row belongs to Paylark and `total` counts all of them

#### Scenario: Only our product
- **WHEN** a reader searches with `system: "main"`
- **THEN** every direct hit has no system

#### Scenario: Misspelt system
- **WHEN** a reader greps with `system: "Paylrk"` and no entity has that name
- **THEN** the response is `total: 0`, no statements and `missing: ["Paylrk"]`
