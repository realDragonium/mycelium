## MODIFIED Requirements

### Requirement: Evidence item shape
The system SHALL require each operation evidence item to have a `kind` of `code`, `ui`, `doc`, `media` or `other`, a one-line `claim` of 1 to 200 characters, an optional `excerpt` of at most 1,500 characters, and one location: a relative `path` of at most 300 characters (optional `lines` such as `40-52` and a 7 to 40 hex `commit`), an `http(s)` `url` of at most 500 characters, a `statement_id` or `draft_id` (Knowledge-base evidence), or, for `media` items only, a `media_id`.

#### Scenario: Absolute path
- **WHEN** the creator supplies an item whose `path` starts with `/` or contains a `..` segment
- **THEN** the call is refused because the path must be relative to the repository root

#### Scenario: Lines without a path
- **WHEN** an item carries `lines` and a `url` but no `path`
- **THEN** the call is refused

### Requirement: Applying reviewer alias decisions
In `review-and-apply` with the application gate on, the system SHALL make each reviewer alias decision through the suggestion's accept or reject path as the reviewer, never the draft's creator, recording the quote and reason, and SHALL settle a suggestion that changed since as Stale alias suggestions under review describes. In `review-only` the decisions SHALL stay advisory.

#### Scenario: Reviewer accepts an alias
- **WHEN** review is `review-and-apply`, `alias_decisions` is on and the reviewer accepts a suggestion quoting its source
- **THEN** the alias is added, the decision records the reviewer, quote and reason, and a draft of only that suggestion closes as approved

#### Scenario: Review only
- **WHEN** review is `review-only` and the reviewer decides a suggestion
- **THEN** the suggestion stays pending for a person

## ADDED Requirements

### Requirement: Knowledge-base evidence
An evidence item SHALL be accepted when it locates its excerpt by a knowledge-base `statement_id` (`stm_…`) or by the `draft_id` of a draft whose review evidence it quotes.

#### Scenario: Statement evidence
- **WHEN** an item has `kind: doc`, a `statement_id` of a live statement and an excerpt of its text
- **THEN** the item is accepted and the draft screen links the statement

### Requirement: Stale alias suggestions under review
When a reviewer decides an alias suggestion whose source text changed since the scan, the system SHALL reject it as the reviewer with the reason that the supporting statement changed; when only its concept names changed, it SHALL refresh the suggestion against the current names and review the draft again.

#### Scenario: Source changed since the suggestion
- **WHEN** the reviewer decides a suggestion whose supporting statement was edited after the scan
- **THEN** the suggestion is rejected as the reviewer, saying the supporting statement changed

#### Scenario: Names changed since the suggestion
- **WHEN** the reviewer decides a suggestion whose concept gained a name after the scan
- **THEN** the suggestion is refreshed and a new review of the draft starts

### Requirement: AI answers to the reviewer's questions
While `answer_questions` is on (saved with the review controls, default off, read as off from controls saved without it), the system SHALL, after a server-model review in `review-and-apply` asks a person, make one answer attempt on the same draft-review model from the draft, its operations and evidence, the statements the review relied on and statements found for each question, at most twice per draft.

#### Scenario: Setting off
- **WHEN** `answer_questions` is off and the reviewer asks a person
- **THEN** no answer attempt is made

### Requirement: Grounding an AI answer
An AI answer SHALL be recorded only when the model says the sources settle every question and every source quote is found in the named supplied statement or the draft's evidence; it SHALL be recorded as an answer from `model:<model>` with those quotes as evidence and the draft reviewed again. Otherwise the run SHALL note that no grounded answer was found and the question SHALL stay open for an agent or a person.

#### Scenario: Grounded answer
- **WHEN** the reviewer asks whether exports run nightly and a supplied statement says "Exports run every night at 02:00"
- **THEN** the answer is recorded with that statement as evidence and the draft is reviewed again

#### Scenario: Not settled by the sources
- **WHEN** the model answers with a quote no supplied statement contains
- **THEN** no answer is recorded, the run notes why, and the question stays open

### Requirement: Final refusals under an external reviewer
While `reject_refused` is on (saved with the review controls, default off, read as off from controls saved without it), draft review runs on an external agent in `review-and-apply` and the application gate is on, the system SHALL reject a draft it refuses before review (unsupported operations, newer knowledge, too large) as the agent that claimed its task, with the refusal as the rationale and a rejection gap, instead of leaving an advisory rejection for a person.

#### Scenario: Draft too large for review
- **WHEN** an agent claims the review of a draft with more parts than review allows
- **THEN** the draft is rejected by that agent with the size refusal as the rationale, and no brief is returned

#### Scenario: Setting off
- **WHEN** `reject_refused` is off and the server refuses a draft before review
- **THEN** the assessment is an advisory rejection and the draft stays submitted
