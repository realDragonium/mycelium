## ADDED Requirements

### Requirement: Restart limit
The system SHALL count, for each documentation run, the server starts that found it started but unfinished. A run cut off more often than `restart_retries` (document generation limits, default 2) SHALL fail with an error saying how many restarts interrupted it, instead of being admitted again.

#### Scenario: Interrupted too often
- **WHEN** the server starts and finds a started run already cut off by restarts more often than the limit
- **THEN** the run reports `status` `failed` with an error naming the restarts

### Requirement: Dismissals across keys and titles
The system SHALL treat a dismissed or given-up out-of-date document and a plan update of the same document revision as the same proposal. It SHALL drop a proposed create without a concept anchor as "dismissed before" or "given up before" when a dismissed or given-up create of the same document type, also without an anchor, drew on at least half of its statements.

#### Scenario: Dismissed out-of-date document
- **WHEN** a writer dismisses an out-of-date document and a later plan proposes an update of the same revision
- **THEN** the update is dropped as "dismissed before"

#### Scenario: Reworded proposal
- **WHEN** a later plan proposes a dismissed unanchored create again under another title, drawing on the same statements
- **THEN** it is dropped as "dismissed before"
