## MODIFIED Requirements

### Requirement: Review settings
The system SHALL keep the review mode (`off`, `review-only`, `review-and-apply`), the automatic-application policy (`auto_apply`: `clean` or `with_corrections`), reviewer account, application gate (`application_enabled`), provider (`claude` or `openai`), model ID and reasoning effort in saved instance settings, defaulting to mode `off`, `auto_apply` `clean` and the gate off, and SHALL disable review rather than fall back to environment values when saved settings are unreadable.

#### Scenario: Fresh instance
- **WHEN** an admin opens the draft review settings on a new instance
- **THEN** the mode is `off`, `auto_apply` is `clean`, `application_enabled` is `false` and saving `off` with no model or reviewer is allowed

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

### Requirement: Assessment shape
The system SHALL accept a model assessment only when it has a rationale of 1 to 6,000 characters, at most 12 questions, 12 corrections and 8 contradictions, and a consistent label: `good` and `reject` carry no corrections, questions or contradictions; `changes_suggested` carries corrections and no questions; `needs_context` carries questions and no contradictions. Invalid, incomplete or refused output and provider errors SHALL fail the attempt.

#### Scenario: Good label with corrections
- **WHEN** the model returns label `good` together with a correction
- **THEN** the attempt fails and no review is recorded

### Requirement: Correction validation
The system SHALL validate every correction before publishing an assessment in any mode: each carries only its action's fields and names an existing `operation_ref` within the reviewed part, `append` instead naming a reviewable tool and a JSON object payload; a struck operation takes no other correction; and every changed or appended payload binds to its tool's parameters with strict types. An invalid correction SHALL fail the attempt with no label and a detail naming the problem.

#### Scenario: Correction for an unknown operation
- **WHEN** the model proposes editing an `operation_ref` the draft does not contain
- **THEN** the attempt fails and its record carries no label

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

### Requirement: Backlog membership
The system SHALL count a submitted draft as backlog when its latest attempt is missing, failed without a recorded review, a stale or other-mode advisory assessment, any unapplied assessment without a recorded review while the mode is `review-and-apply`, or a question or held corrections whose draft changed since; running and paused attempts SHALL NOT count.

#### Scenario: Advisory assessment after switching mode
- **WHEN** the mode changes from `review-only` to `review-and-apply`
- **THEN** drafts holding only a `review-only` assessment appear in the backlog

#### Scenario: Held corrections
- **WHEN** a draft's latest attempt is `held` and the draft has not changed since
- **THEN** the draft is not in the backlog

### Requirement: Part-wise review outcome
The system SHALL act on a draft reviewed in parts only as a whole: a `reject` from any part SHALL reject the draft with that part's rationale, otherwise a `needs_context` from any part SHALL make the draft wait with that part's questions, otherwise every part's corrections SHALL be held together or, under `auto_apply` `with_corrections`, applied together and the draft applied.

#### Scenario: One part rejects
- **WHEN** a draft is reviewed in two parts and the second part returns `reject`
- **THEN** no operation of either part is applied and the draft is rejected with a rationale naming part 2

#### Scenario: Both parts correct their own operations
- **WHEN** each of two parts returns `changes_suggested` editing one of its own operations, with `auto_apply` `with_corrections`
- **THEN** both edits are applied in one transaction and the draft is applied

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Redundant tool names on corrections
**Reason**: `revise` is gone; the rule now covers every correction other than `append`.
**Migration**: See "Restated tool names on corrections".
