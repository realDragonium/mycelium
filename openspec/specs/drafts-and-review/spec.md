# drafts-and-review Specification

## Purpose
Drafts hold proposed knowledge changes as queued substrate operations, kept off the live knowledge until they are reviewed and applied. This capability covers how drafts are filled, submitted, assessed by the internal reviewer, corrected, approved, rejected and applied, and the evidence and receipts that make each step checkable.

## Requirements

### Requirement: Draft lifecycle states
The system SHALL derive a draft's `status` from its lifecycle timestamps and recorded decision: `open` (not submitted, not decided), `submitted` (submitted, not decided), and the terminal states `approved`, `rejected` and `withdrawn`. Draft ids SHALL have the form `drf_` followed by 12 hexadecimal characters, and operation references the form `op_` followed by 12 hexadecimal characters.

#### Scenario: A submitted draft is approved
- **WHEN** a draft is created, submitted and then approved by a curator
- **THEN** its status reads `open`, then `submitted`, then `approved`
- **AND** no operation can be added, revised or removed once it is `approved`

### Requirement: Drafter writes are queued onto a draft
The system SHALL queue every call a drafter makes to a substrate mutation tool (a tool whose name starts with `upsert_`, `add_`, `delete_`, `remove_`, `replace_`, `patch_`, `rename_`, `move_` or `merge_`) onto a draft instead of writing live knowledge, and SHALL answer with a receipt carrying `draft_id`, `seq`, `operation_ref`, `queued` (the tool name) and `revision`.

#### Scenario: A drafter upserts a statement
- **WHEN** a drafter calls `upsert_statement` with the text "An invoice export can be scheduled weekly"
- **THEN** the live knowledge base is unchanged
- **AND** the response is a receipt naming the draft, the operation's `seq` and `operation_ref`, `queued: "upsert_statement"` and the draft's new revision

### Requirement: One open auto-draft per drafter session
The system SHALL route a drafter's write without an explicit `draft_id` to that drafter's open draft for the current MCP session, or, when the call carries no session id, for the key `actor:<principal id>`, creating the draft when none is open. The lookup SHALL match the creator as well as the session key, so presenting another principal's session id never reaches that principal's draft.

#### Scenario: Two writes in one session
- **WHEN** a drafter makes two mutation calls in the same session
- **THEN** both operations are queued on the same open draft

#### Scenario: Reused session id
- **WHEN** a second drafter presents the first drafter's session id on a write
- **THEN** the write is queued on a draft created by the second drafter, not on the first drafter's draft

### Requirement: Explicit draft targeting
The system SHALL accept an optional `draft_id` on every substrate mutation tool, queue the call onto that draft instead of executing it, and refuse the call when the draft does not exist, is not `open`, or belongs to another user and the caller is not a real writer or admin.

#### Scenario: Writer adds to an existing open draft
- **WHEN** a writer calls `add_links` with the `draft_id` of an open draft
- **THEN** the links are queued on that draft and not written live

#### Scenario: Target draft already submitted
- **WHEN** a caller passes the `draft_id` of a submitted draft to `upsert_entity`
- **THEN** the call is refused with an error saying only open drafts accept new ops

### Requirement: Listing queued operations of a draft
The system SHALL let `list_statements`, `list_entities`, `list_link_types`, `list_entity_link_types` and `list_statement_kinds`, when called with a `draft_id`, return that draft's queued operations of the matching kind (`upsert_statement`, `upsert_entity`, `upsert_link_type`, `upsert_entity_link_type`, `upsert_statement_kind` respectively), each as its payload plus `_seq` and `_kind` markers.

#### Scenario: Listing a draft's queued statements
- **WHEN** a caller calls `list_statements` with the id of a draft holding two queued `upsert_statement` operations
- **THEN** the result holds those two payloads, each with its `_seq` and `_kind: "upsert_statement"`

### Requirement: Draft revision counter
The system SHALL keep a per-draft integer `revision` that increases whenever an operation is added, its payload changes, or it is removed, and whenever the draft's review evidence, an operation's evidence, or the draft's source metadata changes. Calls that accept `expected_revision` SHALL refuse with a conflict when it does not equal the current revision.

#### Scenario: Stale expected revision
- **WHEN** a curator revises an operation with `expected_revision` 3 while the draft is at revision 4
- **THEN** the call is refused with a conflict naming both revisions and the operation is unchanged

### Requirement: Draft inspection
The system SHALL return a draft and its operations in `seq` order from one consistent snapshot through `get_draft(draft_id)` (any caller with read access) and `GET /api/drafts/{id}`. Each operation SHALL carry `operation_ref`, `seq`, `kind`, `payload`, `provenance` and `evidence`; the draft SHALL carry `review_evidence`, `review_assessment`, `revision`, `source` and lifecycle fields. `get_draft` SHALL also return `missing`: `[]`, or `[draft_id]` when no draft has that id.

#### Scenario: Unknown draft id
- **WHEN** a caller calls `get_draft` with an id no draft carries
- **THEN** the result is `{id, missing: [id]}` instead of an error
- **AND** `GET /api/drafts/{id}` answers 404 for the same id

