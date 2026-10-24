# ingest Specification

## Purpose
Turn a block of free prose into a reviewable draft of proposed knowledge changes (statements, links, concepts, refinements and alias suggestions) without ever writing accepted knowledge directly.

## Requirements

### Requirement: Ingest tool entry point
The system SHALL expose an `ingest` tool taking one `text` argument, advertised over MCP and mirrored as `POST /ingest`, that runs a model-driven extraction loop inside the call and returns its outcome.

#### Scenario: Prose handed to ingest
- **WHEN** a caller invokes `ingest(text="Workspace admins can export invoices as CSV.")`
- **THEN** the call runs the extraction loop to completion before responding
- **AND** the response carries an `outcome` of `draft_created` or `nothing_to_ingest`

### Requirement: Ingest role gate
The system MUST require the writer role for `ingest`; a drafter also satisfies the gate, and a reader or a principal scoped to an audience is refused.

#### Scenario: Reader calls ingest
- **WHEN** a principal with the reader role calls `ingest`
- **THEN** the call is refused with a role error and no draft is created

#### Scenario: Drafter calls ingest
- **WHEN** a principal with the drafter role calls `ingest`
- **THEN** the loop runs and its outcome is returned

### Requirement: No live write from ingest
The system MUST NOT change accepted knowledge during an ingest run; the model is offered only read tools plus one terminal `emit_draft` tool, and the only thing the run persists is a draft and its queued operations.

#### Scenario: Model reads during ingest
- **WHEN** the ingest loop starts
- **THEN** the tools offered to the model include `search_statements` and `discover_facts`
- **AND** they exclude every write tool, `report_knowledge_gap`, `ask` and `ingest` itself

#### Scenario: Ingest finishes with proposals
- **WHEN** an ingest run ends with proposed operations
- **THEN** statements, links and entities in the knowledge base are unchanged until the draft is applied

### Requirement: Live vocabulary fetched first
The system SHALL fetch the live statement kinds, link types and entity link types at the start of every run and give them to the model in its first message; each fetch counts toward the operation cap, and a failed fetch is recorded in the trace without stopping the run.

#### Scenario: Vocabulary fetch at run start
- **WHEN** an ingest run starts
- **THEN** `list_statement_kinds`, `list_link_types` and `list_entity_link_types` are called before the first model turn
- **AND** the trace counts these three calls as operations

### Requirement: Draft created outcome
The system SHALL answer a run that queued at least one operation, or whose model raised its own flag, with `outcome: draft_created`, `draft_id` (a `drf_…` id), `alias_draft_id` (or null), `submitted_for_review`, the queued `ops` (each with `op`, `payload`, `rationale`, `targets_existing`), `flagged`, `skipped_duplicates` and `trace`.

#### Scenario: Two new facts extracted
- **WHEN** ingest proposes two new statements and a link between them
- **THEN** the response has `outcome: draft_created` and a `draft_id`
- **AND** `ops` lists each queued operation with its rationale

### Requirement: Nothing to ingest outcome
The system SHALL answer `outcome: nothing_to_ingest` with a `reason` and `trace`, and create no draft, when every candidate was a duplicate (`all candidates were duplicates`), nothing was extractable (`nothing extractable`), every proposed operation failed validation without a model flag (`no valid ops survived validation; see flagged trace`), or the run degraded without a usable emit (a reason starting `degraded:`).

#### Scenario: Prose already known
- **WHEN** every fact in the text already exists as a statement and the model proposes no operation
- **THEN** the outcome is `nothing_to_ingest` with reason `all candidates were duplicates`
- **AND** no draft is created

### Requirement: Draft title and author
The system SHALL title an ingest draft `ingest: ` followed by the first 60 characters of the whitespace-collapsed input (`ingest: (empty)` for empty input), and create it with no author account.

#### Scenario: Draft title from prose
- **WHEN** ingest creates a draft from "Admins can export invoices."
- **THEN** the draft is titled `ingest: Admins can export invoices.`

