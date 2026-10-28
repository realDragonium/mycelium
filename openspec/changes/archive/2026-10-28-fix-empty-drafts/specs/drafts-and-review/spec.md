## ADDED Requirements

### Requirement: Empty server drafts are withdrawn
The system SHALL, on each start, withdraw every open draft that has no operations, no creator and no repository source, recording `upgrade` as the one who withdrew it. Open drafts with operations, and drafts a person, agent or repository created, SHALL stay as they are, even when empty.

#### Scenario: An automation's empty draft
- **WHEN** the server starts with an open draft that has no operations and no creator
- **THEN** the draft is `withdrawn` and its `decided_by` is `upgrade`

#### Scenario: A drafter's empty draft
- **WHEN** the server starts with a drafter's open draft that has no operations
- **THEN** the draft stays `open`
