## MODIFIED Requirements

### Requirement: Retry sweep
The system SHALL, every 60 seconds while the mode is not `off` and credentials are present, retry a submitted draft's latest attempt that failed without recording a review, once 5 minutes times 2 to the power of its retry count have passed since it finished, within the review failure limit, and only while that failure is under 160 minutes old or under twice that wait. Each retry SHALL be a first attempt. `MYCELIUM_DISABLE_REVIEW_SWEEP=1` SHALL disable the sweep.

#### Scenario: Failure older than the window
- **WHEN** a draft's latest attempt failed more than 160 minutes ago, as in a restored copy of another instance
- **THEN** the sweep does not retry it and the draft is listed in the backlog

### Requirement: AI answer limit
The system SHALL let the draft-review model answer again after its first answer at most `answer_retries` times in a row (draft review limits, default 2), counting the model's answers and curation agents' answers (those with evidence) since the last answer a person gave. At the limit the run SHALL note "Stopped AI answers after N; the questions wait for a person." and make no model call.

#### Scenario: Limit reached
- **WHEN** `answer_retries` is 0, the model answered once and the reviewer asks again
- **THEN** no answer attempt is made and the run notes that AI answers stopped

#### Scenario: A person answered in between
- **WHEN** a person answered after the model's last answer and the reviewer asks again
- **THEN** the model may answer again

## ADDED Requirements

### Requirement: Review failure limit
The system SHALL count the immediate rerun of a failed review and every sweep retry toward one limit, `failure_retries` (draft review limits, default 2); a sweep retry gets the rerun only while the limit allows. Past the limit the draft's review SHALL be listed as a stopped automation, and nothing retries it until the draft changes or an admin retries it, which starts the count over.

#### Scenario: Past the limit
- **WHEN** the provider keeps failing and a draft's review has been retried `failure_retries` times
- **THEN** the sweep does not retry it again, and Knowledge health lists it as stopped with the last failure

#### Scenario: Admin retry
- **WHEN** an admin retries the stopped draft review
- **THEN** the next sweep reviews the draft again with a fresh count

### Requirement: Questions curation agents answered too often
The system SHALL NOT offer a reviewer's question as a curation item once the model and curation agents answered the draft's questions more often in a row than `answer_retries` allows; it waits for a person.

#### Scenario: Curation agents keep answering
- **WHEN** curation agents and the model answered more often in a row than `answer_retries` allows and the reviewer asks again
- **THEN** the question is not offered as a curation item
