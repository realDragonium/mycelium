## MODIFIED Requirements

### Requirement: Draft created outcome
The system SHALL answer a run that queued at least one operation with `outcome: draft_created`, `draft_id` (a `drf_…` id), `alias_draft_id` (or null), `submitted_for_review`, the queued `ops` (each with `op`, `payload`, `rationale`, `targets_existing`), `flagged`, `skipped_duplicates` and `trace`.

#### Scenario: Two new facts extracted
- **WHEN** ingest proposes two new statements and a link between them
- **THEN** the response has `outcome: draft_created` and a `draft_id`
- **AND** `ops` lists each queued operation with its rationale

### Requirement: Nothing to ingest outcome
The system SHALL answer `outcome: nothing_to_ingest` with a `reason` and `trace`, and create no draft, when every candidate was a duplicate (`all candidates were duplicates`), the model proposed no operation (`nothing extractable`), every proposed operation failed validation (`no valid ops survived validation; see flagged trace`), or no operation could be queued or the run degraded (a reason starting `degraded:`).

#### Scenario: Prose already known
- **WHEN** every fact in the text already exists as a statement and the model proposes no operation
- **THEN** the outcome is `nothing_to_ingest` with reason `all candidates were duplicates`
- **AND** no draft is created

#### Scenario: Only a flag
- **WHEN** the model flags a contradiction and every operation it proposed is dropped
- **THEN** the outcome is `nothing_to_ingest`, no draft is created and the trace's `flagged` names the contradiction

## ADDED Requirements

### Requirement: No empty drafts
The system SHALL create a draft for an ingest, connect or curation run only together with its first operation, in one transaction, so that no run leaves a draft without operations. When the first operation cannot be queued no draft SHALL remain; the next operation that can be queued opens the draft instead.

#### Scenario: First operation refused
- **WHEN** a run's first operation is refused as it is queued and its second is accepted
- **THEN** one draft exists, holding only the second operation
