# knowledge-health Specification

## Purpose
Show curators what in the knowledge base needs attention and give them, the server's connect pass and outside agents the means to work it off: health counts and lists, the AI connect pass, the claimable curation queue, knowledge gaps, alias suggestions and duplicate audits.

## Requirements

### Requirement: Health counts
The system SHALL answer `GET /api/knowledge-health` for any authenticated user with `counts` holding `statements`, `entities`, `isolated`, `unmentioned`, `undescribed`, `unused`, `unlabelled`, `labelling_failed`, `open_gaps`, `pending_drafts`, `out_of_date_documents` and `old_media`, each computed from current data on every request.

#### Scenario: Curator opens knowledge health
- **WHEN** a signed-in reader requests `GET /api/knowledge-health`
- **THEN** the response carries every count in `counts`

#### Scenario: Unauthenticated request
- **WHEN** a caller without a session or token requests the health counts while authentication is on
- **THEN** the request is refused

### Requirement: Health criteria
The system SHALL count and list a statement as `isolated` when no statement link leads from or to it and no link's `when` condition names it, as `unmentioned` when its text mentions no concept name or alias, and as `unlabelled` when it has no audience label; and a concept as `undescribed` when its description is empty or whitespace, and as `unused` when no statement mentions any of its names.

#### Scenario: Statement used only as a condition
- **WHEN** a statement has no links of its own but is the `when` condition of another link
- **THEN** it is not counted as isolated

#### Scenario: Concept with a blank description
- **WHEN** a concept's description is three spaces
- **THEN** it is counted as undescribed

### Requirement: Queue counts
The system SHALL count `labelling_failed` as unlabelled statements whose last labelling attempt recorded an error, `open_gaps` as knowledge gaps neither resolved nor dismissed, `pending_drafts` as drafts not yet decided (open or submitted), `out_of_date_documents` as generated documents whose freshness is out of date, and `old_media` as media flagged old (0 when no media store is configured).

#### Scenario: Draft decided
- **WHEN** a submitted draft is approved
- **THEN** `pending_drafts` no longer counts it

### Requirement: Statement health lists
The system SHALL page each statement list at `GET /api/knowledge-health/statements/{isolated|unmentioned|unlabelled}` in id order, taking `after` (an id) and `limit` (1 to 200, default 50), returning `filter`, `items` and `next_after` (null on the last page); each item carries `id`, `kind`, `text`, `links` (count), `mentions` (concept names in its text), `label_error`, `in_pending_draft` and `settled_at`.

#### Scenario: Paging isolated statements
- **WHEN** a client requests the isolated list with `limit=2` and more than two statements are isolated
- **THEN** two items come back in id order with `next_after` set to the second id

#### Scenario: Limit out of range
- **WHEN** a client requests a statement list with `limit=500`
- **THEN** the request is rejected as invalid

### Requirement: Pending-draft marking
The system SHALL mark a listed statement `in_pending_draft: true` when an undecided draft holds an `add_links` operation with an edge from or to it, or an alias suggestion whose evidence or proposal names it.

#### Scenario: Link already proposed
- **WHEN** an open draft proposes a link from an isolated statement
- **THEN** that statement's list item has `in_pending_draft: true`

### Requirement: Settled marking
The system SHALL report `settled_at` on a listed statement as the time the connect pass or an outside agent last looked at it, while that look still holds: the outcome was not `skipped`, the statement's text is unchanged, no statement weighed for it has changed or been deleted since, and no other statement naming one of its concepts has been written since. Otherwise `settled_at` is null.

#### Scenario: Neighbour changes after a look
- **WHEN** the connect pass looked at a statement and a statement it weighed for it is later edited
- **THEN** that statement's `settled_at` becomes null

### Requirement: Concept health lists
The system SHALL page each concept list at `GET /api/knowledge-health/entities/{undescribed|unused}` in id order with `after` and `limit` (1 to 200, default 50), each item carrying `id`, `name` (the preferred name, else the first name) and `description`.

