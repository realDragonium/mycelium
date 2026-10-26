## ADDED Requirements

### Requirement: Withdrawing a draft over MCP
The system SHALL advertise `withdraw_draft(draft_id)` to drafters and above, withdrawing an open or submitted draft for its creator or a real writer or admin, as `POST /api/drafts/{id}/withdraw` does.

#### Scenario: Someone else's draft
- **WHEN** a drafter withdraws a draft another drafter created
- **THEN** the call is refused and the draft is unchanged

### Requirement: Answering the reviewer over MCP
The system SHALL advertise `answer_draft_review(draft_id, run_id, answer)` to real writers and admins, answering the questions review run `run_id` asked and reviewing the draft again with the answer, as `POST /api/drafts/{id}/review/answer` does.

#### Scenario: Drafter answers
- **WHEN** a drafter calls `answer_draft_review`
- **THEN** the call is refused for want of a real writer role

### Requirement: Reviewing the backlog over MCP
The system SHALL advertise `manage_draft_review_backlog(action)` to real admins only, where `status` lists the submitted drafts the reviewer has not reached with the last backlog job, and `start`, `pause` and `resume` control that job as Settings → Draft review does.

#### Scenario: Pausing the backlog
- **WHEN** an admin agent pauses a running backlog review
- **THEN** the review stops after the draft under review

## MODIFIED Requirements

### Requirement: Starting a review on request
The system SHALL let an identified real writer or admin start or fetch a review through `request_draft_review(draft_id, rerun)` (advertised over MCP and on HTTP as `POST /request-draft-review`) and `POST /api/drafts/{id}/review` (always a rerun, returning `{review: ...}`). Without `rerun` the latest attempt SHALL be returned; with it a new attempt SHALL start, unless one is running, which SHALL be returned instead.

#### Scenario: Rerun while running
- **WHEN** a curator requests a rerun while an attempt for the draft is running
- **THEN** the running attempt is returned and no second attempt starts

#### Scenario: Reviewing an open draft
- **WHEN** a curator requests review of an `open` draft
- **THEN** the request is refused saying only submitted drafts can be internally reviewed