### Requirement: Draft listing
The system SHALL list drafts newest first: `list_my_drafts` returns the caller's own drafts in full; `list_drafts(status, created_by)` returns every creator's drafts, with `op_count` and without review evidence or assessment, to an identified real writer or admin only; `GET /api/drafts?status=` returns every draft with `op_count` and an assessment summary (`run_id`, `status`, `label`, `application`, `stale`). Status filters are `all`, `open`, `submitted`, `approved`, `rejected` and `withdrawn`.

#### Scenario: Drafter tries to list the queue
- **WHEN** a drafter calls `list_drafts`
- **THEN** the call is refused because it requires the real writer role

#### Scenario: Invalid status filter
- **WHEN** a caller requests `GET /api/drafts?status=pending`
- **THEN** the response is 400 naming the allowed status values

### Requirement: Draft ownership
The system SHALL allow only a draft's creator, or a real writer or admin, to submit it, withdraw it, discard its operations or queue operations onto it by `draft_id`.

#### Scenario: Drafter changes another user's draft
- **WHEN** a drafter calls `discard_draft_op` on a draft another user created
- **THEN** the call is refused with a role error saying the draft belongs to another user

### Requirement: Submitting a draft
The system SHALL submit an `open` draft through `submit_draft(draft_id)` or `POST /api/drafts/{id}/submit`, after which tool calls can no longer queue operations onto it. When `draft_id` is omitted, `submit_draft` SHALL submit the caller's open auto-draft and refuse when there is none. `submit_draft` SHALL return `{draft_id, op_count}`; the HTTP route SHALL return `{ok: true}`. Submitting a draft that is not `open` SHALL be refused.

#### Scenario: Submitting the session draft
- **WHEN** a drafter calls `submit_draft()` with no argument after queuing three operations
- **THEN** the session's open draft becomes `submitted` and the result reports `op_count: 3`

#### Scenario: Submitting twice
- **WHEN** a caller submits a draft that is already submitted
- **THEN** the call is refused saying only open drafts can be submitted

### Requirement: Submission starts internal review
The system SHALL start an internal review attempt when a draft is submitted over either path, provided the review mode is not `off` and the selected provider has credentials. A failure to start review SHALL NOT undo the submission.

#### Scenario: Review off at submission
- **WHEN** a draft is submitted while the review mode is `off`
- **THEN** the draft is `submitted` and has no `review_assessment`

### Requirement: Model-produced drafts are submitted while review is on
The system SHALL submit the draft produced by `ingest` or `connect_statements` itself, and report `submitted_for_review: true`, only when the review mode is not `off`, the draft is still `open` and it holds at least one operation; otherwise the draft SHALL stay `open` and the response SHALL report `submitted_for_review: false`.

#### Scenario: Ingest with review off
- **WHEN** `ingest` creates a draft while the review mode is `off`
- **THEN** the draft stays `open` for curation and the response carries `submitted_for_review: false`

### Requirement: Correcting operations
The system SHALL let a real writer or admin replace an operation's payload or remove an operation on an `open` or `submitted` draft, by reference through `revise_draft_operation` and `strike_draft_operation` (returning `{draft_id, operation_ref, revision}`), or by `seq` through `PATCH /api/drafts/{id}/ops/{seq}` with `{payload, expected_revision}` and `DELETE /api/drafts/{id}/ops/{seq}` (returning `{ok: true, revision}`, 404 for an unknown `seq`).

#### Scenario: Drafter tries to revise an operation
- **WHEN** a drafter calls `revise_draft_operation`
- **THEN** the call is refused because it requires the real writer role

#### Scenario: Editing an approved draft
- **WHEN** a curator sends `PATCH /api/drafts/{id}/ops/2` for an approved draft
- **THEN** the response is 400 and the operation is unchanged

### Requirement: Correction refusals
The system SHALL refuse revising or striking an operation that does not exist on the draft, and SHALL refuse both on a draft in a terminal state or with an active reviewed application.

#### Scenario: Revising a missing operation
- **WHEN** a curator calls `strike_draft_operation` with an `operation_ref` the draft does not hold
- **THEN** the call is refused saying the operation was not found in the draft

### Requirement: Discarding an operation from an open draft
The system SHALL let the creator or a real writer remove an operation from an `open` draft by `seq` through `discard_draft_op(draft_id, seq, expected_revision)`, returning `{draft_id, seq, removed: true, revision}`. Remaining operations SHALL keep their `seq` numbers, and a newly queued operation SHALL take one more than the highest `seq` still on the draft.

#### Scenario: Discarding the middle operation
- **WHEN** a drafter discards `seq` 2 of operations 1, 2 and 3 and then queues another write
- **THEN** the remaining operations are numbered 1 and 3 and the new one is numbered 4

### Requirement: Withdrawing and rejecting a draft
The system SHALL let the creator or a real writer withdraw an `open` or `submitted` draft through `POST /api/drafts/{id}/withdraw`, and let a real writer or admin reject one through `POST /api/drafts/{id}/reject`; neither SHALL change live knowledge. Both SHALL be refused with 409 while a reviewed application of the draft is active, and with 400 for a draft that is not `open` or `submitted`.

#### Scenario: Curator rejects a draft
- **WHEN** a curator rejects a submitted draft
- **THEN** the draft becomes `rejected` with the curator as `decided_by` and no queued operation is applied

