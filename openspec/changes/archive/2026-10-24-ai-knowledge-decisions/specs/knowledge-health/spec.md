## MODIFIED Requirements

### Requirement: Claiming curation work
The system SHALL provide `claim_curation_work(kind, limit=5)`, advertised over MCP, for callers with at least the drafter role, leasing up to `limit` (0 to 20) items of `kind` (`isolated`, `unnamed`, `rephrase`, `gap` or `question`) for 30 minutes and returning `kind`, `items`, `renewed`, `expires_at` and `link_types` (the link vocabulary with each type's description and direction).

#### Scenario: Agent claims isolated statements
- **WHEN** a drafter calls `claim_curation_work("isolated", limit=3)`
- **THEN** up to three isolated statements are leased to it for 30 minutes

#### Scenario: Reader tries to claim
- **WHEN** a reader calls `claim_curation_work`
- **THEN** the call is refused with a role error

### Requirement: Curation item shape
The system SHALL give each claimed item `id` (the statement id for `isolated` and `unnamed`, the gap id for `rephrase`, `gap` and `question`), `kind`, `text` (the statement's or the gap's), `statement` (`id`, `kind`, `text` and `concepts` as `{id, name}`, or null for a gap about no statement) and `neighbours`: up to five nearest statements as `{id, kind, text, score}`, excluding the item's own statement.

#### Scenario: Gap about no statement
- **WHEN** an agent claims a `gap` item whose gap names no statement
- **THEN** the item's `statement` is null

### Requirement: Curation work selection
The system SHALL offer items in id order, leaving out items another caller holds under an unexpired lease, items an undecided draft already covers (for statements, a pending link or alias; for gaps other than questions, a gap tied to an undecided draft), and items whose last look still holds; a `rephrase` item is an open gap about a statement whose text starts with the connect pass's rephrase prefix, a `question` item is defined under Question items, and a `gap` item is any other open gap.

#### Scenario: Second agent claims
- **WHEN** one drafter holds an isolated statement and another drafter claims isolated work
- **THEN** the held statement is not offered to the second drafter

### Requirement: Curation release
The system SHALL provide `release_curation_work(item_ids, outcome, ...)` for the same callers, freeing the caller's held items with an `outcome` and answering `released` and `outcome`. It MUST refuse the whole release, naming them, when any item is not held by the caller, or when the outcome is not one the item's kind takes. An expired lease SHALL still count as held until a claim of any kind clears expired leases or an admin frees the caller's claims.

#### Scenario: Release of another agent's item
- **WHEN** a drafter releases an item it does not hold
- **THEN** the release is refused with `not held by you:` and the item id

#### Scenario: Release after the lease expired
- **WHEN** a drafter releases an item 40 minutes after claiming it and nobody has claimed curation work since
- **THEN** the release succeeds and records the outcome

### Requirement: Release outcome rules
The system MUST require a `proposed` release to name a `draft_id` created by the caller, a `resolved` release to name an applied draft, and a `no_link` or `not_applicable` release to give a non-blank `reason` of at most 300 characters; it MUST refuse a `draft_id` on any other release, and an `answer` or `evidence` on any release but `answered`.

#### Scenario: Proposed without a draft
- **WHEN** a drafter releases items as `proposed` without a `draft_id`
- **THEN** the release is refused

#### Scenario: Someone else's draft
- **WHEN** a drafter releases items as `proposed` naming a draft another account created
- **THEN** the release is refused

#### Scenario: Resolved by an undecided draft
- **WHEN** a drafter releases a gap as `resolved` naming a draft that is not applied
- **THEN** the release is refused

### Requirement: Release memory
The system SHALL remember each `proposed`, `no_link`, `answered`, `resolved` or `not_applicable` release, in the same memory the connect pass uses, so the item is not offered again (to agents or as a next statement to connect) until the statement's text, a neighbour the claim offered, or a statement naming one of its concepts changes, or for a gap until its text or the statement it is about changes; a `skipped` item is offered again at once.

#### Scenario: Skipped item
- **WHEN** a drafter releases an item as `skipped`
- **THEN** the item is offered on the next claim

#### Scenario: No link, then the statement is edited
- **WHEN** an item released as `no_link` has its text edited
- **THEN** it is offered again

### Requirement: Curation summary
The system SHALL include in the health response `curation`: per work kind, the current holders (`claimed_by`, the holder's display name when known, `items`, `expires_at`), `attempted` (items still on the list someone has looked at) and `outcomes` counted by `looked` (the connect pass), `proposed`, `no_link`, `skipped`, `answered`, `resolved` and `not_applicable`.

#### Scenario: Agent holding work
- **WHEN** a drafter holds three isolated items
- **THEN** the isolated summary lists that drafter with `items: 3`

### Requirement: Listing knowledge gaps
The system SHALL list gaps at `GET /api/knowledge-gaps` for any authenticated user, newest first, filtered by `status` of `all` (default), `open`, `resolved` or `dismissed`, each with `id`, `text`, `status`, `created_at`, `created_by`, `resolved_at`, `resolved_by`, `dismissed_at`, `dismissed_by`, `closing_reason` (the reason an agent gave when it closed the gap, or null), `draft_id`, `statement_id` and `document_id`, plus `can_write` for the caller; any other status is answered 400.

#### Scenario: Listing open gaps
- **WHEN** a reader requests `GET /api/knowledge-gaps?status=open`
- **THEN** only gaps neither resolved nor dismissed are returned

### Requirement: Alias suggestions decided individually
The system MUST refuse to apply, reject or withdraw a draft while it holds a pending alias suggestion, refuse generic draft edits or operation deletions of a suggestion, never let the draft reviewer act on a draft holding suggestions beyond an advisory assessment unless `alias_decisions` is on, and close a suggestion-only draft once its last suggestion is decided (approved if any was accepted, otherwise rejected), whether a person or the reviewer decided it.

#### Scenario: Last suggestion rejected
- **WHEN** a human rejects the only pending suggestion in a suggestion-only draft
- **THEN** the draft is closed as rejected

#### Scenario: Applying with a pending suggestion
- **WHEN** a curator applies a draft that still holds a pending suggestion
- **THEN** the application is refused

#### Scenario: Reviewer decides the last suggestion
- **WHEN** `alias_decisions` is on and the reviewer in `review-and-apply` accepts the only suggestion in a suggestion-only draft
- **THEN** the draft is closed as approved

## ADDED Requirements

### Requirement: Question items
A `question` item SHALL be the newest open gap about a submitted, undecided draft whose latest review has `application: needs_human` and that has not changed since, and SHALL carry `question`: the `draft_id`, the draft's title, the `run_id` of the review that asked, its `questions` and its rationale.

#### Scenario: Reviewer question
- **WHEN** an agent claims a `question` item
- **THEN** the item carries the draft id, the asking run's id and the reviewer's questions

#### Scenario: Question after the draft changed
- **WHEN** a draft's reviewer asked a person and the draft was edited since
- **THEN** its gap is not offered as a `question` item

### Requirement: Outcomes per kind
The system SHALL accept `answered` and `skipped` for `question` items; `proposed`, `no_link`, `skipped`, `resolved` and `not_applicable` for `rephrase` and `gap` items; and `proposed`, `no_link` and `skipped` for `isolated` and `unnamed` items.

#### Scenario: Outcome the kind does not take
- **WHEN** a drafter releases an isolated statement as `resolved`
- **THEN** the release is refused

### Requirement: Closing a gap by release
A `resolved` release SHALL tie the gap to the named applied draft and resolve it, and a `not_applicable` release SHALL dismiss it, each stamping the releasing agent and the time as a person's status change does. The gap's `closing_reason` SHALL be the agent's reason until a person changes the gap's status.

#### Scenario: Agent finds a gap does not apply
- **WHEN** a drafter releases a gap as `not_applicable` with a reason
- **THEN** the gap is dismissed by that drafter and lists the reason as `closing_reason`

#### Scenario: Person reopens it
- **WHEN** a writer reopens a gap an agent dismissed
- **THEN** the gap is open and its `closing_reason` is null

### Requirement: Answering a reviewer question by release
An `answered` release SHALL take exactly one `question` item, a non-blank `answer` of at most 6,000 characters and one to five `evidence` items in the shape draft operation evidence takes, from an identified principal that did not create the draft. It SHALL record the answer on the asking review run as a curator's answer is recorded, with the agent as `answered_by` and its evidence, and start the next review attempt; the question's gap stays open until the draft is applied.

#### Scenario: Answer with evidence
- **WHEN** a drafter agent releases a question item as `answered` with an answer and a code excerpt
- **THEN** the review run stores the answer with the agent and its evidence, and a fresh review of the draft starts

#### Scenario: Answer without evidence
- **WHEN** a drafter agent releases a question item as `answered` with no evidence
- **THEN** the release is refused

#### Scenario: The draft's creator answers
- **WHEN** the principal that created the draft releases its question as `answered`
- **THEN** the release is refused
