## MODIFIED Requirements

### Requirement: Task kinds
The system SHALL queue tasks of kind `documentation`, `document_review`, `documentation_planning`, `plan_review`, `audience_labelling`, `ingest`, `connect`, `alias_discovery` and `draft_review`. Labelling batches are made when an agent claims, from the statements due then, at the labelling batch size, and a statement in an open batch is not put in another. Plan reviews are queued by the maintenance sweep and when an agent claims `plan_review`, for profiles whose plan review is `ai` with proposed items no review decided.

#### Scenario: Labelling batch at claim time
- **WHEN** audience labelling is set to External agent and an agent claims `audience_labelling` work
- **THEN** a batch of due statements no open task holds is queued and leased to that agent

### Requirement: Reviewer independence
The system MUST never offer a `document_review` task to the principal that submitted the document it reviews, a `draft_review` task to the principal that created the draft, nor a `plan_review` task to the agent that made the plan it reviews. A claim that withheld such tasks SHALL say so in its `note`, and a submission by the draft's creator SHALL be refused naming the reason and the task returned to the queue.

#### Scenario: Another agent reviews
- **WHEN** documentation review is set to `agent` and writer A's document passes the emit gate
- **THEN** A's submission returns `in_review`, A is not offered the review, and writer B's passing review saves the document

#### Scenario: A drafter claims its own draft's review
- **WHEN** the only waiting `draft_review` task is for a draft writer A created and A claims `draft_review`
- **THEN** A gets no task and a `note` saying the waiting task is its own draft

#### Scenario: The planner claims its plan's review
- **WHEN** agent A made a plan and the only waiting `plan_review` task reviews it
- **THEN** A gets no task and a `note` saying the waiting task is a plan it made, and agent B is given it

## ADDED Requirements

### Requirement: Agent plan reviews decide every item
The system SHALL brief a `plan_review` task with the profile's audience, templates and documents and each item still proposed with the statements it draws on that the audience may see, and SHALL keep a submission only when it decides every briefed item exactly once (`approve` or `dismiss`, with a reason); a missing, repeated or unknown item is refused with findings, and after 2 refusals the task fails and its items wait for a person.

#### Scenario: An item left out
- **WHEN** an agent submits decisions for one of a review's two items
- **THEN** the submission is refused with a finding naming the undecided item

#### Scenario: A person decided meanwhile
- **WHEN** a person dismisses an item after the review was briefed and the agent approves it
- **THEN** the item stays dismissed and no run starts for it
