## MODIFIED Requirements

### Requirement: Task kinds
The system SHALL queue tasks of kind `documentation`, `document_review`, `documentation_planning`, `audience_labelling`, `ingest`, `connect`, `alias_discovery` and `draft_review`. Labelling batches are made when an agent claims, from the statements due then, at the labelling batch size, and a statement in an open batch is not put in another.

#### Scenario: Labelling batch at claim time
- **WHEN** audience labelling is set to External agent and an agent claims `audience_labelling` work
- **THEN** a batch of due statements no open task holds is queued and leased to that agent

### Requirement: Reviewer independence
The system MUST never offer a `document_review` task to the principal that submitted the document it reviews, nor a `draft_review` task to the principal that created the draft. A claim that withheld such tasks SHALL say so in its `note`, and a submission by the draft's creator SHALL be refused naming the reason and the task returned to the queue.

#### Scenario: Another agent reviews
- **WHEN** documentation review is set to `agent` and writer A's document passes the emit gate
- **THEN** A's submission returns `in_review`, A is not offered the review, and writer B's passing review saves the document

#### Scenario: A drafter claims its own draft's review
- **WHEN** the only waiting `draft_review` task is for a draft writer A created and A claims `draft_review`
- **THEN** A gets no task and a `note` saying the waiting task is its own draft

## ADDED Requirements

### Requirement: External agent for every model action
The system SHALL let an admin set any model action to External agent (`external_agent: true` on `PATCH /api/model-settings/{action}`, or on `PATCH /api/draft-review/settings` for draft review), after which its model work is queued as agent tasks, or for `ask` done by the caller's own agent, instead of calling a provider. `GET /api/model-settings` reports `external_agent`, `agent_review` and `agent_supported` per action.

#### Scenario: Documentation set to External agent
- **WHEN** documentation is set to External agent and a writer requests a document without a `provider`
- **THEN** the run is created with provider `agent` and `status` `waiting_for_agent`, and no model is called to write it

#### Scenario: Draft review set to External agent
- **WHEN** draft review is set to External agent and a draft is submitted
- **THEN** its review run has provider `agent`, stays `running`, and a `draft_review` task waits; no model is called

### Requirement: Agent draft review briefs
The system SHALL brief a claimed `draft_review` task, at claim time, with the internal reviewer's system prompt and context for each part of the draft, the draft's previous review with its suggested corrections, the review mode and `auto_apply`, and SHALL take `{parts: [assessment, ...]}`, one assessment per part in the internal reviewer's shape. A draft the server refuses without a review (unsupported operations, newer knowledge, too large) SHALL get an advisory rejection and no brief.

#### Scenario: Re-reviewing held corrections
- **WHEN** an agent claims the review of a draft whose previous review was held with corrections
- **THEN** the brief's `earlier_review` carries that review and its corrections

### Requirement: Agent draft review verdicts
The system SHALL validate a `draft_review` submission as the internal reviewer's assessment and corrections, refusing it with findings up to 2 times, and SHALL then act on it exactly as on the internal reviewer's assessment, with the claiming agent's principal as the reviewer.

#### Scenario: Approve with corrections under review-and-apply
- **WHEN** draft review is External agent in `review-and-apply` with `auto_apply: with_corrections` and an agent submits `changes_suggested` with a valid correction
- **THEN** the correction is made, the draft is applied, and the recorded review names the agent's principal

#### Scenario: Inconsistent verdict
- **WHEN** an agent submits `changes_suggested` with no corrections
- **THEN** the submission is `refused` with a finding and the run keeps waiting

#### Scenario: Review-only
- **WHEN** the mode is `review-only` and an agent submits `good`
- **THEN** the draft stays submitted with an advisory assessment and no review record

### Requirement: Embeddings keep their model
The system SHALL never use agents for embeddings. Ask MUST NOT be queued as an agent task.

#### Scenario: Ask set to External agent
- **WHEN** Ask is set to External agent and a caller asks a question
- **THEN** no agent task is queued

## REMOVED Requirements

### Requirement: External agent for an action
**Reason**: Every model action now takes External agent, so no action refuses it.
**Migration**: See "External agent for every model action".

### Requirement: Draft review and embeddings keep their model
**Reason**: Draft review now takes External agent through the `draft_review` task kind.
**Migration**: See "Agent draft review verdicts" and "Embeddings keep their model".