#### Scenario: Listing undescribed concepts
- **WHEN** a client requests the undescribed list
- **THEN** each item shows the concept's preferred name

### Requirement: Next statements to connect
The system SHALL, when a statement list is requested with `to_connect=true`, return up to `limit` matching statements that no undecided draft covers, no agent holds and whose last look still holds is excluded, ordered first by how many linked statements name one of the same concepts (most first) and then by id, with `next_after` null.

#### Scenario: Statement beside connected knowledge
- **WHEN** two isolated statements are eligible and only the second names a concept that linked statements also name
- **THEN** the second is returned first

### Requirement: Connect pass availability
The system SHALL include in the health response `connect` with `batch_size`, `max_run_tokens`, `provider` and `model`, or `connect: null` with `connect_error` explaining why the connect pass is unavailable, such as missing credentials or an unavailable model setting.

#### Scenario: No credentials for the connect model
- **WHEN** the connect action's provider has no credentials configured
- **THEN** `connect` is null and `connect_error` gives the reason

### Requirement: Connect pass tool
The system SHALL provide `connect_statements(statement_ids)`, available over HTTP as `POST /connect-statements` and not advertised over MCP, requiring the writer role (a drafter also satisfies it), that runs one model loop over the given statements and produces at most one draft.

#### Scenario: Writer connects a batch
- **WHEN** a writer calls `connect_statements` with three isolated statement ids
- **THEN** one run proposes links and concept mentions for them as one draft

### Requirement: Connect pass input checks
The system MUST refuse a connect call before any model call when `statement_ids` is empty after removing repeats, when it holds more ids than the saved batch size (default 5, at most 25), when any id is not a statement (naming the missing ids), or when the connect action has no usable credentials.

#### Scenario: Batch too large
- **WHEN** a caller passes six distinct ids with the default batch size
- **THEN** the call is refused with `at most 5 statements per run; got 6`

