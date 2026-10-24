## MODIFIED Requirements

### Requirement: Ask tool and compact result
The system SHALL provide the tool `ask(question, depth="standard", verbose=False)` that answers from the knowledge base and by default returns `{outcome: "answered", answer, confidence}`, with `confidence` one of `high`, `medium` or `low`, or `{outcome: "needs_clarification", question}`.

#### Scenario: Default answer
- **WHEN** a reader calls `ask` with "Who can export invoices?"
- **THEN** the response has exactly `outcome`, `answer` and `confidence`

### Requirement: Ask quick depth
At `depth: "quick"` the system SHALL drop the evidence floor, accepting the first well-formed `submit_answer`, and cap the run at the lower of the saved limits and 8 operations, 25 seconds wall clock and 20 seconds per model request.

#### Scenario: Quick answer after one read
- **WHEN** a reader calls `ask` with `depth: "quick"` and the model submits after recon and one read
- **THEN** the answer is accepted without an adjacency re-search
