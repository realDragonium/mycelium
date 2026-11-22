## MODIFIED Requirements

### Requirement: Independent reviewer account
The system SHALL act for the configured reviewer account, resolved independently of the submitting caller, and SHALL fail the attempt when that account is not an active real writer or admin. The reviewer account MAY be the draft's creator.

#### Scenario: Reviewer created the draft
- **WHEN** the configured reviewer account is the one that created the submitted draft
- **THEN** the draft is reviewed as any other

### Requirement: Applying reviewer alias decisions
In `review-and-apply` with the application gate on, the system SHALL make each reviewer alias decision through the suggestion's accept or reject path as the reviewer, recording the quote and reason, and SHALL settle a suggestion that changed since as Stale alias suggestions under review describes. In `review-only` the decisions SHALL stay advisory.

#### Scenario: Reviewer accepts an alias
- **WHEN** review is `review-and-apply`, `alias_decisions` is on and the reviewer accepts a suggestion quoting its source
- **THEN** the alias is added, the decision records the reviewer, quote and reason, and a draft of only that suggestion closes as approved

#### Scenario: Review only
- **WHEN** review is `review-only` and the reviewer decides a suggestion
- **THEN** the suggestion stays pending for a person

### Requirement: Agent decision refusals
The system SHALL refuse `review_draft` and `reopen_draft` from a caller that is not a real writer or admin, SHALL refuse `review_draft` when the draft's revision differs from `expected_revision`, and SHALL refuse an approval when a record the draft changes was rewritten after the draft was written, as the stale draft refusal defines it.

#### Scenario: Own draft
- **WHEN** a writer agent calls `review_draft` with `approve` on a submitted draft it created
- **THEN** the draft is applied and its decision names the agent

#### Scenario: Statement edited after the draft
- **WHEN** a statement is edited directly after a draft that patches it was written, and an agent approves that draft
- **THEN** the approval is refused naming the newer change and nothing is applied

### Requirement: Reopening a rejected draft
The system SHALL let a real writer or admin return a `rejected` draft to `submitted`, through `reopen_draft(draft_id, reason)` over MCP or `POST /api/drafts/{id}/reopen` with a `reason`, clearing its decision. Reopening SHALL be refused for a draft that is not `rejected` and for one whose changed records were rewritten after it was written. A reopened draft SHALL NOT be reviewed automatically again on that account.

#### Scenario: Reconsidering a reviewer rejection
- **WHEN** an agent reopens a draft the automatic reviewer rejected and then approves it
- **THEN** the draft is applied and its decisions read rejected, reopened, approved

#### Scenario: Withdrawn draft
- **WHEN** a writer tries to reopen a withdrawn draft
- **THEN** the request is refused

### Requirement: Saving review settings
The system SHALL accept `PATCH /api/draft-review/settings` only from an admin, with the review controls and model selection, optional `external_agent` (omitted keeps the saved value), `revision` and `model_revision`, saving them atomically and answering 409 for a stale revision. A mode other than `off` SHALL require a model ID, provider credentials and an active real writer or admin as reviewer, unless `external_agent` is on. Saving SHALL NOT start any review.

#### Scenario: Concurrent admin saves
- **WHEN** two admins save settings from the same loaded revision
- **THEN** the first save succeeds and the second returns 409

#### Scenario: Enabling review without a reviewer
- **WHEN** an admin saves mode `review-only` with no reviewer selected and `external_agent` off
- **THEN** the save is refused naming the missing reviewer

#### Scenario: Enabling review with an external agent
- **WHEN** an admin saves mode `review-and-apply` with `external_agent: true`, no model, no reviewer and no provider credentials
- **THEN** the save succeeds and the settings read `ready: true`

#### Scenario: Choosing corrected approvals
- **WHEN** an admin saves `auto_apply: with_corrections`
- **THEN** later `changes_suggested` reviews in `review-and-apply` make their corrections and apply the draft