### Requirement: Alias suggestion operations need individual decisions
The system SHALL NOT let draft operation tools or routes revise or remove an `alias_suggestion` operation, SHALL refuse to approve, reject, withdraw or apply a draft while any of its alias suggestions is still pending, and SHALL skip alias suggestions when replaying a draft.

#### Scenario: Rejecting a draft with a pending alias suggestion
- **WHEN** a curator rejects a draft holding a pending alias suggestion
- **THEN** the rejection is refused with a message to review alias suggestions individually first

### Requirement: Draft-level review evidence
The system SHALL let only a draft's creator replace the draft's review evidence through `set_draft_review_evidence(draft_id, evidence, expected_revision)` while the draft is `open` or `submitted` and has no active reviewed application. Evidence SHALL be plain text of at most 30,000 characters. The revision SHALL increase only when the evidence changes, and the call SHALL return the draft as `get_draft` does.

#### Scenario: Evidence over the limit
- **WHEN** the creator supplies 30,001 characters of evidence
- **THEN** the call is refused and the draft's revision is unchanged

#### Scenario: Another user supplies evidence
- **WHEN** a writer who did not create the draft calls `set_draft_review_evidence`
- **THEN** the call is refused saying only the draft creator can supply review evidence

### Requirement: Per-operation evidence
The system SHALL let only a draft's creator replace one operation's evidence through `set_operation_evidence(draft_id, operation_ref, evidence, expected_revision)` while the draft is `open` or `submitted`, returning `{draft_id, operation_ref, revision}`. The list SHALL hold at most 5 items, and an empty list SHALL remove the operation's evidence.

#### Scenario: Code evidence for a link
- **WHEN** the creator sets one `code` item with `path: "src/exports/schedule.py"`, `lines: "40-52"`, an excerpt and the claim "Weekly schedules trigger an export job"
- **THEN** `get_draft` shows that item on the operation and the draft's revision has increased

#### Scenario: Six items
- **WHEN** the creator supplies six evidence items for one operation
- **THEN** the call is refused saying at most 5 evidence items are allowed per operation

### Requirement: Evidence item shape
The system SHALL require each operation evidence item to have a `kind` of `code`, `ui`, `doc`, `media` or `other`, a one-line `claim` of 1 to 200 characters, an optional `excerpt` of at most 1,500 characters, and one location: a repository-relative `path` of at most 300 characters (with optional `lines` such as `40-52` and a `commit` of 7 to 40 hex characters), a `url` of at most 500 characters starting with `http://` or `https://`, or, for `media` items only, a `media_id`.

#### Scenario: Absolute path
- **WHEN** the creator supplies an item whose `path` starts with `/` or contains a `..` segment
- **THEN** the call is refused because the path must be relative to the repository root

#### Scenario: Lines without a path
- **WHEN** an item carries `lines` and a `url` but no `path`
- **THEN** the call is refused

### Requirement: Media evidence
The system SHALL refuse media evidence whose `media_id` does not name stored media, SHALL fill an empty `excerpt` of a media item with the media's alt text and caption, and, once the draft is applied, SHALL attach that media to the statements or entities the operation wrote. A failure to attach media SHALL NOT undo the applied knowledge.

#### Scenario: Screenshot evidence on an applied draft
- **WHEN** a draft whose `upsert_statement` operation carries `media` evidence is approved
- **THEN** the screenshot is attached to the statement that operation created

### Requirement: Draft source metadata
The system SHALL let only the creator attach pull request metadata (`repository`, `pull_request`, `merged_commit`, `workflow_run_id`, `workflow_run_attempt`) to an undecided draft through `attach_draft_source(draft_id, source, expected_revision)`, and let a drafter find their own draft by it through `find_my_draft_by_source(source)` (`{draft: null}` when none matches). A source SHALL belong to at most one draft per creator and SHALL NOT supply source contents to the reviewer.

#### Scenario: Source already used
- **WHEN** a creator attaches a source identical to one on another of their drafts
- **THEN** the call is refused with an error naming the draft that owns it

### Requirement: Stale assessments
The system SHALL mark a review assessment `stale` whenever the draft's current revision differs from the revision the assessment was made against, in `get_draft`, `get_draft_review_run` and the `GET /api/drafts` summary.

#### Scenario: Evidence changed after review
- **WHEN** the creator changes an operation's evidence after a review attempt completed
- **THEN** the draft's `review_assessment.stale` is `true`

### Requirement: Review settings
The system SHALL keep the review mode (`off`, `review-only`, `review-and-apply`), the automatic-application policy (`auto_apply`: `clean` or `with_corrections`), reviewer account, application gate (`application_enabled`), provider (`claude` or `openai`), model ID and reasoning effort in saved instance settings, defaulting to mode `off`, `auto_apply` `clean` and the gate off, and SHALL disable review rather than fall back to environment values when saved settings are unreadable.

#### Scenario: Fresh instance
- **WHEN** an admin opens the draft review settings on a new instance
- **THEN** the mode is `off`, `auto_apply` is `clean`, `application_enabled` is `false` and saving `off` with no model or reviewer is allowed

### Requirement: Reading review settings
The system SHALL return through `GET /api/draft-review/settings`, to any authenticated caller, the effective settings, readiness (`ready`, `issues`), provider availability, `can_review` and `can_configure`, and to admins also the active writers and admins eligible as reviewer.

