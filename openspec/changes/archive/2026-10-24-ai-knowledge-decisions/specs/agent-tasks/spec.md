## MODIFIED Requirements

### Requirement: Task kinds
The system SHALL queue tasks of kind `documentation`, `document_review`, `documentation_planning`, `plan_review`, `audience_labelling`, `audience_review`, `ingest`, `connect`, `alias_discovery` and `draft_review`. Labelling batches are made when an agent claims, from the statements due then, at the labelling batch size, and a statement in an open batch is not put in another. Plan reviews are queued for profiles whose plan review is `ai` while proposed items wait undecided.

#### Scenario: Labelling batch at claim time
- **WHEN** audience labelling is set to External agent and an agent claims `audience_labelling` work
- **THEN** a batch of due statements no open task holds is queued and leased to that agent

## ADDED Requirements

### Requirement: Grant review batches
The system SHALL make `audience_review` batches when an agent claims, from the waiting external grants then, one labeller's grants per batch at the labelling batch size, and SHALL not put a grant in an open batch into another.

#### Scenario: Grant review batch at claim time
- **WHEN** audience labelling is set to External agent, AI grant review is on and an agent claims `audience_review` work
- **THEN** a batch of waiting grants from one labeller is queued and leased to that agent

### Requirement: Grant reviewer independence
The system MUST never offer an `audience_review` task to the agent that labelled its grants, SHALL say so in the claim's `note` when it withheld one, and SHALL skip any grant the submitting agent labelled.

#### Scenario: A labeller claims the review of its grants
- **WHEN** the only waiting grants were labelled by agent A and A claims `audience_review`
- **THEN** A gets no task and a `note` saying the waiting task holds grants it labelled
