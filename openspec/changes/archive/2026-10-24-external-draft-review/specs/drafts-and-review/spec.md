## MODIFIED Requirements

### Requirement: Saving review settings
The system SHALL accept `PATCH /api/draft-review/settings` only from an admin, with the review controls and model selection, optional `external_agent` (omitted keeps the saved value), `revision` and `model_revision`, saving them atomically and answering 409 for a stale revision. A mode other than `off` SHALL require a model ID, provider credentials and an active real writer or admin as reviewer, unless `external_agent` is on. Saving SHALL NOT start any review.

#### Scenario: Concurrent admin saves
- **WHEN** two admins save settings from the same loaded revision
- **THEN** the first save succeeds and the second returns 409

#### Scenario: Enabling review without a reviewer
- **WHEN** an admin saves mode `review-only` with no reviewer selected and `external_agent` off
- **THEN** the save is refused naming the missing independent reviewer

#### Scenario: Enabling review with an external agent
- **WHEN** an admin saves mode `review-and-apply` with `external_agent: true`, no model, no reviewer and no provider credentials
- **THEN** the save succeeds and the settings read `ready: true`

#### Scenario: Choosing corrected approvals
- **WHEN** an admin saves `auto_apply: with_corrections`
- **THEN** later `changes_suggested` reviews in `review-and-apply` make their corrections and apply the draft

### Requirement: Interrupted attempts
The system SHALL, at startup, mark attempts left `running` as `failed` so the sweep retries them, except attempts an unfinished agent task still serves, and SHALL restore the actual outcome (`applied`, `rejected` or `needs_human`) from durable review and application receipts for attempts that recorded one before the interruption. No startup step SHALL start model work or replay an uncommitted application.

#### Scenario: Restart after the application committed
- **WHEN** the process stops after a reviewed application committed but before the attempt was finalized
- **THEN** after restart the attempt reads `application: applied` and is not retried

#### Scenario: Restart while an agent has not reviewed yet
- **WHEN** the process restarts while a `draft_review` task waits for an agent
- **THEN** the attempt is still `running` and the task can be claimed

### Requirement: Backlog membership
The system SHALL count a submitted draft as backlog when its latest attempt is missing, failed without a recorded review, a stale or other-mode advisory assessment, any unapplied assessment without a recorded review in `review-and-apply`, a question whose draft changed since, or held corrections whose draft changed since or, while an external agent reviews, at all. Running and paused attempts SHALL NOT count. With an external agent the backlog job queues a task per draft.

#### Scenario: Advisory assessment after switching mode
- **WHEN** the mode changes from `review-only` to `review-and-apply`
- **THEN** drafts holding only a `review-only` assessment appear in the backlog

#### Scenario: Held corrections
- **WHEN** a draft's latest attempt is `held`, the draft has not changed since and draft review runs on a model
- **THEN** the draft is not in the backlog

#### Scenario: Held corrections with an external agent
- **WHEN** draft review is set to External agent and a draft's latest attempt is `held`
- **THEN** the draft is in the backlog, and the backlog job queues a `draft_review` task for it whose brief carries the held review