#### Scenario: Writer reads the settings
- **WHEN** a writer reads the draft review settings
- **THEN** the response has `can_review: true`, `can_configure: false` and an empty `reviewers` list

### Requirement: Saving review settings
The system SHALL accept `PATCH /api/draft-review/settings` only from an admin, with `mode`, `auto_apply`, `provider`, `model`, optional `reasoning_effort`, `reviewer_id`, `application_enabled`, `revision` and `model_revision`, saving controls and model selection atomically and answering 409 for a stale revision. A mode other than `off` SHALL require a model ID, provider credentials and an active real writer or admin as reviewer. Saving SHALL NOT start any review.

#### Scenario: Concurrent admin saves
- **WHEN** two admins save settings from the same loaded revision
- **THEN** the first save succeeds and the second returns 409

#### Scenario: Enabling review without a reviewer
- **WHEN** an admin saves mode `review-only` with no reviewer selected
- **THEN** the save is refused naming the missing independent reviewer

#### Scenario: Choosing corrected approvals
- **WHEN** an admin saves `auto_apply: with_corrections`
- **THEN** later `changes_suggested` reviews in `review-and-apply` make their corrections and apply the draft

### Requirement: Starting a review on request
The system SHALL let an identified real writer or admin start or fetch a review through `request_draft_review(draft_id, rerun)` (HTTP `POST /request-draft-review`, not on MCP) and `POST /api/drafts/{id}/review` (always a rerun, returning `{review: ...}`). Without `rerun` the latest attempt SHALL be returned; with it a new attempt SHALL start, unless one is running, which SHALL be returned instead.

#### Scenario: Rerun while running
- **WHEN** a curator requests a rerun while an attempt for the draft is running
- **THEN** the running attempt is returned and no second attempt starts

#### Scenario: Reviewing an open draft
- **WHEN** a curator requests review of an `open` draft
- **THEN** the request is refused saying only submitted drafts can be internally reviewed

### Requirement: Review request refusals
The system SHALL refuse a review request while the mode is `off`, when no model ID is set, when the selected provider lacks credentials (before any attempt is recorded), and for a draft that is not `submitted`.

#### Scenario: Missing credentials
- **WHEN** a curator requests a review while the selected provider has no credentials
- **THEN** the request is refused and no attempt is recorded on the draft

### Requirement: Review attempt record
The system SHALL record each review attempt (id `drv_` plus 12 hex characters), retrievable through `get_draft_review_run(run_id)` and shown as the draft's latest `review_assessment`, with `status` (`running`, `completed`, `failed`, `paused`), `mode`, `draft_revision`, `stale`, `provider`, `model`, `reviewer_id`, settings revisions, `label`, `rationale`, `questions`, `corrections`, `contradictions`, `attempt`, `retries`, `answers`, `application`, `detail` and `review_id`.

#### Scenario: Completed advisory attempt
- **WHEN** a `review-only` attempt finishes with a `good` label
- **THEN** its record has `status: completed`, `label: good`, `application: unapplied` and no `review_id`

### Requirement: Settings captured per attempt
The system SHALL capture the mode, provider, model, reasoning effort, reviewer and both settings revisions when an attempt is admitted, and SHALL let an attempt edit, reject or apply a draft only when the saved settings at action time still equal the captured ones and both the captured and current mode are `review-and-apply`. Otherwise the attempt SHALL end as an advisory assessment.

#### Scenario: Settings change during a run
- **WHEN** an admin saves any settings change while a `review-and-apply` attempt is running
- **THEN** the attempt finishes as an advisory assessment and the draft stays `submitted`

### Requirement: Independent reviewer account
The system SHALL act for the configured reviewer account, resolved independently of the submitting caller, and SHALL fail the attempt when that account is not an active real writer or admin or is the draft's creator.

#### Scenario: Reviewer created the draft
- **WHEN** the configured reviewer account is the one that created the submitted draft
- **THEN** the attempt fails saying the reviewer must be independent of the draft creator

### Requirement: Reviewer input
The system SHALL give the reviewer one fresh structured-output model call per review part, with no tools and no author conversation, with the part's operations, their evidence and findings, the draft evidence, the affected knowledge, the link type glossary, correction tool schemas, curator answers, any previous failure, and up to 5 closest live statements per new statement text, best first, within 90,000 characters. Each of several parts SHALL also get an 8,000-character summary of the others.

#### Scenario: Context fills up
- **WHEN** adding another closest live statement would push the context over 90,000 characters
- **THEN** that statement is left out and no further closest statements are added

### Requirement: Affected knowledge
The system SHALL treat as affected knowledge the entities and statements an operation references by `ent_`/`stm_` id, the owners of names it references by `nam_` id, the entities whose names appear in its statement texts, the entities it upserts by name, and, only for `merge_entities`, `move_name`, `rename_name`, `delete_name` and `delete_entity`, the statements that mention an affected entity. Each SHALL be recorded as a precondition with a content fingerprint.

#### Scenario: Statement naming a live concept
- **WHEN** a draft's new statement text names the live concept "Workspace"
- **THEN** the Workspace entity is a knowledge precondition of the review

### Requirement: Draft size limits for review
The system SHALL review a draft too large for one context in connected parts: operations that change the same record, refer to one another's new statements with `@S:N`, or name an entity another operation creates SHALL share a part, packed in operation order into parts that each fit. A connected group whose context without closest statements exceeds 90,000 characters SHALL produce a `reject` assessment asking to narrow the draft, without a model call.

