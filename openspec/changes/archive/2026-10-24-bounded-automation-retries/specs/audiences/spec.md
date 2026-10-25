## MODIFIED Requirements

### Requirement: AI review of waiting grants
While `ai_grant_review` (default off) and `confirm_external_grants` are both on, the system SHALL have a second AI confirm or reject each waiting external grant with a reason: the audience-labelling model in the labelling pass, retrying a grant it leaves undecided as Stopped audience decisions describes, or, with audience labelling set to External agent, `audience_review` agent tasks.

#### Scenario: Setting off
- **WHEN** `ai_grant_review` is off and grants are waiting
- **THEN** no review task is queued and no review model call is made

#### Scenario: Server model reviews
- **WHEN** `ai_grant_review` is on and audience labelling runs on a server model
- **THEN** the labelling pass decides a batch of waiting grants with that model

### Requirement: Running AI label decisions
Each label or kept-grant decision SHALL carry a reason of at most 500 characters and go through a curator's path. The audience-labelling model SHALL decide them in the labelling pass, retrying an item it leaves out as Stopped audience decisions describes; with audience labelling set to External agent they SHALL be `audience_review` tasks. An item whose statement text or label changed since it was offered SHALL be skipped.

#### Scenario: Statement edited after it was offered
- **WHEN** an agent confirms an edited curator label whose statement was edited again after the task was claimed
- **THEN** the label still waits, flagged as text changed

## ADDED Requirements

### Requirement: Stopped audience decisions
The system SHALL persistently count failures per waiting grant, edited curator label or kept grant and its statement text and label: a failed model call, an item the model left out or decided invalidly, or an `audience_review` task closed as failed. After `decision_retries` (audience labelling limits, default 2) further failures the item SHALL be neither sent to the model nor queued for agents until its statement or label changes or an admin retries it.

#### Scenario: Model keeps failing
- **WHEN** `decision_retries` is 0 and the model call for a waiting grant fails
- **THEN** later passes do not send that grant again and it is listed as stopped

#### Scenario: Failed agent task
- **WHEN** an `audience_review` task is closed as failed and its items reach the limit
- **THEN** the task's result says how many items stopped and no new task holds them
