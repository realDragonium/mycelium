## MODIFIED Requirements

### Requirement: Curation leases
The system SHALL extend the lease on every item of `kind` the caller still holds whenever the caller claims that kind again, listing them in `renewed`, with `limit=0` only renewing; an item whose lease has expired returns to the pool and counts as a skip of that item.

#### Scenario: Lease expires
- **WHEN** 30 minutes pass after a claim without renewal
- **THEN** the item is offered to the next claimant

### Requirement: Stopped automations
The system SHALL list on Knowledge health, with `GET /api/knowledge-health` as `stopped`, each item an automation stopped retrying, with its kind (`audience_review`, `connect`, `gap_follow_up`, `draft_review`, `curation`, `mention`, `embedding`), item, reason, failures and time, and SHALL let an admin retry one with `POST /api/knowledge-health/stopped/retry`, which offers it again with a fresh count. A stop SHALL be forgotten when the item's inputs change.

#### Scenario: Writer retries
- **WHEN** a writer posts a retry
- **THEN** the request is refused and the item stays stopped

## ADDED Requirements

### Requirement: Skip limit
The system SHALL count each `skipped` release of a curation item and each lease of it that ran out. Once an item was skipped more often than `skip_retries` (Connecting statements limits, default 2), it SHALL be listed as stopped and not offered until its text changes or an admin retries it. Any other release SHALL forget the count.

#### Scenario: Skipped past the limit
- **WHEN** `skip_retries` is 1, an item was skipped once and a later claim of it runs out
- **THEN** the item is not offered and is listed as stopped until its text changes
