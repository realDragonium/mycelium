## MODIFIED Requirements

### Requirement: Claiming curation work
The system SHALL provide `claim_curation_work(kind, limit=5)`, advertised over MCP, for callers with at least the drafter role, leasing up to `limit` (0 to 20) items of `kind` (`isolated`, `unnamed`, `rephrase`, `gap`, `question`, `duplicate`, `undescribed` or `unused`) for 30 minutes and returning `kind`, `items`, `renewed`, `expires_at` and `link_types` (the link vocabulary with each type's description and direction).

#### Scenario: Agent claims isolated statements
- **WHEN** a drafter calls `claim_curation_work("isolated", limit=3)`
- **THEN** up to three isolated statements are leased to it for 30 minutes

#### Scenario: Reader tries to claim
- **WHEN** a reader calls `claim_curation_work`
- **THEN** the call is refused with a role error

### Requirement: Curation item shape
The system SHALL give each claimed item `id` (the statement id for `isolated` and `unnamed`, the gap id for `rephrase`, `gap` and `question`, the concept id for `undescribed` and `unused`, the two sorted ids joined by `~` for `duplicate`), `kind`, `text`, `statement` (`id`, `kind`, `text` and `concepts` as `{id, name}`, or null for an item about no statement), `neighbours` (up to five nearest other statements as `{id, kind, text, score}`) and the fields Curation item context describes.

#### Scenario: Gap about no statement
- **WHEN** an agent claims a `gap` item whose gap names no statement
- **THEN** the item's `statement` is null

### Requirement: Outcomes per kind
The system SHALL accept `answered` and `skipped` for `question` items; `proposed`, `no_link`, `skipped`, `resolved` and `not_applicable` for `rephrase` and `gap` items; `proposed`, `not_applicable` and `skipped` for `duplicate` items; and `proposed`, `no_link` and `skipped` for `isolated`, `unnamed`, `undescribed` and `unused` items.

#### Scenario: Outcome the kind does not take
- **WHEN** a drafter releases an isolated statement as `resolved`
- **THEN** the release is refused

### Requirement: Dismissing duplicate candidates
The system SHALL let a real writer or administrator dismiss a concept pair as not duplicates (`POST /api/names-workspace/duplicates/dismiss`) and restore it (`POST /api/names-workspace/duplicates/restore`), record a `duplicate` concept pair released `not_applicable` as the same dismissal by the releasing agent, list dismissals for any authenticated user, leave dismissed pairs out of `find_entity_duplicates`, and drop a dismissal when either concept is deleted or merged away.

#### Scenario: Dismissed pair after a merge
- **WHEN** a dismissed pair's concept is merged into a third concept
- **THEN** the dismissal no longer exists

#### Scenario: Agent finds two concepts distinct
- **WHEN** a drafter releases a concept `duplicate` item as `not_applicable` with a reason
- **THEN** the pair is dismissed by that drafter and no longer listed as a candidate

## ADDED Requirements

### Requirement: Curation item context
Where they apply, a claimed item SHALL also carry `pair` (a duplicate's kind, both sides and their score), `concept` (the concept, its names, description and statements naming it) and `draft` (for a `rephrase` or `gap` item whose gap names a draft: its id, title, status, latest review rationale and operations).

#### Scenario: Gap about a rejected draft
- **WHEN** an agent claims a `gap` item filed when a draft was rejected
- **THEN** the item's `draft` carries that draft's operations and the rejection's rationale

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
