## MODIFIED Requirements

### Requirement: Retry sweep
The system SHALL, every 60 seconds while the mode is not `off` and credentials are present, retry a submitted draft's latest attempt that failed without recording a review, once 5 minutes times 2 to the power of its retry count have passed since it finished, at most 5 retries, and only while that failure is under 160 minutes old. Each retry SHALL be a fresh first attempt. `MYCELIUM_DISABLE_REVIEW_SWEEP=1` SHALL disable the sweep.

#### Scenario: Failure older than the window
- **WHEN** a draft's latest attempt failed more than 160 minutes ago, as in a restored copy of another instance
- **THEN** the sweep does not retry it and the draft is listed in the backlog

### Requirement: Review backlog
The system SHALL let an admin list through `GET /api/draft-review/backlog` the submitted drafts the current configuration has not reached, oldest first and without alias-suggestion-only drafts, as `{draft_ids, external_agent, job}` with the latest job. `POST /api/draft-review/backlog` SHALL start that job and return `{job}`, refused while the mode is `off` or a job is unfinished.

#### Scenario: Switching review on
- **WHEN** an admin turns review on with three drafts submitted while it was off and posts the backlog
- **THEN** the job reviews those three drafts one at a time, oldest first, and finishes with `reviewed: 3`

### Requirement: Backlog job control
The system SHALL report a backlog job's `status` (`running`, `paused`, `finished`), `used_tokens`, `reviewed`, `remaining`, `detail`, `started_at` and `finished_at`, SHALL pause it after the draft under review on `POST /api/draft-review/backlog/pause`, and SHALL continue it on `POST /api/draft-review/backlog/resume`.

#### Scenario: Pause and resume
- **WHEN** an admin pauses a running backlog job reviewing three drafts after the first
- **THEN** the job is `paused` with `reviewed: 1`, and after resume it finishes with `reviewed: 3`

## ADDED Requirements

### Requirement: Backlog review without a budget
The system SHALL run a started backlog review in one background job, held in the server process and forgotten on restart, that reviews one draft at a time and each at most once, and before each draft SHALL finish when no waiting draft is left, or pause with a `detail` saying why when review can no longer run, as when it is switched off or loses its credentials. The job SHALL set no token budget; each review is bounded by `max_draft_tokens`.

#### Scenario: Runs to the end
- **WHEN** an admin starts a backlog job over three waiting drafts whose reviews use 1,000 tokens each
- **THEN** the job finishes with `reviewed: 3` and `used_tokens: 3000`

### Requirement: Attempts an earlier budget paused
The system SHALL resume, in the retry sweep, an attempt an earlier version's monthly AI budget left `paused`, keeping its attempt and retry counts and its previous failure. A paused attempt SHALL NOT count as backlog.

#### Scenario: Upgrading with a paused review
- **WHEN** an instance upgrades with a submitted draft whose latest attempt is `paused`
- **THEN** the next sweep reviews the draft again with the same attempt and retry counts

## REMOVED Requirements

### Requirement: Backlog review job
**Reason**: The job has no token budget any more; the rest moves to "Backlog review without a budget".
**Migration**: None; a start request's `budget_tokens` is ignored.

### Requirement: Budget-paused attempts
**Reason**: Mycelium sets no AI budget, so no new attempt is paused by one.
**Migration**: Attempts paused before the upgrade are resumed by the sweep, as "Attempts an earlier budget paused" requires.