### Requirement: Submission to internal review
The system SHALL submit a created knowledge draft to the internal draft reviewer at once when draft review is on and the draft holds at least one operation, reporting `submitted_for_review: true`; otherwise the draft stays open for a curator and `submitted_for_review` is false. Review itself is described in the `drafts-and-review` capability.

#### Scenario: Review is off
- **WHEN** draft review mode is `off` and ingest creates a draft
- **THEN** the draft stays open and `submitted_for_review` is false

#### Scenario: Review is on
- **WHEN** draft review is on and ingest queues operations
- **THEN** the draft is submitted to the reviewer and `submitted_for_review` is true

### Requirement: Allowed operation kinds
The system MUST queue only operations whose kind is one of `upsert_statement`, `upsert_statements`, `upsert_entity`, `add_links`, `add_entity_links`, `patch_statement`, `replace_text`, `merge_statements` or `alias_suggestion`, and that is a registered tool or the alias suggestion record; any other kind is dropped and listed in `flagged`.

#### Scenario: Unknown operation kind
- **WHEN** the model emits an operation of kind `delete_statement`
- **THEN** that operation is not queued
- **AND** `flagged` names it as not a known draft op kind

### Requirement: Replay-safe payload validation
The system MUST drop, and list in `flagged`, any operation that would fail when the draft is applied: a payload that is not an object, a required key that is missing or null, or a top-level key the target tool does not accept. Other operations in the same run are still queued.

#### Scenario: Required keys per kind
- **WHEN** the model emits an operation missing its required keys: `kind` and `text` for `upsert_statement`, `statements` for `upsert_statements`, `name` and `description` for `upsert_entity`, `links` for `add_links` and `add_entity_links`, `id` for `patch_statement`, `id` and `text` for `replace_text`, `from_id` and `into_id` for `merge_statements`
- **THEN** that operation is dropped and `flagged` names the missing keys

#### Scenario: Entity without description
- **WHEN** the model emits `upsert_entity` with a name and no description
- **THEN** that operation is dropped and flagged
- **AND** the run's other valid operations are queued

#### Scenario: Unexpected key
- **WHEN** the model emits `merge_statements` with an extra `reason` key
- **THEN** that operation is dropped and `flagged` names the unexpected key

### Requirement: Edge shape validation
The system MUST drop an `add_links` operation unless `links` is a non-empty list of objects each with `from_id`, `to_id` and `link_type`, every end and every `when` leaf is a statement id (`stm_…`) or a draft result reference (`@seq:index`), and the `when` expression is valid; an `add_entity_links` operation needs `from_entity_id`, `to_entity_id` and `link_type` on each edge. Proposals linking an entity to a statement are dropped as findings.

#### Scenario: Entity-to-statement link proposed
- **WHEN** the model emits `add_links` with an edge from an entity id to a statement id
- **THEN** that operation is dropped and flagged

### Requirement: Statement payload normalization
The system SHALL normalize statement-creating payloads before queueing: a missing `links` on `upsert_statement` or on each `upsert_statements` item becomes an empty list, and any proposed `mentions` (and `strict_mentions`) are removed because mentions are derived from text. An `upsert_statement` with an `id` and no `links` is still queued, with a note in its rationale that it replaces the statement's outgoing links.

#### Scenario: Proposed mentions removed
- **WHEN** the model emits `upsert_statement` carrying `mentions` and no `links`
- **THEN** the queued payload has `links: []` and no `mentions`

### Requirement: Phrasing pre-check
The system SHALL run the phrasing check on each proposed statement text and, when it reports violations, queue the statement with `allow_phrasing_violations` set and list the violation categories in `flagged` and in the rationale, rather than dropping it.

#### Scenario: Statement with a phrasing violation
- **WHEN** the model proposes an event statement that breaks a phrasing rule
- **THEN** the statement is queued with `allow_phrasing_violations: true`
- **AND** `flagged` names the violation categories

