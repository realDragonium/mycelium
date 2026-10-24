## MODIFIED Requirements

### Requirement: Reviewer input
The system SHALL give the reviewer one fresh structured-output model call per review part, with no tools and no author conversation, with the part's operations, their evidence and findings, the draft evidence, the affected knowledge, the link type glossary, correction tool schemas, curator answers, any previous failure, and up to 5 closest live statements per new statement text, best first, within 90,000 characters. Each of several parts SHALL also get an 8,000-character summary of the others.

#### Scenario: Context fills up
- **WHEN** adding another closest live statement would push the context over 90,000 characters
- **THEN** that statement is left out and no further closest statements are added

### Requirement: Draft size limits for review
The system SHALL review a draft too large for one context in connected parts: operations that change the same record, refer to one another's new statements with `@S:N`, or name an entity another operation creates SHALL share a part, packed in operation order into parts that each fit. A connected group whose context without closest statements exceeds 90,000 characters SHALL produce a `reject` assessment asking to narrow the draft, without a model call.

#### Scenario: Draft touching 31 records
- **WHEN** a submitted draft adds a batch of invoice statements and, separately, a workspace concept, together affecting 31 records
- **THEN** the draft is reviewed in two parts and no attempt fails for its size

### Requirement: Correction validation
The system SHALL validate every correction before publishing an assessment in any mode: `revise` and `strike` name an existing `operation_ref`, each at most once and within the reviewed part; `append` names a reviewable tool and no `operation_ref`; `strike` carries no payload; `revise` and `append` carry a JSON object payload binding to the tool's parameters with strict types and no unknown nested fields. An invalid correction SHALL fail the attempt with no label and a detail naming the problem.

#### Scenario: Correction for an unknown operation
- **WHEN** the model proposes revising an `operation_ref` the draft does not contain
- **THEN** the attempt fails and its record carries no label

### Requirement: Draft statement references in corrections
The system SHALL fail an attempt whose correction uses a bare `@N` outside an `upsert_statements` batch or past the end of its batch, or an `@S:N` that names no statement of the draft's `upsert_statements` operation at seq `S`, saying how the statement is named.

#### Scenario: Link to a batch statement written as a bare reference
- **WHEN** the model appends an `add_links` correction whose target is `@0` instead of `@3:0`
- **THEN** the attempt fails saying that outside a batch the statement is named as `@<seq>:<index>`

### Requirement: Review backlog
The system SHALL let an admin list through `GET /api/draft-review/backlog` the submitted drafts the current configuration has not reached, oldest first and without alias-suggestion-only drafts, as `{draft_ids, estimated_cost_usd, job}`: their number times the 30-day mean review cost (`null` unpriced) and the latest job. `POST /api/draft-review/backlog`, with an optional `budget_usd` above 0, SHALL start that job and return `{job}`, refused while the mode is `off` or a job is unfinished.

#### Scenario: Switching review on
- **WHEN** an admin turns review on with three drafts submitted while it was off and posts the backlog
- **THEN** the job reviews those three drafts one at a time, oldest first, and finishes with `reviewed: 3`

## ADDED Requirements

### Requirement: Rerun and rejection after a failed attempt
The system SHALL, in `review-and-apply` mode with the gate on, start one more attempt (`attempt: 2`) when an attempt fails without recording a review, passing the failure to the reviewer; when that second attempt also fails, the draft SHALL be rejected with an authoritative `rejected` review and a knowledge gap, unless the failure came from the model provider, which SHALL leave the draft `submitted`.

#### Scenario: Invalid correction twice
- **WHEN** both attempts on a draft fail because a correction leaves a phrasing finding
- **THEN** the draft is rejected with a rationale saying automatic review failed twice

#### Scenario: Provider outage
- **WHEN** both attempts fail with a model provider error
- **THEN** the draft remains `submitted`


### Requirement: Part-wise review outcome
The system SHALL act on a draft reviewed in parts only as a whole: a `reject` from any part SHALL reject the draft with that part's rationale, otherwise a `needs_context` from any part SHALL make the draft wait with that part's questions, otherwise every part's corrections SHALL be applied together and the draft applied.

#### Scenario: One part rejects
- **WHEN** a draft is reviewed in two parts and the second part returns `reject`
- **THEN** no operation of either part is applied and the draft is rejected with a rationale naming part 2

#### Scenario: Both parts correct their own operations
- **WHEN** each of two parts returns `changes_suggested` revising one of its own operations
- **THEN** both revisions are applied in one transaction and the draft is applied

### Requirement: Part assessments
The system SHALL keep one assessment for a draft reviewed in parts, whose `parts` lists each part's `operation_refs`, `label`, `rationale`, `questions`, `corrections` and `contradictions`; a draft reviewed whole SHALL have empty `parts`.

#### Scenario: Draft reviewed in two parts
- **WHEN** a draft is reviewed in two parts that both return `good`
- **THEN** its assessment has label `good` and two `parts`, each listing its own operations

### Requirement: Review cost cap
The system SHALL estimate, before any model call, what reviewing a draft could cost from its parts' context sizes, the output token bound and the selected model's price, and SHALL produce a `reject` assessment naming the estimate, the number of parts and the cap when the estimate exceeds the draft review `max_cost_usd` product setting (default 1.0, greater than 0). A model without a known price SHALL have no cap.

#### Scenario: Draft over the cap
- **WHEN** `max_cost_usd` is 0.0001 and a priced model would review a submitted draft
- **THEN** the draft receives a `reject` assessment asking to split it and no model is called

### Requirement: Stale draft refusal
The system SHALL produce a `reject` assessment without a model call when an operation would overwrite an entity or statement whose current content was written after the draft was created, by a direct edit or by another applied draft created later, or that no longer exists. An operation that leaves the record's content unchanged SHALL NOT count.

#### Scenario: Direct edit after the draft
- **WHEN** a writer edits an invoice statement after a draft that replaces its text was created
- **THEN** the draft is rejected saying the statement changed after the draft was written, and nothing is applied

#### Scenario: Two drafts on one statement
- **WHEN** two pending drafts replace the same statement's text and the newer one is applied first
- **THEN** the older draft is rejected as stale, while the newer one applies whatever the order

### Requirement: Backlog review job
The system SHALL run a started backlog review in one background job, held in the server process and forgotten on restart, that reviews one draft at a time and each at most once, and before each draft SHALL finish when no waiting draft is left, or pause with a `detail` saying why when the job's spending plus the mean review cost would pass `budget_usd` or the monthly AI budget pauses draft review.

#### Scenario: Budget reached
- **WHEN** a job with `budget_usd` 1.5 has spent 1.0 and a review costs 1.0 on average
- **THEN** the job stops before the next draft with a detail saying it stopped at the backlog budget

### Requirement: Backlog job control
The system SHALL report a backlog job's `status` (`running`, `paused`, `finished`), `budget_usd`, `spent_usd`, `reviewed`, `remaining`, `detail`, `started_at` and `finished_at`, SHALL pause it after the draft under review on `POST /api/draft-review/backlog/pause`, and SHALL continue it on `POST /api/draft-review/backlog/resume`.

#### Scenario: Pause and resume
- **WHEN** an admin pauses a running backlog job reviewing three drafts after the first
- **THEN** the job is `paused` with `reviewed: 1`, and after resume it finishes with `reviewed: 3`

## REMOVED Requirements

### Requirement: Rerun and rejection after failure
**Reason**: A draft no longer fails for its size, so its "Draft too large twice" scenario no longer exists; the rule is restated as "Rerun and rejection after a failed attempt".
**Migration**: None; the rerun and rejection behaviour is unchanged.
