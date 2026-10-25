## ADDED Requirements

### Requirement: AI answer limit
The system SHALL let the draft-review model answer again after its first answer at most `answer_retries` times in a row (draft review limits, default 2), counting model answers since the last answer a person gave. At the limit the run SHALL note "Stopped AI answers after N; the questions wait for a person." and make no model call.

#### Scenario: Limit reached
- **WHEN** `answer_retries` is 0, the model answered once and the reviewer asks again
- **THEN** no answer attempt is made and the run notes that AI answers stopped

#### Scenario: A person answered in between
- **WHEN** a person answered after the model's last answer and the reviewer asks again
- **THEN** the model may answer again

### Requirement: Refreshed review limit
The system SHALL start another review after refreshed alias suggestions at most `refresh_reviews` times in a row (draft review limits, default 2). At the limit the run SHALL note that it stopped reviewing again, which an external agent's closed task carries as its summary, and the draft SHALL stay in the review backlog for an admin; a review a person or the backlog starts SHALL count from zero.

#### Scenario: Limit reached
- **WHEN** `refresh_reviews` is 0 and a review refreshes a suggestion
- **THEN** no further review starts and the run notes why