### Requirement: Backwards edges dropped
The system MUST drop, before queueing, any proposed statement edge whose source and target statement kinds show it points the wrong way for its link type (the edge would be valid swapped), list each in `flagged` as `edge dropped: …`, and keep the operation holding it with its remaining edges. Edges whose kinds break the type in both directions are left for review.

#### Scenario: Flipped edge in a batch
- **WHEN** a proposed `upsert_statements` item links a property to a capability with a type that goes capability to property
- **THEN** that edge is removed and flagged
- **AND** the statement itself is still queued

### Requirement: Draft references renumbered
The system SHALL let operations refer to statements created earlier in the same emit as `@seq:index` (counting emitted operations from 1) and rewrite each reference to the queued operation's real sequence number; an operation that refers to an operation that was not queued is dropped and flagged. A batch naming its own items with its own operation number is read as `@index`.

#### Scenario: Link to a dropped operation
- **WHEN** an `add_links` operation references `@2:0` and operation 2 was dropped by validation
- **THEN** the `add_links` operation is dropped and flagged

### Requirement: Reconcile and adjacency floor
The system MUST refuse an `emit_draft` call until the run has made at least one successful reconcile read (`discover_facts` or `search_statements`) and, after its first read, at least one successful adjacency search (`search_statements` or `grep_statements`). A refused emit is answered with a re-prompt; after three refusals the run is force-finalized with reason `floor_stuck`.

#### Scenario: Emit without searching
- **WHEN** the model calls `emit_draft` before any reconcile read
- **THEN** the emit is refused with a message stating the reads still owed
- **AND** the run continues

### Requirement: Candidate ledger
The system MUST require one ledger row per extracted candidate, classified `new`, `duplicate`, `refinement`, `contradiction` or `unphraseable`; every `new` or `refinement` row needs a non-empty `matched_against` and either `link_candidates_considered` or a note, and the number of statement-creating operations may not exceed the number of `new` and `refinement` rows. An unmet ledger refuses the emit like the floor does. The ledger is returned in the trace as `candidate_ledger`.

#### Scenario: New row without reconciliation
- **WHEN** the emit carries a `new` row with an empty `matched_against`
- **THEN** the emit is refused and the model is told which rows are under-supported

### Requirement: Duplicates and contradictions reported
The system SHALL return candidates the model found already present in `skipped_duplicates` as `candidate :: existing_id`, and contradictions the model raised in `flagged`, without queuing any automatic resolution for a contradiction.

#### Scenario: Contradicting prose
- **WHEN** the text says exports are limited to 1,000 rows and an existing statement says 5,000
- **THEN** `flagged` names both sides of the contradiction
- **AND** no operation resolving it is queued

### Requirement: Alias suggestions in their own draft
The system SHALL put `alias_suggestion` operations (`entity_id`, `alias`, `quote`, `reason`, `ambiguity`) in a separate draft titled `Alias suggestions from <draft_id>: <title>`, submitted at once without internal review, and return its id as `alias_draft_id`; when the run proposed only alias suggestions, that draft is the only one, titled `Alias suggestions from <title>`, and is returned as `draft_id`. Review of suggestions is described in the `knowledge-health` capability.

#### Scenario: Prose introduces an abbreviation
- **WHEN** ingest reads "single sign-on (SSO)" and proposes a new statement and an alias suggestion for an existing concept
- **THEN** the statement is in the draft named by `draft_id`
- **AND** the suggestion is in a separate submitted draft named by `alias_draft_id`

### Requirement: Alias evidence quoted from the input
The system MUST drop an ingest alias suggestion whose `quote` is not an exact substring of the (possibly truncated) input, that names a `statement_id`, whose alias does not occur in its quote, whose target concept does not exist, or whose alias already belongs to the target or to another concept, and list the reason in `flagged`.