#### Scenario: Draft touching 31 records
- **WHEN** a submitted draft adds a batch of invoice statements and, separately, a workspace concept, together affecting 31 records
- **THEN** the draft is reviewed in two parts and no attempt fails for its size

### Requirement: Reviewable operation families
The system SHALL review only drafts whose operations are all among `upsert_entity`, `upsert_statement`, `upsert_statements`, `patch_statement`, `replace_text`, `upsert_name`, `move_name`, `rename_name`, `merge_entities`, `merge_statements`, `delete_name`, `delete_entity`, `delete_statement`, `add_links`, `remove_links`, `add_entity_links` and `remove_entity_links`. Any other operation kind SHALL produce a `reject` assessment naming the kinds, without a model call.

#### Scenario: Draft with a glossary edit
- **WHEN** a submitted draft contains an `upsert_link_type` operation
- **THEN** the assessment is `reject` with a rationale naming `upsert_link_type` and no model is called

### Requirement: Assessment shape
The system SHALL accept a model assessment only when it has a rationale of 1 to 6,000 characters, at most 12 questions, 12 corrections and 8 contradictions, and a consistent label: `good` and `reject` carry no corrections, questions or contradictions; `changes_suggested` carries corrections and no questions; `needs_context` carries questions and no contradictions. Invalid, incomplete or refused output and provider errors SHALL fail the attempt.

#### Scenario: Good label with corrections
- **WHEN** the model returns label `good` together with a correction
- **THEN** the attempt fails and no review is recorded

### Requirement: Review call limits
The system SHALL bound each review model call by the saved review limits, defaulting to 6,000 output tokens, a 90-second request timeout and no provider retries, and SHALL never fall back to another provider.

#### Scenario: Provider times out
- **WHEN** the provider does not answer within the request timeout
- **THEN** the attempt fails and records the failure in its `detail`

### Requirement: Correction validation
The system SHALL validate every correction before publishing an assessment in any mode: each carries only its action's fields and names an existing `operation_ref` within the reviewed part, `append` instead naming a reviewable tool and a JSON object payload; a struck operation takes no other correction; and every changed or appended payload binds to its tool's parameters with strict types. An invalid correction SHALL fail the attempt with no label and a detail naming the problem.

#### Scenario: Correction for an unknown operation
- **WHEN** the model proposes editing an `operation_ref` the draft does not contain
- **THEN** the attempt fails and its record carries no label

### Requirement: Draft statement references in corrections
The system SHALL fail an attempt whose correction uses a bare `@N` outside an `upsert_statements` batch or past the end of its batch, or an `@S:N` that names no statement of the draft's `upsert_statements` operation at seq `S`, saying how the statement is named.

#### Scenario: Link to a batch statement written as a bare reference
- **WHEN** the model appends an `add_links` correction whose target is `@0` instead of `@3:0`
- **THEN** the attempt fails saying that outside a batch the statement is named as `@<seq>:<index>`

### Requirement: Corrections that remove the whole draft
The system SHALL fail an attempt whose corrections strike every operation of the draft and append none, saying that a draft which should not land is a reject.

#### Scenario: Only operation struck
- **WHEN** the reviewer returns `changes_suggested` striking the one operation of a draft
- **THEN** the attempt fails and nothing is applied

### Requirement: Review-only mode is advisory
The system SHALL, in `review-only` mode, publish the assessment without editing operations, recording an authoritative review, rejecting, applying or waiting for an answer; the draft SHALL stay `submitted` with `application: unapplied`, including when the label is `reject` or `needs_context`.

#### Scenario: Advisory reject
- **WHEN** a `review-only` attempt returns label `reject`
- **THEN** the draft remains `submitted` and awaits a curator

### Requirement: Application gate
The system SHALL make no automatic edit, question, rejection or application in `review-and-apply` mode while the saved `application_enabled` gate is off; the attempt SHALL complete as an assessment with `application: unapplied` and a detail saying the gate is disabled. Drafts containing alias suggestions SHALL likewise receive only an advisory assessment.

#### Scenario: Gate off
- **WHEN** a `review-and-apply` attempt labels a draft `good` while `application_enabled` is `false`
- **THEN** the draft stays `submitted` and the attempt's detail says the reviewed application gate is disabled

### Requirement: Review-and-apply outcomes
The system SHALL, in `review-and-apply` mode with the gate on, record an authoritative review and act on it: a `reject` SHALL finalize the draft as `rejected` with `application: rejected`; a `good` draft SHALL be recorded `accepted` and applied through reviewed application with `application: applied`. A `changes_suggested` assessment SHALL, under `auto_apply` `clean`, end `held`, making no correction and recording no review.

#### Scenario: Changes suggested under the clean policy
- **WHEN** the reviewer returns `changes_suggested` with `auto_apply` `clean`
- **THEN** the draft stays `submitted` and unchanged, and the attempt ends `held` with its corrections

#### Scenario: Changes suggested and applied
- **WHEN** the reviewer returns `changes_suggested` striking a duplicate statement operation with `auto_apply` `with_corrections`
- **THEN** the operation is struck, a `refined` review is recorded against the new revision and the draft is applied and becomes `approved`

