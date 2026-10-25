## ADDED Requirements

### Requirement: Agent plans over several calls
The system SHALL queue each further call of a plan allowed more than one planning call as its own `documentation_planning` task for the same plan, which any agent may claim, briefed with the next batch of uncovered statements and the items earlier calls kept as `already_proposed`; the submission that leaves no statement unoffered, or uses the last call, finishes the plan with the items of every call.

#### Scenario: Second planning task
- **WHEN** an agent's proposal is kept for the first of two allowed calls while uncovered statements remain unoffered
- **THEN** the task closes saying another task places the rest, and a new `documentation_planning` task for the same plan waits, listing the kept items as `already_proposed`
