## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Mention candidates
`get_mention_candidates(entity_id, after=0, limit=50)` SHALL scan at most 2,000 statements after the `after` cursor and return `{matches, next_after, has_more, scanned}`, each match `{statement_id, text, kind, names, match}` with `match` one of `derived`, `approved` or `possible`. It MUST reject a negative `after`, a `limit` outside 1..200 and an unknown entity, and MUST NOT write.

#### Scenario: Empty page with more to scan
- **WHEN** the first 2,000 statements after the cursor contain no match for the entity
- **THEN** the page has no matches, `has_more: true` and a `next_after` to continue from

#### Scenario: HTTP access
- **WHEN** a signed-in reader calls `GET /api/mention-candidates?entity_id=...`
- **THEN** the same page is returned as the MCP tool returns