#### Scenario: Correction leaves a phrasing finding
- **WHEN** a corrected draft still holds a statement the phrasing check would refuse
- **THEN** the attempt fails naming the operation and finding, and none of the corrections remain

### Requirement: Correction batch safety
The system SHALL roll back every automatic correction and fail the attempt when the corrected draft still has operation findings or a correction touches knowledge the review did not inspect.

#### Scenario: Correction touches uninspected knowledge
- **WHEN** an appended correction links to a live statement the reviewer was not given
- **THEN** the attempt fails and none of its corrections remain on the draft

### Requirement: Exact-state checks before automatic action
The system SHALL, before any automatic action, verify that the draft is still `submitted`, its revision is unchanged, and the affected and supporting knowledge records read for the review still match; otherwise the attempt SHALL fail asking for a rerun.

#### Scenario: Live statement changes during review
- **WHEN** a closest live statement given to the reviewer is edited before the attempt acts
- **THEN** the attempt fails saying supporting knowledge changed during review and nothing is applied

### Requirement: Questions for a person
The system SHALL, when a `review-and-apply` attempt with the gate on returns `needs_context`, record an authoritative `needs_context` review carrying the questions, set `application: needs_human`, file a knowledge gap naming the draft and the questions, and leave the draft `submitted`.

#### Scenario: Reviewer asks whether two concepts are the same
- **WHEN** the reviewer cannot tell whether a new concept "Billing workspace" is the live concept "Workspace"
- **THEN** the draft stays submitted, its assessment lists the question with `application: needs_human`, and an open knowledge gap names the draft

### Requirement: Answering the reviewer
The system SHALL accept `POST /api/drafts/{id}/review/answer` with `run_id` and an `answer` of 1 to 6,000 characters from a real writer or admin only when that run is the draft's latest, has `application: needs_human` and the draft has not changed since; it SHALL store the answer with the curator's id and the questions it answers, carry all earlier answers to every later attempt, start a new attempt and return `{review: ...}`.

#### Scenario: Answer after the draft changed
- **WHEN** a curator answers a question after the draft's evidence was changed
- **THEN** the answer is refused saying the draft changed after the reviewer asked

#### Scenario: Answer to an older run
- **WHEN** a curator answers with a `run_id` that is no longer the draft's latest attempt
- **THEN** the answer is refused asking to reload

### Requirement: Contradictions resolved in favour of the draft
The system SHALL, after automatically applying a draft whose assessment lists contradictions, file one open knowledge gap per contradiction naming the draft and the contradicted live statement id.

#### Scenario: New statement contradicts a live one
- **WHEN** an applied draft's assessment lists a contradiction with live statement `stm_…` and its resolution
- **THEN** an open knowledge gap references the draft and that statement

### Requirement: Retry sweep
The system SHALL, every 60 seconds while the mode is not `off`, credentials are present and the AI budget does not pause draft review, retry a submitted draft's latest attempt that failed without recording a review, once 5 minutes times 2 to the power of its retry count have passed since it finished, at most 5 retries, and only while that failure is under 160 minutes old. Each retry SHALL be a fresh first attempt. `MYCELIUM_DISABLE_REVIEW_SWEEP=1` SHALL disable the sweep.

#### Scenario: Failure older than the window
- **WHEN** a draft's latest attempt failed more than 160 minutes ago, as in a restored copy of another instance
- **THEN** the sweep does not retry it and the draft is listed in the backlog

### Requirement: Budget-paused attempts
The system SHALL mark an attempt stopped by the monthly AI budget as `paused` rather than failed, without consuming a retry or triggering a rerun, and the sweep SHALL resume it with its attempt and retry counts once the budget allows.

#### Scenario: Budget exhausted mid-month
- **WHEN** an attempt starts after the month's AI budget is spent
- **THEN** its status is `paused` and it is not in the backlog

### Requirement: Interrupted attempts
The system SHALL, at startup, mark attempts left `running` as `failed` so the sweep retries them, and SHALL restore the actual outcome (`applied`, `rejected` or `needs_human`) from durable review and application receipts for attempts that recorded one before the interruption. No startup step SHALL start model work or replay an uncommitted application.

#### Scenario: Restart after the application committed
- **WHEN** the process stops after a reviewed application committed but before the attempt was finalized
- **THEN** after restart the attempt reads `application: applied` and is not retried

### Requirement: Review backlog
The system SHALL let an admin list through `GET /api/draft-review/backlog` the submitted drafts the current configuration has not reached, oldest first and without alias-suggestion-only drafts, as `{draft_ids, estimated_cost_usd, job}`: their number times the 30-day mean review cost (`null` unpriced) and the latest job. `POST /api/draft-review/backlog`, with an optional `budget_usd` above 0, SHALL start that job and return `{job}`, refused while the mode is `off` or a job is unfinished.

#### Scenario: Switching review on
- **WHEN** an admin turns review on with three drafts submitted while it was off and posts the backlog
- **THEN** the job reviews those three drafts one at a time, oldest first, and finishes with `reviewed: 3`

### Requirement: Backlog membership
The system SHALL count a submitted draft as backlog when its latest attempt is missing, failed without a recorded review, a stale or other-mode advisory assessment, any unapplied assessment without a recorded review while the mode is `review-and-apply`, or a question or held corrections whose draft changed since; running and paused attempts SHALL NOT count.

