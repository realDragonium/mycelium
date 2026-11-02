## ADDED Requirements

### Requirement: Opening a draft over MCP
The system SHALL advertise `open_draft(title?)` to drafters, writers and admins, returning the caller's open draft as its id, status `open`, title, operation count and whether this call created it. A reader SHALL be refused. The caller stages writes on the draft by passing its id as `draft_id` and submits it with `submit_draft`.

#### Scenario: A writer proposes an edit over MCP
- **WHEN** a writer calls `open_draft`, then edits the text of "An invoice export link is valid for 24 hours." with that `draft_id`, then calls `submit_draft` with it
- **THEN** the edit is queued on the writer's draft, the live statement is unchanged, and the draft is submitted with one operation

#### Scenario: A reader
- **WHEN** a reader calls `open_draft`
- **THEN** the call is refused

### Requirement: One open draft per caller
The system SHALL return the caller's open draft from `open_draft` when one is open under the key a drafter's writes use, ignoring `title`, and SHALL otherwise create one owned by the caller. A draft the caller opened SHALL stay open until they submit or withdraw it, even while it holds no operations.

#### Scenario: Opening again while a draft is open
- **WHEN** a writer calls `open_draft` again before submitting
- **THEN** the same draft is returned, not created, with its operation count

#### Scenario: Another person's draft
- **WHEN** a second writer calls `open_draft` while the first writer's draft is open
- **THEN** the second writer gets a new draft of their own

#### Scenario: Discarding an unused draft
- **WHEN** the writer withdraws the draft they opened before staging anything
- **THEN** the draft is withdrawn and no longer counts among the drafts open with their authors
