## ADDED Requirements

### Requirement: Delivery names the revision over MCP
`deliver_document(document_id, destination, expected_revision)` SHALL require `expected_revision`, a revision number from 1, as the HTTP delivery route does, so an agent publishes the revision it read.

#### Scenario: Revision left out
- **WHEN** an agent calls `deliver_document` without `expected_revision`
- **THEN** the call is refused before anything is published

### Requirement: Documentation workspace over MCP
The system SHALL advertise to readers `list_documentation(kind)`, listing `documents`, `runs`, `destinations`, the `options` a run may use or the `maintenance` feed, and `get_document_history(document_id, revision?, diff?)`, listing a document's revisions, reading one, or diffing it against the revision it was revised from.

#### Scenario: Diff of a revision
- **WHEN** a reader agent asks for revision 3 of a document with `diff`
- **THEN** it gets the lines added and removed against the revision 3 was revised from

### Requirement: Documentation plan decisions over MCP
The system SHALL advertise `decide_documentation_plan(request)` to real writers and admins, approving plan items (each starting its run, an item that cannot start reporting why), dismissing an item, dismissing or restoring an uncovered statement and dismissing an out-of-date document, recorded as the caller's. `retry_documentation(run_id? | item_id?, with_review_notes?)` SHALL retry a run or a plan item's run that wrote nothing.

#### Scenario: Approving items over MCP
- **WHEN** a writer agent approves two plan items and one cannot start
- **THEN** the other starts its run and the answer gives the first one's reason

### Requirement: Document edits over MCP
The system SHALL advertise `edit_document(request)` to real writers and admins, saving a person's edit of a saved document at its revision or of an unsaved run's result, reviewed as a run.

#### Scenario: Stale edit
- **WHEN** an agent saves an edit with a revision older than the document's
- **THEN** the edit is refused as a conflict and no run starts