### Requirement: Connect pass result
The system SHALL answer a connect call with the same `draft_created` or `nothing_to_ingest` shape as `ingest` (see the `ingest` capability), plus `tokens` (every token the run's model calls used) and `gaps_filed`; a created draft is submitted to the internal reviewer while review is on and otherwise stays open.

#### Scenario: Connect while review is on
- **WHEN** a connect run queues links and draft review is on
- **THEN** the response has `submitted_for_review: true`

### Requirement: Connect pass proposal scope
The system MUST let a connect draft hold only `add_links` edges, `alias_suggestion` records and `upsert_entity` concepts; any statement creation, rewrite, merge, deletion or other operation is dropped and listed in `flagged`, so a connect run never changes a statement.

#### Scenario: Model proposes a rewrite
- **WHEN** the connect model emits a `patch_statement` for a batch statement
- **THEN** the operation is dropped and flagged as outside what the connect pass may propose

### Requirement: Connect pass edge screening
The system MUST drop, and flag, each proposed edge that links a statement to itself, is conditioned on one of its own ends, touches no batch statement as an end or `when` condition, joins two `state` statements with `composes`, touches a statement the run classified `unphraseable`, or whose statement kinds break its link type's direction in either orientation.

#### Scenario: Edge between two outside statements
- **WHEN** the connect model proposes a link between two statements that are not in the batch
- **THEN** the edge is dropped and flagged as touching no batch statement

#### Scenario: Accepts edge to a non-property
- **WHEN** the connect model proposes an `accepts` edge to a statement that is not a `property`
- **THEN** the edge is dropped

### Requirement: Connect pass concepts and aliases
The system MUST drop a proposed new concept whose name already names a concept, whose name is a single short or generic word, or that no batch statement's text contains; and drop an alias suggestion whose `statement_id` is not a batch statement or whose statement text does not contain the alias. Alias evidence must quote that batch statement.

#### Scenario: New concept name already exists
- **WHEN** the connect model proposes `upsert_entity` for the name "Invoice" that already names a concept
- **THEN** the operation is dropped and flagged, leaving the existing description untouched

### Requirement: Rephrase gaps from the connect pass
The system SHALL open a knowledge gap for each batch statement the run classified `unphraseable`, with text starting `Rephrase this statement before it is connected: ` followed by the run's advice (or `rephrase it as one claim`), linked to the statement, unless that statement already has an open gap; the gap ids are returned in `gaps_filed`.

#### Scenario: Badly phrased statement
- **WHEN** a connect run classifies "Invoice Settings accepts due date." as unphraseable
- **THEN** a rephrase gap about that statement is opened and its id is in `gaps_filed`
- **AND** no edge touching that statement is queued

### Requirement: Connect pass memory
The system SHALL record, for each batch statement the run reconciled (any ledger classification except `unprocessed`), that the connect pass looked at it with its current text and the statements it weighed, so it is not offered as a next statement to connect until its look no longer holds; a statement the run never reached is offered again.

#### Scenario: Run stopped by its cap
- **WHEN** a connect run of five statements reconciles three before its cap stops it
- **THEN** only those three are recorded as looked at

### Requirement: Connect pass limits
The system SHALL bound each connect run by the saved connect limits: batch size (default 5), token cap (`max_run_tokens`, default 2,000,000, 0 for none), operation cap (default 60), wall clock (default 300 seconds), max tokens per turn (default 32000) and per-call timeout (default 120 seconds); before each model turn it stops reading and emits when the tokens used so far plus a reserve for one more turn and the final emit reach the cap.

#### Scenario: Token cap near
- **WHEN** the tokens used so far plus the reserve reach the token cap
- **THEN** the run stops reading and forces its final emit

### Requirement: Curation item shape
The system SHALL give each claimed item `id` (the statement id for `isolated` and `unnamed`, the gap id for `rephrase`, `gap` and `question`, the concept id for `undescribed` and `unused`, the two sorted ids joined by `~` for `duplicate`), `kind`, `text`, `statement` (`id`, `kind`, `text` and `concepts` as `{id, name}`, or null for an item about no statement), `neighbours` (up to five nearest other statements as `{id, kind, text, score}`) and the fields Curation item context describes.

#### Scenario: Gap about no statement
- **WHEN** an agent claims a `gap` item whose gap names no statement
- **THEN** the item's `statement` is null

### Requirement: Curation work selection
The system SHALL offer items in id order, leaving out items another caller holds under an unexpired lease, items an undecided draft already covers (for statements, a pending link or alias; for gaps other than questions, a gap tied to an undecided draft), and items whose last look still holds; a `rephrase` item is an open gap about a statement whose text starts with the connect pass's rephrase prefix, a `question` item is defined under Question items, and a `gap` item is any other open gap.

#### Scenario: Second agent claims
- **WHEN** one drafter holds an isolated statement and another drafter claims isolated work
- **THEN** the held statement is not offered to the second drafter

### Requirement: Curation leases
The system SHALL extend the lease on every item of `kind` the caller still holds whenever the caller claims that kind again, listing them in `renewed`, with `limit=0` only renewing; an item whose lease has expired returns to the pool.

#### Scenario: Lease expires
- **WHEN** 30 minutes pass after a claim without renewal
- **THEN** the item is offered to the next claimant

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
The system SHALL remember each `proposed`, `no_link`, `answered`, `resolved` or `not_applicable` release, in the same memory the connect pass uses, so the item is not offered again (to agents or as a next statement to connect) until the statement's text, a neighbour the claim offered, or a statement naming one of its concepts changes, or for a gap until its text or the statement it is about changes or a person reopens a gap the release closed; a `skipped` item is offered again at once.

#### Scenario: Skipped item
- **WHEN** a drafter releases an item as `skipped`
- **THEN** the item is offered on the next claim

#### Scenario: No link, then the statement is edited
- **WHEN** an item released as `no_link` has its text edited
- **THEN** it is offered again

### Requirement: Curation summary
The system SHALL include in the health response `curation`: per work kind, the current holders (`claimed_by`, the holder's display name when known, `items`, `expires_at`), `attempted` (items still on the list someone has looked at) and `outcomes` counted by `looked` (the connect pass), `proposed`, `no_link`, `skipped` and `answered`.

#### Scenario: Agent holding work
- **WHEN** a drafter holds three isolated items
- **THEN** the isolated summary lists that drafter with `items: 3`

### Requirement: Freeing an agent's claims
The system SHALL let an administrator free every claim one holder has on one kind with `POST /api/knowledge-health/claims/free` taking `kind` and `claimed_by`, answering `freed` (the number dropped) and recording no outcome, so the items are offered again; other callers are refused.

#### Scenario: Writer tries to free claims
- **WHEN** a writer posts to the free-claims route
- **THEN** the request is refused

### Requirement: Reporting a knowledge gap
The system SHALL provide `report_knowledge_gap(text, statement_id?, draft_id?, document_id?)`, advertised over MCP, to any caller with at least the reader role and no audience scope, creating an open gap stamped with its creator and returning `gap_id`. It MUST refuse blank text and any named statement, draft or document that does not exist.

#### Scenario: Agent reports a missing fact
- **WHEN** a reader calls `report_knowledge_gap(text="Nothing says who can export invoices")`
- **THEN** an open gap is created and its `gap_id` returned

#### Scenario: Unknown statement named
- **WHEN** a gap report names a `statement_id` that does not exist
- **THEN** the report is refused and no gap is created

### Requirement: Listing knowledge gaps
The system SHALL list gaps at `GET /api/knowledge-gaps` for any authenticated user, newest first, filtered by `status` of `all` (default), `open`, `resolved` or `dismissed`, each with `id`, `text`, `status`, `created_at`, `created_by`, `resolved_at`, `resolved_by`, `dismissed_at`, `dismissed_by`, `closing_reason` (the reason an agent gave when it closed the gap, or null), `draft_id`, `statement_id` and `document_id`, plus `can_write` for the caller; any other status is answered 400.

#### Scenario: Listing open gaps
- **WHEN** a reader requests `GET /api/knowledge-gaps?status=open`
- **THEN** only gaps neither resolved nor dismissed are returned

### Requirement: Changing a gap's status
The system SHALL let a real writer or administrator change a gap with `PATCH /api/knowledge-gaps/{id}` and an `action` of `resolve`, `dismiss` or `reopen`, stamping who and when; resolving clears a dismissal, dismissing clears a resolution, reopening clears both, and no route deletes a gap. Drafters and readers are answered 403, an unknown gap 404 and an unknown action 400.

#### Scenario: Drafter dismisses a gap
- **WHEN** a drafter sends `{"action": "dismiss"}` for a gap
- **THEN** the request is answered 403

#### Scenario: Reopening a resolved gap
- **WHEN** a writer reopens a resolved gap
- **THEN** its status is `open` and both terminal timestamps are cleared

### Requirement: Gaps resolved by applied drafts
The system SHALL resolve, in the same transaction that applies a draft, every open gap tied to that draft, recording the approver. A gap is tied to a draft when reported with its `draft_id`, or when released from the curation queue as `proposed` with that draft while it named no draft yet. Gaps the internal reviewer files are described in the `drafts-and-review` capability.

#### Scenario: Report about a draft
- **WHEN** a gap was reported with a `draft_id` and that draft is applied
- **THEN** the gap is resolved

#### Scenario: Gap closed by a curation draft
- **WHEN** a gap item is released as `proposed` with a draft and that draft is applied
- **THEN** the gap is resolved

### Requirement: Alias discovery scan
The system SHALL scan selected statements for new aliases of existing concepts with `POST /api/alias-suggestions/scan` taking `statement_ids` (1 to 50), for a real writer or administrator, in one structured model request on the `alias_discovery` model selection, and store the valid suggestions in one submitted draft titled `Alias suggestions from selected statements`; it answers `suggestions` and `skipped` (each with `proposal` and `reason`) and changes no live knowledge.

#### Scenario: Scan finds an abbreviation
- **WHEN** a writer scans a statement reading "Workspaces sign in with single sign-on (SSO)"
- **THEN** a submitted draft holds a suggestion of the alias with its exact quote

#### Scenario: Drafter scans
- **WHEN** a drafter posts to the scan route
- **THEN** the request is refused

### Requirement: Alias scan aborts
The system MUST abort a scan without saving anything when a selected statement does not exist, when the prompt exceeds the saved input limit (default 100000 characters), when names or concepts change while the model runs (answered 409), or when the model cites a statement outside the selection.

#### Scenario: Evidence outside the selection
- **WHEN** the scan's model cites a statement that was not selected
- **THEN** the scan fails and no draft is saved, including for its valid suggestions

### Requirement: Alias scan skips invalid suggestions
The system SHALL skip, with a reason in `skipped`, an individual scan suggestion that repeats another in the same scan, whose quote is not in its statement or does not contain the alias, whose concept is missing, or whose alias already belongs to a concept, keeping the valid ones; a scan with no valid suggestion creates no draft.

#### Scenario: Every suggestion invalid
- **WHEN** a scan's model returns only suggestions for aliases the target already has
- **THEN** the response lists them in `skipped` with reasons and no draft is created

### Requirement: Alias suggestion listing
The system SHALL list alias suggestions from every draft at `GET /api/alias-suggestions?status=pending|accepted|rejected|all` (default `pending`) for readers, each with its draft id, title and status, `operation_ref`, draft `revision`, the suggestion (proposal, original proposal, quoted evidence, decision history), the concept's current names, `stale`, `acceptance_committed` and up to 8 example statements containing the alias.

#### Scenario: Suggestion goes stale
- **WHEN** a name is added to a suggestion's target concept after the suggestion was made
- **THEN** the suggestion is listed with `stale: true`

### Requirement: Alias suggestion review
The system SHALL let only a human writer or administrator decide each suggestion with `POST /api/alias-suggestions/{draft_id}/{operation_ref}/review` taking `action` (`accept`, `reject`, `retarget` with `entity_id`, or `refresh`) and the displayed `expected_revision`, recording the actor and time; service accounts and drafters are refused. A changed draft revision, an already decided suggestion or draft, or a stale suggestion answers 409.

#### Scenario: Service account accepts
- **WHEN** a service-account token with the writer role posts an accept decision
- **THEN** the request is refused

#### Scenario: Accepting a stale suggestion
- **WHEN** a human writer accepts a suggestion whose target names changed since it was made
- **THEN** the request is answered 409 asking for an inspection and refresh

### Requirement: Alias acceptance effect
The system SHALL, on acceptance, add only that alias to the target concept and record an acceptance receipt; retargeting keeps the original proposal and evidence, refresh and retarget are refused when the supporting statement's text changed, and an alias owned by another concept is refused with a conflict. A repeated accept of a suggestion whose alias was already committed recovers the recorded decision without adding the name again, and any other action on it is refused.

#### Scenario: Interrupted acceptance
- **WHEN** an acceptance committed the alias but the draft update failed, and the curator accepts again
- **THEN** the original decision is recorded and the name is not written twice

#### Scenario: Retarget preserves evidence
- **WHEN** a human writer retargets a suggestion to another concept
- **THEN** `original_proposal` and the quoted evidence are unchanged

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

### Requirement: Statement duplicate audit
The system SHALL provide `find_duplicates(threshold?, limit=50)` for readers, over HTTP only, returning near-duplicate statement pairs `{a_id, a_text, b_id, b_text, score}` at or above the threshold (default from the embedding model, 0.92 for `nomic-embed-text` and 0.88 for `text-embedding-3-small`), each pair once, by score descending.

#### Scenario: Two wordings of one claim
- **WHEN** two statements' vectors score 0.95 with the default threshold
- **THEN** the pair is reported once

### Requirement: Concept duplicate audit
The system SHALL provide `find_entity_duplicates(threshold?, limit=50, offset=0)` for readers, over HTTP only, comparing names of different concepts and returning `{candidates, total}`: one candidate per concept pair with each matching name pair and its `via`, word matches ranked above embedding-only ones, then by score.

#### Scenario: Match passes and scores
- **WHEN** names of two concepts are compared
- **THEN** they match `fold` (score 1.0) when equal after folding, `same_words` (0.95) for the same words in another order or style, `initials` (0.9) when one spells the other's initials, or `embedding` at or above the threshold (default 0.75 for `nomic-embed-text`, 0.66 for `text-embedding-3-small`)

#### Scenario: Abbreviation on a separate concept
- **WHEN** "SSO" and "Single sign-on" name different concepts
- **THEN** the pair is a candidate matched `via: initials`

### Requirement: Dismissing duplicate candidates
The system SHALL let a real writer or administrator dismiss a concept pair as not duplicates (`POST /api/names-workspace/duplicates/dismiss`) and restore it (`POST /api/names-workspace/duplicates/restore`), record a `duplicate` concept pair released `not_applicable` as the same dismissal by the releasing agent, list dismissals for any authenticated user, leave dismissed pairs out of `find_entity_duplicates`, and drop a dismissal when either concept is deleted or merged away.

#### Scenario: Dismissed pair after a merge
- **WHEN** a dismissed pair's concept is merged into a third concept
- **THEN** the dismissal no longer exists

#### Scenario: Agent finds two concepts distinct
- **WHEN** a drafter releases a concept `duplicate` item as `not_applicable` with a reason
- **THEN** the pair is dismissed by that drafter and no longer listed as a candidate

### Requirement: Claiming curation work
The system SHALL provide `claim_curation_work(kind, limit=5)`, advertised over MCP, for callers with at least the drafter role, leasing up to `limit` (0 to 20) items of `kind` (`isolated`, `unnamed`, `rephrase`, `gap`, `question`, `duplicate`, `undescribed` or `unused`) for 30 minutes and returning `kind`, `items`, `renewed`, `expires_at` and `link_types` (the link vocabulary with each type's description and direction).

#### Scenario: Agent claims isolated statements
- **WHEN** a drafter calls `claim_curation_work("isolated", limit=3)`
- **THEN** up to three isolated statements are leased to it for 30 minutes

#### Scenario: Reader tries to claim
- **WHEN** a reader calls `claim_curation_work`
- **THEN** the call is refused with a role error

### Requirement: Uncovered statements per profile
The system SHALL report in `GET /api/knowledge-health` an `uncovered_by_profile` map holding, for each writing profile that can be planned for, how many statements are uncovered for it (its audience may see them, none of its documents cites them and they were not dismissed for it), computed from current data on every request.

#### Scenario: Profile with undocumented statements
- **WHEN** the `public` profile's audience may see 12 statements no `public` document cites
- **THEN** `uncovered_by_profile` reports 12 for `public`

### Requirement: Connect pass model
The system SHALL run the connect pass on the model selected for the `connect` action, refusing the run while that action has no model chosen, with its instructions from the saved `connect` prompt followed by a fixed contract, meter its calls as `connect`, and append its trace to `connect_trace.jsonl` in the data directory.

#### Scenario: No model chosen
- **WHEN** a caller requests a connect run while the `connect` action has no model saved
- **THEN** the call is refused naming the missing model and no draft is created

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

### Requirement: Question items
A `question` item SHALL be the newest open gap about a submitted, undecided draft whose latest review has `application: needs_human` and that has not changed since, and SHALL carry `question`: the `draft_id`, the draft's title, the `run_id` of the review that asked, its `questions` and its rationale.

#### Scenario: Reviewer question
- **WHEN** an agent claims a `question` item
- **THEN** the item carries the draft id, the asking run's id and the reviewer's questions

#### Scenario: Question after the draft changed
- **WHEN** a draft's reviewer asked a person and the draft was edited since
- **THEN** its gap is not offered as a `question` item

### Requirement: Outcomes per kind
The system SHALL accept `answered` and `skipped` for `question` items; `proposed`, `no_link`, `skipped`, `resolved` and `not_applicable` for `rephrase` and `gap` items; `proposed`, `not_applicable` and `skipped` for `duplicate` items; and `proposed`, `no_link` and `skipped` for `isolated`, `unnamed`, `undescribed` and `unused` items.

#### Scenario: Outcome the kind does not take
- **WHEN** a drafter releases an isolated statement as `resolved`
- **THEN** the release is refused

### Requirement: Duplicate items
A `duplicate` item SHALL be a statement pair from the statement duplicate audit or a concept pair from `find_entity_duplicates`, ordered by score, leaving out pairs either side of which an undecided draft touches. Releasing it `proposed` SHALL name the caller's draft that merges the pair; `not_applicable` SHALL record that the pair is not a duplicate, so it is not offered again until either side's text (or, for concepts, names) changes.

#### Scenario: Agent merges a duplicate through review
- **WHEN** an agent claims a statement pair, queues `merge_statements` on its draft, submits it and releases the pair `proposed`
- **THEN** the merge waits for the reviewer and the pair is not offered while the draft is undecided

#### Scenario: Not a duplicate
- **WHEN** an agent releases a statement pair `not_applicable` and neither statement changes
- **THEN** the pair is not offered again

### Requirement: Concept items
An `undescribed` item SHALL be a concept with a blank description, and an `unused` item a concept no statement mentions, each left out while an undecided draft names it. A release SHALL be remembered until the concept's names or description change, and for an `undescribed` item also until a statement naming it changes.

#### Scenario: Concept described by a draft
- **WHEN** an agent proposes a description for an undescribed concept in its draft and releases it `proposed`
- **THEN** the concept is not offered again while the draft is undecided

### Requirement: AI curation pass
The system SHALL run a background curation pass on the Connecting statements model as the curation agent `model:<model>`, only while that action runs on a server model with credentials, metering its calls as the connect action. Each step SHALL have its own setting, default off and read as off when unsaved: `decide_duplicates`, `describe_concepts`, `act_on_gaps` (rephrase gaps and gaps about drafts) and `connect_automatically` (the connect pass on the next isolated, then unnamed, statements).

#### Scenario: Toggles off
- **WHEN** every curation toggle is off
- **THEN** the pass makes no model call

#### Scenario: Model merges a duplicate
- **WHEN** `decide_duplicates` is on and the model says a statement pair is the same fact
- **THEN** a submitted draft merges the dropped side into the kept one and the pair is released `proposed`

#### Scenario: Model cannot ground a description
- **WHEN** `describe_concepts` is on and the model cites a statement not supplied for the concept
- **THEN** no draft is made and the concept stays available to outside agents

#### Scenario: External agent
- **WHEN** Connecting statements runs on an External agent
- **THEN** the pass does nothing and the items wait in the queue for agents

### Requirement: AI curation pass decisions
The pass SHALL merge a duplicate through a draft or release it `not_applicable`, propose a concept description citing statements that name it, rephrase or keep a rephrase gap's statement, and for a gap about a draft propose a corrective draft from a fixed set of operations or close the gap. Its drafts SHALL carry statement evidence, have no creator account and be submitted while review is on. An item it cannot decide SHALL be released `skipped` and not offered to it again until the item changes.

#### Scenario: Model leaves a gap undecided
- **WHEN** `act_on_gaps` is on and the model returns no decision for a gap about a rejected draft
- **THEN** the gap is released `skipped` and stays available to outside agents

### Requirement: Curation item context
Where they apply, a claimed item SHALL also carry `pair` (a duplicate's kind, both sides and their score), `concept` (the concept, its names, description and statements naming it) and `draft` (for a `rephrase` or `gap` item whose gap names a draft: its id, title, status, latest review rationale and operations).

#### Scenario: Gap about a rejected draft
- **WHEN** an agent claims a `gap` item filed when a draft was rejected
- **THEN** the item's `draft` carries that draft's operations and the rejection's rationale
