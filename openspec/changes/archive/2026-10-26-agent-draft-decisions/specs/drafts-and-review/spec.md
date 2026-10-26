## MODIFIED Requirements

### Requirement: Draft inspection
The system SHALL return a draft and its operations in `seq` order from one consistent snapshot through `get_draft(draft_id)` (any caller with read access) and `GET /api/drafts/{id}`. Each operation SHALL carry `operation_ref`, `seq`, `kind`, `payload`, `provenance` and `evidence`; the draft SHALL carry `review_evidence`, `review_assessment`, `revision`, `source`, lifecycle fields and `decisions`. `get_draft` SHALL also return `missing`: `[]`, or `[draft_id]` when no draft has that id.

#### Scenario: Unknown draft id
- **WHEN** a caller calls `get_draft` with an id no draft carries
- **THEN** the result is `{id, missing: [id]}` instead of an error
- **AND** `GET /api/drafts/{id}` answers 404 for the same id

### Requirement: Draft listing
The system SHALL list drafts newest first: `list_my_drafts` returns the caller's own drafts in full; `list_drafts(status, created_by, label, application)` returns every creator's drafts to an identified real writer or admin only, and `GET /api/drafts` every draft, each with `op_count` and an assessment summary (`run_id`, `status`, `label`, `application`, `stale`) and without review evidence. Status filters are `all`, `open`, `submitted`, `approved`, `rejected` and `withdrawn`.

#### Scenario: Drafter tries to list the queue
- **WHEN** a drafter calls `list_drafts`
- **THEN** the call is refused because it requires the real writer role

#### Scenario: Invalid status filter
- **WHEN** a caller requests `GET /api/drafts?status=pending`
- **THEN** the response is 400 naming the allowed status values


## ADDED Requirements

### Requirement: Filtering drafts by review
The system SHALL keep only drafts whose latest assessment has the given `label` or `application` outcome when `list_drafts` or `GET /api/drafts` is given `label` or `application`.

#### Scenario: Drafts the reviewer rejected
- **WHEN** a writer calls `list_drafts(status="rejected", application="rejected")`
- **THEN** only drafts the automatic reviewer rejected are listed, not ones a person rejected

### Requirement: Deciding a draft over MCP
The system SHALL offer real writers and admins `review_draft(draft_id, verdict, expected_revision, reason, corrections, question, evidence)` over MCP for a `submitted` draft, in every review mode. `approve` SHALL apply the draft as a manual approval does; `approve_with_corrections` SHALL validate and make the corrections as accepting held corrections does, then approve the corrected draft, changing nothing if a correction does not fit or leaves an operation finding.

#### Scenario: Agent approves under review-only
- **WHEN** an admin agent approves a submitted invoice-export draft while the review mode is `review-only`
- **THEN** the draft is applied, becomes `approved` with the agent as `decided_by`

#### Scenario: Agent corrects a statement
- **WHEN** an agent approves with an `edit` correction changing a statement's text
- **THEN** the corrected text is applied and the original text is not

### Requirement: Rejecting or asking over MCP
The system SHALL, for `review_draft` verdict `reject`, require a reason and close the draft as a manual rejection does, and for verdict `needs_context`, require a question, file it as a knowledge gap naming the draft and leave the draft `submitted`.

#### Scenario: Rejection without a reason
- **WHEN** an agent calls `review_draft` with verdict `reject` and no reason
- **THEN** the call is refused and the draft stays `submitted`

#### Scenario: Asking a person
- **WHEN** an agent decides `needs_context` asking whether exports are limited to paid plans
- **THEN** a knowledge gap naming the draft holds the question and the draft stays `submitted`

### Requirement: Agent decision refusals
The system SHALL refuse `review_draft` and `reopen_draft` for a draft the calling principal created, SHALL refuse `review_draft` when the draft's revision differs from `expected_revision`, and SHALL refuse an approval when a record the draft changes was rewritten after the draft was written, as the stale draft refusal defines it.

#### Scenario: Own draft
- **WHEN** an agent calls `review_draft` on a draft it created
- **THEN** the call is refused with a role error and the draft is unchanged

#### Scenario: Statement edited after the draft
- **WHEN** a statement is edited directly after a draft that patches it was written, and an agent approves that draft
- **THEN** the approval is refused naming the newer change and nothing is applied

### Requirement: Reopening a rejected draft
The system SHALL let a real writer or admin return a `rejected` draft to `submitted`, through `reopen_draft(draft_id, reason)` over MCP, refused for a draft the caller created, or `POST /api/drafts/{id}/reopen` with a `reason`, clearing its decision. Reopening SHALL be refused for a draft that is not `rejected` and for one whose changed records were rewritten after it was written. A reopened draft SHALL NOT be reviewed automatically again on that account.

#### Scenario: Reconsidering a reviewer rejection
- **WHEN** an agent reopens a draft the automatic reviewer rejected and then approves it
- **THEN** the draft is applied and its decisions read rejected, reopened, approved

#### Scenario: Withdrawn draft
- **WHEN** a writer tries to reopen a withdrawn draft
- **THEN** the request is refused

### Requirement: Draft decision log
The system SHALL record every approval, rejection, reopening and question made by a person in the web app or by `review_draft` and `reopen_draft`, with its action, decider, time, reason, evidence items and the corrections made, and SHALL return them in order as the draft's `decisions`. The automatic reviewer's own outcomes SHALL stay in its review assessment.

#### Scenario: Person rejects in the web app
- **WHEN** a curator rejects a draft with **Reject** and reopens it with a reason
- **THEN** the draft's `decisions` list a rejection and a reopening by that curator, the second with the reason