#### Scenario: Advisory assessment after switching mode
- **WHEN** the mode changes from `review-only` to `review-and-apply`
- **THEN** drafts holding only a `review-only` assessment appear in the backlog

#### Scenario: Held corrections
- **WHEN** a draft's latest attempt is `held` and the draft has not changed since
- **THEN** the draft is not in the backlog

### Requirement: Recording a review externally
The system SHALL offer real writers and admins, over HTTP only, `record_draft_review` with outcome `accepted`, `refined`, `rejected` or `needs_context`, refused unless the draft is `submitted` and the revision and every operation-derived precondition still match, and refused for `accepted` or `refined` while questions or operation findings remain. A `rejected` outcome SHALL finalize the draft as `rejected`.

#### Scenario: Accepting with an open question
- **WHEN** a curator records an `accepted` review with one unresolved question
- **THEN** the call is refused saying accepted reviews cannot contain unresolved findings

### Requirement: Applying a recorded review
The system SHALL offer real writers and admins, over HTTP only, `apply_reviewed_draft(draft_id, review_id)`, which requires the application gate on, a `submitted` draft, and an `accepted` or `refined` review without unresolved questions at the draft's current revision whose knowledge preconditions still hold, and which returns an already committed receipt with `recovered: true` instead of applying twice.

#### Scenario: Knowledge changed after the review
- **WHEN** `apply_reviewed_draft` is called after an entity the review fingerprinted was edited
- **THEN** the application is recorded as failed and refused saying affected knowledge changed after the recorded review

#### Scenario: Recovering a committed application
- **WHEN** `apply_reviewed_draft` is called again for a review whose application already committed
- **THEN** the stored receipt is returned with `recovered: true` and nothing is replayed

### Requirement: Manual approval
The system SHALL let a real writer or admin approve an `open` or `submitted` draft through `POST /api/drafts/{id}/approve`, independently of review mode and the application gate, by recording an `accepted` review by that curator ("Approved by hand.") and claiming the application in one transaction before replaying, and SHALL return `{ok: true, applied, skipped, results}`. Approval SHALL answer 409 while a reviewer's application of the draft is active.

#### Scenario: Drafter approves their own draft
- **WHEN** a drafter calls the approve route for their own draft
- **THEN** the response is 403

### Requirement: Manual approval recovery
The system SHALL, when an earlier manual approval committed the knowledge but did not finalize the draft, finalize the recorded result on the next approval instead of replaying the operations again.

#### Scenario: Crash after the substrate commit
- **WHEN** the process stops after a manual approval committed its knowledge and the curator approves again after restart
- **THEN** the draft becomes `approved` and no operation is applied twice

### Requirement: All-or-nothing replay
The system SHALL apply a draft by replaying its operations in `seq` order as the applying principal in one substrate transaction, restoring both vector indexes and changing nothing when any operation fails or any statement is refused. When statements are refused, approval SHALL answer 422 with a message and a `rejections` list of `seq`, `kind`, `text` and `reasons` per statement. Phrasing SHALL be checked at application, not when an operation is queued.

#### Scenario: One statement breaks a phrasing rule
- **WHEN** a curator approves a draft in which one of five batched statements violates a phrasing rule
- **THEN** none of the five statements is written, the draft keeps its status, and the 422 response lists the refused statement with its reasons

### Requirement: Cross-operation references
The system SHALL resolve a payload value of the form `@<seq>:<index>` at replay to the id of the statement created at position `<index>` by the `upsert_statements` operation at `<seq>`, SHALL leave bare `@N` values to the batch tool, and SHALL report an operation finding for a reference to a missing, later or non-batch operation or an out-of-range position.

#### Scenario: Link to a statement from an earlier batch
- **WHEN** an `add_links` operation at seq 3 targets `@1:0` and seq 1 is an `upsert_statements` batch
- **THEN** at replay the link targets the id of the first statement that batch created

### Requirement: Tolerating obsolete operations at replay
The system SHALL skip, rather than fail on, an operation whose tool no longer exists and drop payload keys the tool no longer accepts when replaying a draft, while reporting both as operation findings (`obsolete_tool`, `unknown_parameters:…`) that block recording an accepted review and reviewed application but not manual approval.

#### Scenario: Old draft with a removed tool
- **WHEN** a curator approves a draft containing an operation for a tool that has since been removed
- **THEN** that operation is reported as skipped and the rest of the draft is applied

### Requirement: Applying a draft resolves its gaps
The system SHALL resolve, in the same transaction that applies a draft, every open knowledge gap filed about that draft, whether it was approved by hand or applied by the reviewer. Contradiction gaps filed after an automatic application SHALL stay open.

#### Scenario: Answered question lands
- **WHEN** a draft whose question gap was answered is applied
- **THEN** that question gap is resolved

### Requirement: Rejection gaps
The system SHALL file a knowledge gap naming the draft for every automatic rejection, whether by a `reject` label or after two failed attempts.

#### Scenario: Reviewer rejects a draft
- **WHEN** a `review-and-apply` attempt rejects a draft
- **THEN** an open knowledge gap says the draft was rejected by the internal reviewer and gives its rationale

### Requirement: Quarantine turns review off
The system SHALL treat the review mode as `off` while the instance is quarantined, without changing the saved settings (see the `operations` capability).

