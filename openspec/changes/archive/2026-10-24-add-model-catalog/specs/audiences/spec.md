## MODIFIED Requirements

### Requirement: Labelling status survives restarts
`GET /api/audiences/labelling` SHALL report statement, AI-label, curator-label, unlabelled, queued and failed counts, the last error, the labelling tokens the usage ledger recorded, `automatic`, `confirm_external_grants`, and the labelling provider and model. While a queued statement has attempts left it SHALL include `backfill` (`started_at`, `queued`, `labelled`, `tokens`), counted from the oldest waiting statement's queueing and read from the queue, so it survives restarts.

#### Scenario: Restart mid-backfill
- **WHEN** the server restarts while a backfill has 40 statements left
- **THEN** `GET /api/audiences/labelling` still shows the backfill with its labelled count and tokens