#### Scenario: Fabricated quote
- **WHEN** the model proposes an alias with a quote that does not appear in the input text
- **THEN** the suggestion is dropped and flagged

### Requirement: Input length limit
The system SHALL process at most `max_input_chars` characters of input (default 20000); longer input is cut to its head, and the trace records a note that the tail was not processed.

#### Scenario: Oversized prose
- **WHEN** ingest receives 25000 characters with the default limit
- **THEN** only the first 20000 characters are processed
- **AND** the trace notes the truncation

### Requirement: Run limits
The system SHALL bound each run by the saved ingest limits: an operation cap (default 50, counting the vocabulary fetch and every read), a wall clock (default 300 seconds, with reading stopped after two thirds so the final emit has the last third), max tokens per turn (default 32000), a per-call timeout (default 90 seconds), provider retries (default 4) and adaptive thinking (default on). Ingest has no spending cap.

#### Scenario: Default operation cap reached
- **WHEN** a run has made 50 counted operations
- **THEN** the model gets no further read turns and is forced to emit

### Requirement: Forced finalize instead of failure
The system SHALL NOT raise to the caller when a run hits its operation cap, wall clock, turn limit, a provider error, a model that keeps answering without the terminal tool (after one nudge), or the floor limit; it forces one final `emit_draft` turn and assembles a degraded draft from it, or returns `nothing_to_ingest` with a `degraded:` reason. A malformed emit is re-prompted once before degrading. An emit cut off by the token or time limit keeps the operations it had finished.

#### Scenario: Provider error mid-run
- **WHEN** the model provider fails after its retries
- **THEN** the run forces a final emit
- **AND** the trace records `forced_finalize` and `degraded: true`

### Requirement: Forced runs record gaps
The system SHALL add a trace gap on every forced finalize stating that candidates beyond those reconciled may be unprocessed, and a gap for each ledger row classified `unprocessed`.

#### Scenario: Cap hit mid-reconcile
- **WHEN** the operation cap forces a finalize
- **THEN** the trace `gaps` include the forced-finalize note

### Requirement: Ingest trace
The system SHALL return a `trace` with the model, provider, outcome, input length, operation count and cap, latency, model turns, every tool call, the candidate ledger, proposed operations, flags, skipped duplicates, gaps, floor state, token totals, `cost_usd` (null for a model without a known price), `forced_finalize`, `degraded`, notes and the prompt version used, and append it as one JSON line to `ingest_trace.jsonl` in the data directory unless `MYCELIUM_INGEST_TRACE_LOG` names another file.

#### Scenario: Trace written
- **WHEN** an ingest run finishes
- **THEN** a JSON line with its trace is appended to the ingest trace log

### Requirement: Editable ingest instructions
The system SHALL read the ingest instructions from the saved prompt named `ingest` (editable in Settings → Prompts) at the start of each run, falling back to the packaged doctrine file, or to the file named by `MYCELIUM_INGEST_DOCTRINE_PATH`; an edit applies to the next run without a restart, and an unreadable source falls back with a note in the trace.

#### Scenario: Instructions edited
- **WHEN** an administrator saves new ingest instructions
- **THEN** the next ingest run uses them

### Requirement: Ingest model selection
The system SHALL run ingest with the model selected for the `ingest` action (default provider Claude, model `claude-sonnet-4-6`) and its reasoning effort, as configured in the `ai-providers` capability, and attribute its model calls to `ingest`.

#### Scenario: Default model
- **WHEN** no ingest model has been saved
- **THEN** ingest runs on `claude-sonnet-4-6`

### Requirement: Shared model-loop budget
The system SHALL count each ingest call against the shared model-loop concurrency limit it shares with Ask, the connect pass and documentation runs (default 2 concurrent loops), on every transport.

#### Scenario: Loops already running
- **WHEN** two model loops are running under the default limit and a third caller posts to `/ingest`
- **THEN** the third call waits for a free slot before its loop starts
