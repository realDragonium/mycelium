## ADDED Requirements

### Requirement: Agent documents carry flows and concept links
The system SHALL list `preview_flow` among a `documentation` task's `read_tools`, served through `read_for_agent_task` inside the task's audience, and SHALL accept `flows` in a `documentation` submission, drawing, checking and storing them and resolving the body's concept links as for a server run. A refusal SHALL name every problem with the flows at once.

#### Scenario: An agent places a flow
- **WHEN** an agent previews a flow with `read_for_agent_task`, submits it in `flows` and places it in the body
- **THEN** the submission is accepted and the saved document holds the drawn flow

### Requirement: Agent results name unmatched links and reviews show flows
The `message` of an accepted or `in_review` documentation result SHALL name concept links that matched no concept. A `document_review` task's brief SHALL show what each placed flow draws.

#### Scenario: An unmatched link
- **WHEN** an agent's accepted document holds `[[Ledgr]]`, which matches no concept
- **THEN** the result's `message` names `[[Ledgr]]` as reading as plain text

#### Scenario: Reviewing an agent's flow
- **WHEN** an agent claims the `document_review` task of a document that places a flow
- **THEN** the brief's input lists that flow's steps as text

### Requirement: A returned submission comes back with the document
The system SHALL, when a `documentation` submission is refused or its review sends the document back, add to the task's brief the title and body last submitted, the flows submitted with their drawings where they could be drawn, the statement ids it cited, and the findings, with the instruction to revise that text instead of starting over. The brief of a task that revises a saved document SHALL hold the document's current text, flows and cited statement ids.

#### Scenario: Sent back by review
- **WHEN** an agent's document with one flow is refused by its review and an agent claims the task again
- **THEN** the brief holds the submitted body, the flow's definition and steps, the cited statement ids and the review's findings

#### Scenario: Refused at submission
- **WHEN** a submission is refused for a flow that is never placed and the agent reads the task again
- **THEN** the brief holds the body it submitted and the refusal as a finding
