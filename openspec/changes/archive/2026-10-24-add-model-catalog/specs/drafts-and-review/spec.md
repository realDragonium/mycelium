## ADDED Requirements

### Requirement: Review token cap
The system SHALL estimate, before any model call, the tokens reviewing a draft could use from its parts' context sizes and the output token bound, and SHALL produce a `reject` assessment naming the estimate, the number of parts and the cap when the estimate exceeds the draft review `max_draft_tokens` product setting (default 300,000; 0 means no cap).

#### Scenario: Draft over the cap
- **WHEN** `max_draft_tokens` is 100 and a submitted draft is reviewed
- **THEN** the draft receives a `reject` assessment asking to split it and no model is called

## MODIFIED Requirements

### Requirement: Review backlog
The system SHALL let an admin list through `GET /api/draft-review/backlog` the submitted drafts the current configuration has not reached, oldest first and without alias-suggestion-only drafts, as `{draft_ids, estimated_tokens, job}`: their number times the 30-day mean run's tokens (`null` without one) and the latest job. `POST /api/draft-review/backlog`, with an optional `budget_tokens` above 0, SHALL start that job and return `{job}`, refused while the mode is `off` or a job is unfinished.

#### Scenario: Switching review on
- **WHEN** an admin turns review on with three drafts submitted while it was off and posts the backlog
- **THEN** the job reviews those three drafts one at a time, oldest first, and finishes with `reviewed: 3`

### Requirement: Backlog review job
The system SHALL run a started backlog review in one background job, held in the server process and forgotten on restart, that reviews one draft at a time and each at most once, and before each draft SHALL finish when no waiting draft is left, or pause with a `detail` saying why when the job's tokens plus those of the mean review run would pass `budget_tokens` or the monthly AI budget pauses draft review.

#### Scenario: Budget reached
- **WHEN** a job with `budget_tokens` 1,500 has used 1,000 and a review uses 1,000 on average
- **THEN** the job stops before the next draft with a detail saying it stopped at the backlog budget

### Requirement: Backlog job control
The system SHALL report a backlog job's `status` (`running`, `paused`, `finished`), `budget_tokens`, `used_tokens`, `reviewed`, `remaining`, `detail`, `started_at` and `finished_at`, SHALL pause it after the draft under review on `POST /api/draft-review/backlog/pause`, and SHALL continue it on `POST /api/draft-review/backlog/resume`.

#### Scenario: Pause and resume
- **WHEN** an admin pauses a running backlog job reviewing three drafts after the first
- **THEN** the job is `paused` with `reviewed: 1`, and after resume it finishes with `reviewed: 3`

## REMOVED Requirements

### Requirement: Review cost cap
**Reason**: Mycelium keeps no prices; replaced by "Review token cap".
**Migration**: A saved `max_cost_usd` at its $1 default becomes 300,000 tokens; any other value becomes no cap.