#### Scenario: Submission during quarantine
- **WHEN** a draft is submitted while the instance is quarantined and review is saved as `review-and-apply`
- **THEN** no review attempt starts

### Requirement: Rerun and rejection after a failed attempt
The system SHALL, in `review-and-apply` mode with the gate on, start one more attempt (`attempt: 2`) when an attempt fails without recording a review, passing the failure to the reviewer; when that second attempt also fails, the draft SHALL be rejected with an authoritative `rejected` review and a knowledge gap, unless the failure came from the model provider, which SHALL leave the draft `submitted`.

#### Scenario: Invalid correction twice
- **WHEN** both attempts on a draft fail because a correction leaves a phrasing finding
- **THEN** the draft is rejected with a rationale saying automatic review failed twice

#### Scenario: Provider outage
- **WHEN** both attempts fail with a model provider error
- **THEN** the draft remains `submitted`

### Requirement: Part-wise review outcome
The system SHALL act on a draft reviewed in parts only as a whole: a `reject` from any part SHALL reject the draft with that part's rationale, otherwise a `needs_context` from any part SHALL make the draft wait with that part's questions, otherwise every part's corrections SHALL be held together or, under `auto_apply` `with_corrections`, applied together and the draft applied.

#### Scenario: One part rejects
- **WHEN** a draft is reviewed in two parts and the second part returns `reject`
- **THEN** no operation of either part is applied and the draft is rejected with a rationale naming part 2

#### Scenario: Both parts correct their own operations
- **WHEN** each of two parts returns `changes_suggested` editing one of its own operations, with `auto_apply` `with_corrections`
- **THEN** both edits are applied in one transaction and the draft is applied

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

### Requirement: Accepting held corrections
The system SHALL accept `POST /api/drafts/{id}/review/accept` with `run_id` and optional `corrections` from a real curator, refused unless that run is the draft's latest, ended `held`, and the draft has not changed since. It SHALL then make the corrections and approve the draft as the curator, and the run SHALL end `applied`.

#### Scenario: Accepting the suggestion
- **WHEN** a curator accepts a held review without supplying corrections
- **THEN** the reviewer's corrections are made, the draft is approved and the run ends `applied`

#### Scenario: Draft changed since the review
- **WHEN** a curator accepts after the draft's revision changed
- **THEN** the request is refused asking for the review to run again, and the draft is unchanged

### Requirement: Restated tool names on corrections
The system SHALL accept a correction other than `append` that also names the tool of the operation it targets, dropping the redundant tool name instead of failing the attempt.

#### Scenario: Strike naming its own tool
- **WHEN** the model strikes an `upsert_statements` operation and also sets `tool_name: "upsert_statements"`
- **THEN** the correction is applied as a plain strike

### Requirement: Corrections a curator accepts
The system SHALL make the corrections a curator supplies, or the held run's own when none are supplied, after validating them as the reviewer's are, in one transaction, refusing the result if it leaves an operation finding. The run's detail SHALL say whether the corrections were the reviewer's or edited.

#### Scenario: Accepting an edited suggestion
- **WHEN** a curator accepts with one correction whose text differs from the reviewer's
- **THEN** the curator's correction is made instead and the detail says the corrections were edited

### Requirement: Precise corrections
The system SHALL let a correction change one thing: `edit` sets one statement's `text` or `kind`, or an entity's `description`; `add_link` and `drop_link` name one link by both ends, type and, where needed, its `when` tree; `drop_statement` names one batch statement; `strike` names an operation; `append` adds one. Indices and `@` references SHALL name the draft as submitted.

#### Scenario: Editing a statement by index
- **WHEN** a correction edits statement 2 of an `upsert_statements` batch and another drops statement 0
- **THEN** the edit lands on the statement submitted as 2

#### Scenario: Correction to a batch link
- **WHEN** a correction adds a link from a batch's `@0` to live statement `stm_…`
- **THEN** the link is added to statement 0 of that batch and nothing else changes

### Requirement: Corrections leave everything else intact
The system SHALL move later statements and every `@N` and `@S:N` reference with a dropped statement, refuse to drop a statement another operation still names, and refuse a correction set whose result changes, renumbers or drops any operation, statement or link it does not name.

#### Scenario: Editing one statement of a batch
- **WHEN** a correction edits the text of statement 1 of a four-statement batch whose statements carry links and conditions
- **THEN** only that statement's text changes and every other statement, link and condition is as submitted

#### Scenario: Dropping a statement other statements refer to
- **WHEN** a correction drops statement 0 of a batch whose statement 3 has an incoming link from `@1` with condition `@2`
- **THEN** the link becomes from `@0` with condition `@1`, still naming the same statements

#### Scenario: Dropping a statement still named
- **WHEN** a correction drops a batch statement that another operation names as `@S:N`
- **THEN** the attempt fails saying which operation still names it

### Requirement: Applying corrections automatically
The system SHALL, under `auto_apply` `with_corrections`, apply a `changes_suggested` assessment's corrections in one draft transaction, record a `refined` review against the corrected revision and apply the draft.

#### Scenario: Corrected draft lands
- **WHEN** the reviewer returns `changes_suggested` editing one statement's text with `auto_apply` `with_corrections`
- **THEN** the edited text is applied and the attempt ends `applied`
