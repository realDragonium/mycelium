## ADDED Requirements

### Requirement: AI decisions on edited curator labels and kept grants
While `ai_label_decisions` is on (Audience labelling settings, default off, read as off from settings saved without it), the grant reviewer SHALL decide, besides waiting grants, each curator label whose statement text changed (`confirm` keeps it for the new text as the reviewer; `reject` hands it back to the AI labeller) and each statement that kept a confirmed grant after an edit (`confirm` confirms the kept grants with its reason; `reject` narrows them with a reason quoting the reviewer).

#### Scenario: Setting off
- **WHEN** `ai_label_decisions` is off and a curator-labelled statement is edited
- **THEN** the label waits for a curator and no review is queued for it

#### Scenario: Model keeps an edited curator label
- **WHEN** `ai_label_decisions` is on, labelling runs on a server model and the model confirms an edited curator label
- **THEN** the label's `text_changed_at` is cleared and the label records `model:<model>`

#### Scenario: Agent narrows a kept grant
- **WHEN** an agent rejects a statement whose edit kept a confirmed `external-technical` grant
- **THEN** external audiences no longer see it, the label is a curator label whose reason names the agent, and the statement leaves the spot-check list

### Requirement: Running AI label decisions
Each label or kept-grant decision SHALL carry a reason of at most 500 characters and go through a curator's path. The audience-labelling model SHALL decide them in the labelling pass, retrying an item it leaves out at most three times for the same text; with audience labelling set to External agent they SHALL be `audience_review` tasks. An item whose statement text or label changed since it was offered SHALL be skipped.

#### Scenario: Statement edited after it was offered
- **WHEN** an agent confirms an edited curator label whose statement was edited again after the task was claimed
- **THEN** the label still waits, flagged as text changed
