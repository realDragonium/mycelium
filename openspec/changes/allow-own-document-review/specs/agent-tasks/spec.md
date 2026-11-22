## ADDED Requirements

### Requirement: Review tasks are open to the maker's account
The system SHALL offer a `document_review`, `plan_review`, `draft_review` or `audience_review` task to any real writer or admin, including the principal that submitted the document, made the plan, created the draft, or labelled the grants or set the curator label under review, and SHALL act on that principal's submission as on any other reviewer's. A claim SHALL carry no `note`.

#### Scenario: The writer's account reviews its document
- **WHEN** documentation review is set to `agent`, writer A's submission returned `in_review` and A claims `document_review`
- **THEN** A is given the review, and A's passing review saves the document

#### Scenario: The planner's account reviews its plan
- **WHEN** agent A made a plan for a profile whose plan review is `ai`, and A claims `plan_review` and decides every item
- **THEN** the approved items start their runs and each decision names A as the reviewer

#### Scenario: The creator's account reviews its draft
- **WHEN** draft review runs on an external agent in `review-and-apply` with the application gate on, writer A submitted a draft, and A claims its `draft_review` and approves it
- **THEN** the draft is approved and applied with A as the reviewer

#### Scenario: The labeller's account reviews its grants
- **WHEN** agent A labelled the waiting external grants and A claims `audience_review` and decides each
- **THEN** each confirmation and rejection is recorded with A as the one who decided

## MODIFIED Requirements

### Requirement: Grant review batches
The system SHALL make `audience_review` batches when an agent claims, from the waiting external grants then, at the labelling batch size, and SHALL not put a grant in an open batch into another.

#### Scenario: Grant review batch at claim time
- **WHEN** audience labelling is set to External agent, AI grant review is on and an agent claims `audience_review` work
- **THEN** a batch of waiting grants is queued and leased to that agent

### Requirement: Label review batches
The system SHALL make `audience_review` batches of one subject each (waiting grants, edited curator labels or kept grants) at the labelling batch size, carrying the subject in the task state, and SHALL take a decision per statement (`statement_id`, `decision` `confirm` or `reject`, `reason`) for label and kept-grant batches. Task state saved before subjects existed SHALL read as a waiting-grant batch.

#### Scenario: Edited curator label batch
- **WHEN** `ai_label_decisions` is on, labelling is External agent and an agent claims `audience_review`
- **THEN** the task names the edited curator labels it holds and takes one decision per statement

## REMOVED Requirements

### Requirement: Reviewer independence
**Reason**: The rule kept a review from the account that made the thing, but two tokens of one agent setup were never told apart, so it protected nothing and forced a second service account. See "Review tasks are open to the maker's account".
**Migration**: None. Tasks queued before this change that named an excluded account can be claimed by any writer or admin. Review in a session that did not make the thing.

### Requirement: Grant reviewer independence
**Reason**: As for "Reviewer independence": the labeller's or curator's account may now review its own grants and labels, and its decisions are applied instead of skipped.
**Migration**: None.
