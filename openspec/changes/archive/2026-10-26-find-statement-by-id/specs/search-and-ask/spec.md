## ADDED Requirements

### Requirement: Search finds a statement by its id
When a query to `search_statements` or `grep_statements` is exactly a statement id, ignoring surrounding whitespace, the system SHALL return that statement as the first hit with `matched_via: "id"` and no `score`, followed by the ordinary results without it. The id hit MUST obey the call's `kind` and mention filters and the active audience scope, so an id never reveals a statement the caller could not otherwise find. An id that names no visible statement MUST be searched as ordinary text.

#### Scenario: Pasting an id into Find
- **WHEN** a reader searches for "  stm_1a2b  " and that statement exists
- **THEN** the first hit is that statement with `matched_via: "id"` and no `score`
- **AND** it appears only once in the results

#### Scenario: Unknown id
- **WHEN** a reader searches for an id no statement carries
- **THEN** the results are those of an ordinary text search, with no id hit

#### Scenario: Id outside the audience
- **WHEN** a search runs under an external audience scope and the query is the id of a statement that audience cannot see
- **THEN** that statement is not returned
