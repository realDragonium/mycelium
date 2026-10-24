## ADDED Requirements

### Requirement: Connect pass failure limit
The system SHALL count a failure for each statement an automatic connect run took when the run fails or ends without looking at it, and after `connect_retries` (Connecting statements limits, default 2) further failures SHALL leave the statement out of automatic connect runs until its text changes or an admin retries it.

#### Scenario: Run keeps failing
- **WHEN** `connect_retries` is 0 and the automatic connect run on a statement fails
- **THEN** the next pass does not take that statement

#### Scenario: Statement edited
- **WHEN** a stopped statement's text changes
- **THEN** automatic connect runs may take it again

### Requirement: Rejected proposal chains
The system MUST NOT offer a gap about a draft to curation agents, the AI curation pass included, while its chain holds more than `follow_up_retries` (Connecting statements limits, default 2) rejected curation proposals, each the draft of a gap about the previous one. Such a gap SHALL stay open for a person and be listed as stopped; an admin's retry SHALL let it be offered once more.

#### Scenario: Chain past the limit
- **WHEN** `follow_up_retries` is 0 and a curation proposal for a gap about a rejected draft is rejected too
- **THEN** the gap about that proposal is not offered and is listed as stopped

#### Scenario: Admin retry
- **WHEN** an admin retries that gap
- **THEN** it is offered once, and a gap about its rejected proposal stops again

### Requirement: Stopped automations
The system SHALL list on Knowledge health, with `GET /api/knowledge-health` as `stopped`, each item an automation stopped retrying, with its kind (`audience_review`, `connect`, `gap_follow_up`), item, reason, failures and time, and SHALL let an admin retry one with `POST /api/knowledge-health/stopped/retry`, which offers it again with a fresh count. A stop SHALL be forgotten when the item's inputs change.

#### Scenario: Writer retries
- **WHEN** a writer posts a retry
- **THEN** the request is refused and the item stays stopped
