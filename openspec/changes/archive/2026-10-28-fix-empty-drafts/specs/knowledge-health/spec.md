## MODIFIED Requirements

### Requirement: Health counts
The system SHALL answer `GET /api/knowledge-health` for any authenticated user with `counts` holding `statements`, `entities`, `isolated`, `unmentioned`, `undescribed`, `unused`, `unlabelled`, `labelling_failed`, `open_gaps`, `pending_drafts`, `open_drafts`, `out_of_date_documents` and `old_media`, each computed from current data on every request.

#### Scenario: Curator opens knowledge health
- **WHEN** a signed-in reader requests `GET /api/knowledge-health`
- **THEN** the response carries every count in `counts`

#### Scenario: Unauthenticated request
- **WHEN** a caller without a session or token requests the health counts while authentication is on
- **THEN** the request is refused

### Requirement: Queue counts
The system SHALL count `labelling_failed` as unlabelled statements whose last labelling attempt recorded an error, `open_gaps` as knowledge gaps neither resolved nor dismissed, `pending_drafts` as submitted drafts awaiting a decision, `open_drafts` as drafts still open with their authors, `out_of_date_documents` as generated documents whose freshness is out of date, and `old_media` as media flagged old (0 when no media store is configured).

#### Scenario: Draft decided
- **WHEN** a submitted draft is approved
- **THEN** `pending_drafts` no longer counts it

#### Scenario: Draft still with its author
- **WHEN** a drafter has an open draft they have not submitted
- **THEN** `open_drafts` counts it and `pending_drafts` does not

## ADDED Requirements

### Requirement: Drafts count on the health screen
The Knowledge health screen SHALL show `pending_drafts` as its drafts count, labelled as drafts awaiting a decision, with `open_drafts` beside it as the drafts still open with their authors.

#### Scenario: Drafts waiting and open
- **WHEN** two drafts are submitted and three are open with their authors
- **THEN** the drafts count reads 2 and notes 3 still open with their authors
