## MODIFIED Requirements

### Requirement: Agent draft review briefs
The system SHALL brief a claimed `draft_review` task, at claim time, with the internal reviewer's system prompt and context for each part of the draft, the draft's previous review with its suggested corrections, the review mode and `auto_apply`, and SHALL take `{parts: [assessment, ...]}`, one assessment per part in the internal reviewer's shape. A draft the server refuses without a review SHALL get no brief and a rejection as Final refusals under an external reviewer describes.

#### Scenario: Re-reviewing held corrections
- **WHEN** an agent claims the review of a draft whose previous review was held with corrections
- **THEN** the brief's `earlier_review` carries that review and its corrections

#### Scenario: Refused draft with final refusals on
- **WHEN** `reject_refused` is on and an agent claims the review of a draft holding an operation review does not support
- **THEN** the claim returns no task and the draft is rejected by that agent

### Requirement: Grant reviewer independence
The system MUST never offer an `audience_review` task to the agent that labelled its grants or kept grants, or, for edited curator labels, to the curator who set the label, SHALL say so in the claim's `note` when it withheld one, and SHALL skip any item the submitting agent labelled.

#### Scenario: A labeller claims the review of its grants
- **WHEN** the only waiting grants were labelled by agent A and A claims `audience_review`
- **THEN** A gets no task and a `note` saying the waiting task holds grants it labelled

#### Scenario: Curator claims the review of their label
- **WHEN** the only edited curator label was set by agent A and A claims `audience_review`
- **THEN** A gets no task

## ADDED Requirements

### Requirement: Label review batches
The system SHALL make `audience_review` batches of one subject each (waiting grants, edited curator labels or kept grants) at the labelling batch size, from one labeller's or curator's items, carrying the subject in the task state, and SHALL take a decision per statement (`statement_id`, `decision` `confirm` or `reject`, `reason`) for label and kept-grant batches. Task state saved before subjects existed SHALL read as a waiting-grant batch.

#### Scenario: Edited curator label batch
- **WHEN** `ai_label_decisions` is on, labelling is External agent and another agent claims `audience_review`
- **THEN** the task names the edited curator labels it holds and takes one decision per statement
