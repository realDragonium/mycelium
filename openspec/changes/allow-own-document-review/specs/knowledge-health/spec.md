## MODIFIED Requirements

### Requirement: Answering a reviewer question by release
An `answered` release SHALL take exactly one `question` item, a non-blank `answer` of at most 6,000 characters and one to five `evidence` items in the shape draft operation evidence takes, from an identified principal, the draft's creator included. It SHALL record the answer on the asking review run as a curator's answer is recorded, with the agent as `answered_by` and its evidence, and start the next review attempt; the question's gap stays open until the draft is applied.

#### Scenario: Answer with evidence
- **WHEN** a drafter agent releases a question item as `answered` with an answer and a code excerpt
- **THEN** the review run stores the answer with the agent and its evidence, and a fresh review of the draft starts

#### Scenario: Answer without evidence
- **WHEN** a drafter agent releases a question item as `answered` with no evidence
- **THEN** the release is refused

#### Scenario: The draft's creator answers
- **WHEN** the principal that created the draft releases its question as `answered` with an answer and evidence
- **THEN** the answer is recorded and a fresh review of the draft starts
