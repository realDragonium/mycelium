## ADDED Requirements

### Requirement: AI review of waiting grants
While `ai_grant_review` (default off) and `confirm_external_grants` are both on, the system SHALL have a second AI confirm or reject each waiting external grant with a reason: the audience-labelling model in the labelling pass, retrying a grant it leaves undecided at most three times, or, with audience labelling set to External agent, `audience_review` agent tasks.

#### Scenario: Setting off
- **WHEN** `ai_grant_review` is off and grants are waiting
- **THEN** no review task is queued and no review model call is made

#### Scenario: Server model reviews
- **WHEN** `ai_grant_review` is on and audience labelling runs on a server model
- **THEN** the labelling pass decides a batch of waiting grants with that model

### Requirement: Applying an AI grant decision
An AI grant decision SHALL go through the curator's decision path, recording the reviewer (the agent, or `model:<model>`) and its reason, and SHALL skip a grant whose statement text or label changed since it was offered.

#### Scenario: Second agent rejects a grant
- **WHEN** agent B submits a rejection with a reason for a grant agent A labelled
- **THEN** the label becomes a curator label without that audience, recording B and the reason

#### Scenario: Label changed after queueing
- **WHEN** a grant's label changed after its review task was queued and the reviewer confirms it
- **THEN** the grant stays waiting
