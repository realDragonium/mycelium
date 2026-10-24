## MODIFIED Requirements

### Requirement: Answering the reviewer
The system SHALL accept `POST /api/drafts/{id}/review/answer` with `run_id` and an `answer` of 1 to 6,000 characters from a real writer or admin or a curation agent's `answered` release, only when that run is the draft's latest, has `application: needs_human` and the draft has not changed since; it SHALL store the answer with the answerer's id and the questions it answers, carry all earlier answers to every later attempt, start a new attempt and return `{review: ...}`.

#### Scenario: Answer after the draft changed
- **WHEN** a curator answers a question after the draft's evidence was changed
- **THEN** the answer is refused saying the draft changed after the reviewer asked

#### Scenario: Answer to an older run
- **WHEN** a curator answers with a `run_id` that is no longer the draft's latest attempt
- **THEN** the answer is refused asking to reload

#### Scenario: Agent's answer reaches the reviewer
- **WHEN** a curation agent answers a reviewer question with code evidence
- **THEN** the next attempt's context carries the answer, the agent's id and its evidence

### Requirement: Alias suggestion operations need individual decisions
The system SHALL NOT let draft operation tools or routes revise or remove an `alias_suggestion` operation, SHALL refuse to approve, reject, withdraw or apply a draft while any of its alias suggestions is still pending, and SHALL skip alias suggestions when replaying a draft. A pending suggestion SHALL be decided individually, by a real writer or administrator or, while `alias_decisions` is on, by the draft reviewer.

#### Scenario: Rejecting a draft with a pending alias suggestion
- **WHEN** a curator rejects a draft holding a pending alias suggestion
- **THEN** the rejection is refused with a message to review alias suggestions individually first

### Requirement: Review settings
The system SHALL keep the review mode (`off`, `review-only`, `review-and-apply`), the automatic-application policy (`auto_apply`: `clean` or `with_corrections`), reviewer account, application gate (`application_enabled`), provider (`claude` or `openai`), model ID and reasoning effort in saved instance settings, defaulting to mode `off`, `auto_apply` `clean` and the gate off, and SHALL disable review rather than fall back to environment values when saved settings are unreadable.

#### Scenario: Fresh instance
- **WHEN** an admin opens the draft review settings on a new instance
- **THEN** the mode is `off`, `auto_apply` is `clean`, `application_enabled` is `false` and saving `off` with no model or reviewer is allowed

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

## ADDED Requirements

### Requirement: Alias decision setting
The system SHALL keep whether the reviewer decides alias suggestions (`alias_decisions`) in the saved review controls, default off, read saved controls without it as off, and count a draft of only alias suggestions as backlog only while it is on.

#### Scenario: Upgraded instance
- **WHEN** an instance saved its review controls before `alias_decisions` existed
- **THEN** the controls load with `alias_decisions` off

#### Scenario: Alias-only draft
- **WHEN** a submitted draft holds only alias suggestions and `alias_decisions` is off
- **THEN** the draft is not in the backlog

### Requirement: Reviewer alias decisions
While `alias_decisions` is on and review is not `off`, the system SHALL review drafts of only alias suggestions on submission. Each assessment SHALL carry `alias_decisions`: one per pending `alias_suggestion` operation of its part unless the label is `needs_context`, each `accept` or `reject` with a `quote` found in the suggestion's source text and a `reason`. Breaking these rules SHALL fail a model attempt or refuse an agent's submission with findings.

#### Scenario: Quote not in the source
- **WHEN** an agent reviewer decides a suggestion with a quote its source text does not contain
- **THEN** the submission is refused with a finding and the suggestion stays pending

#### Scenario: Setting off
- **WHEN** `alias_decisions` is off and a draft of only alias suggestions is submitted
- **THEN** no review starts and each suggestion waits for a person

### Requirement: Applying reviewer alias decisions
In `review-and-apply` with the application gate on, the system SHALL make each reviewer alias decision through the suggestion's accept or reject path as the reviewer, never the draft's creator, recording the quote and reason, and SHALL leave pending, for a person, a suggestion whose names or source changed since. In `review-only` the decisions SHALL stay advisory.

#### Scenario: Reviewer accepts an alias
- **WHEN** review is `review-and-apply`, `alias_decisions` is on and the reviewer accepts a suggestion quoting its source
- **THEN** the alias is added, the decision records the reviewer, quote and reason, and a draft of only that suggestion closes as approved

#### Scenario: Review only
- **WHEN** review is `review-only` and the reviewer decides a suggestion
- **THEN** the suggestion stays pending for a person
