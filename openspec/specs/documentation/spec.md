# documentation Specification

## Purpose
Project accepted knowledge into audience-scoped, reviewed documents: writing profiles and their templates, background documentation runs with grounding and review gates, immutable revisions, freshness and automatic maintenance, documentation planning, and publication to GitHub pull requests. Generated documents are outputs and never feed back as evidence.

## Requirements

### Requirement: Writing profiles are guideline-set rows
The system SHALL store each writing profile (guideline set) as prompt-store rows of type `guideline-set` named `<set>/<slot>`, where the slot is `guidance`, `exposure`, `audience` (an audience id), `maintenance` (`manual`, `propose`, `auto-revise`), `planning` (`off`, `propose`, `write`), `plan_review` (`person`, `ai`), `delivery` (`people`, `agents`), `destinations` (destination names, one per line) or a document type, whose row is its template.

#### Scenario: Listing what a profile can write
- **WHEN** the live rows are `billing-docs/guidance`, `billing-docs/exposure`, `billing-docs/how-to` and `billing-docs/reference`
- **THEN** the catalogue offers profile `billing-docs` with document types `how-to` and `reference`
- **AND** `guidance` and `exposure` are not offered as document types

#### Scenario: Retired rows leave the catalogue
- **WHEN** every row of a profile is retired
- **THEN** the profile is no longer offered to runs, planning or the generate form

### Requirement: Profile names and reserved slots
The system MUST refuse profile and template names that are blank, contain `/` or have surrounding whitespace, MUST refuse a template named `guidance`, `exposure`, `audience`, `maintenance`, `planning`, `plan_review`, `delivery` or `destinations`, MUST refuse duplicate template names within one save, and MUST refuse a maintenance text other than `manual`, `propose` or `auto-revise`; a stored maintenance text that is not one of those reads as `manual`.

#### Scenario: Reserved template name
- **WHEN** a writer saves a profile with a template named `exposure`
- **THEN** the save is refused and nothing is written

### Requirement: Profile save is versioned and conflict-checked
The system SHALL save a profile through `PUT /api/documentation/profiles/{name}` with its guidance, exposure, audience, maintenance policy, templates and the profile `revision` the editor read; the save appends a new version only for slots whose text changed, retires slots the body no longer contains, and is refused with 409 when the stored profile revision differs. A save carrying no guidance, exposure, audience or template is refused.

#### Scenario: Two editors save the same profile
- **WHEN** two writers load profile `billing-docs` and the first saves a template change
- **THEN** the second save with the old `revision` is refused with 409 and stores nothing

#### Scenario: Unchanged slot
- **WHEN** a save repeats a slot's current text
- **THEN** no new version of that slot is appended

### Requirement: Profile edit roles
The system MUST require a real writer or admin to save a profile or a profile text, MUST require an admin to remove an existing slot, to retire a profile (`DELETE /api/documentation/profiles/{name}`), to retire a text (`retire_prompt_text`), to change the audience or the destinations of an existing profile or to save an `audience` or `destinations` text directly, and MUST refuse an `audience` value that is not a live audience id.

#### Scenario: Writer removes a template
- **WHEN** a writer saves profile `billing-docs` without its existing `reference` template
- **THEN** the save is refused for lacking the admin role

#### Scenario: Writer changes the audience
- **WHEN** a writer saves an existing profile with a different `audience`
- **THEN** the save is refused for lacking the admin role

#### Scenario: Writer widens the destinations
- **WHEN** a writer saves an existing profile that publishes only to `staff-wiki` with no destinations
- **THEN** the save is refused for lacking the admin role

### Requirement: Default profile protection
The system MUST refuse to retire the configured default profile (the documentation setting `guideline_set`, default `kb-authoring`) or to remove its last template, until another default profile is selected.

#### Scenario: Retiring the default
- **WHEN** an admin retires the profile configured as the default
- **THEN** the request is refused with a message to choose another default first

### Requirement: Profile readiness view
The system SHALL report, for each profile from `GET /api/documentation/profiles`, its `revision`, `retired`, `ready`, `effective_audience`, `retired_templates` and `issues`; a profile is ready only when it has at least one valid template and a live effective audience, and issues name a missing template, missing guidance, missing disclosure rules, or a retired audience. The listing also reports `can_write`, `can_retire` and `default_profile`.

#### Scenario: Profile without a template
- **WHEN** a profile has guidance but no template
- **THEN** it is listed with `ready` false and an issue asking for a template

### Requirement: Profile text history and restore
The system SHALL keep every version of a profile text and of the editable loop instructions, list them through `GET /api/documentation/prompts/history`, save one text through `PUT /api/documentation/prompts` with the expected current `revision` (its version number, 0 for a new text), and restore an earlier version through `POST /api/documentation/prompts/restore` as a new version; a stale `revision` is refused with 409.

#### Scenario: Restoring an earlier template
- **WHEN** a writer restores version 2 of `billing-docs/how-to` while version 4 is current and supplies revision 4
- **THEN** version 5 is appended with version 2's text

#### Scenario: Text outside the editor's scope
- **WHEN** a caller saves a text that is neither a `guideline-set` row nor a loop instruction doctrine through these routes
- **THEN** the save is refused

### Requirement: Starter profile seeding
The system SHALL, at startup, insert the packaged `kb-authoring` profile (guidance, exposure and the `tutorial`, `how-to`, `reference`, `explanation` and `troubleshooting` templates) only when no `guideline-set` row has ever been stored; saved edits and retirements take precedence on later starts, and a starter file that cannot be read leaves no partial profile and does not stop the server from starting.

#### Scenario: Restart after retiring a starter template
- **WHEN** an admin retired `kb-authoring/tutorial` and the server restarts
- **THEN** `kb-authoring/tutorial` stays retired

### Requirement: Requesting a documentation run
The system SHALL expose `request_documentation(prompt, guideline_set?, document_type?, provider?, anchor_entity_id?)`, advertised over MCP and mirrored as `POST /api/documentation/runs`, which admits a background run and returns its run row immediately with `status` `running` or `queued`.

#### Scenario: Request without profile or type
- **WHEN** a writer calls `request_documentation(prompt="How to export invoices as CSV")`
- **THEN** a run row with an id prefixed `drn_` is returned before any document is written
- **AND** its `guideline_set` and `document_type` stay null until the run resolves them

### Requirement: Documentation run roles
The system MUST require a real writer or admin role (a drafter does not qualify) to request, revise, retry, manually edit or publish documents and to start, approve, retry or dismiss plan items; any authenticated caller may read runs, documents, revisions, plans, destinations and the maintenance feed, subject to audience scoping.

#### Scenario: Drafter requests a document
- **WHEN** a drafter calls `request_documentation`
- **THEN** the call is refused with a role error and no run is created

### Requirement: Request validation at the door
The system MUST refuse a documentation request whose prompt is blank or longer than the documentation prompt limit (`max_prompt_chars`, default 2000), whose `guideline_set` is not configured, whose `document_type` is not a template of the named set, or whose `anchor_entity_id` names no existing entity; the refusal happens before any run row exists and names the configured alternatives for an unknown set or type.

#### Scenario: Unknown document type
- **WHEN** a writer requests `guideline_set="billing-docs"` and `document_type="tutorial"` and that set has no `tutorial` template
- **THEN** the request is refused listing the types `billing-docs` can write

#### Scenario: Prompt over the limit
- **WHEN** the prompt is 2500 characters and the limit is 2000
- **THEN** the request is refused rather than truncated

### Requirement: Model choice for a run
The system SHALL take `provider` `claude`, `openai` or `agent` per request, defaulting to the saved documentation model settings (default `claude`), record the provider, model and reasoning effort on the run, and refuse the request when no model is configured for a provider the run needs or that provider is unavailable; a run never switches provider on failure. `list_documentation_models` reports the default provider and each provider's model, availability and reason.

#### Scenario: GPT selected without a model
- **WHEN** a writer requests `provider="openai"` and no OpenAI documentation model is configured
- **THEN** the request is refused asking to choose an OpenAI documentation model

### Requirement: Agent runs
The system SHALL have a run with provider `agent` written by an outside agent (see agent-tasks), needing a model only when the server reviews it; it is the default while documentation is set to External agent. A manual edit always uses a server provider, and `list_documentation_models` lists `agent` while documentation is set to External agent.

#### Scenario: Explicit server provider while External agent is selected
- **WHEN** documentation is set to External agent and a writer requests `provider="claude"`
- **THEN** the run is written on the server with the Claude documentation model

### Requirement: Run concurrency and queueing
The system SHALL run at most the saved documentation active-run limit (`documentation_runs`, default 2) at once; a run admitted beyond it is stored `queued` with a `queue_position` (1 starts next) and starts in admission order when a running one finishes. While running, a run also waits for a shared model-loop slot and stays `running` while it waits.

#### Scenario: Third concurrent request
- **WHEN** two runs are running and a third is requested with the limit at 2
- **THEN** the third returns `status` `queued` with `queue_position` 1
- **AND** it starts when one of the running runs finishes

### Requirement: Run status derivation
The system SHALL report each run's `status` as `queued` before it starts, `waiting_for_agent` while an outside agent's task serves it, `running` until it finishes, then `document_written`, `nothing_written` or `failed` from its outcome, except that a run whose written document has since been rewritten by another run reports `document_superseded` while its stored `outcome` stays `document_written` and `document_superseded` is true.

#### Scenario: A later run revises the document
- **WHEN** run A wrote document D and run B later writes a new revision of D
- **THEN** `get_documentation_run(A)` reports `status` `document_superseded` and `outcome` `document_written`

### Requirement: Waiting agent runs take no run slot
The system SHALL give a `waiting_for_agent` run no `queue_position` and not count it against the active-run limit.

#### Scenario: Agent run before it is written
- **WHEN** a run is requested with provider `agent`
- **THEN** it reports `status` `waiting_for_agent` until the agent's document is saved or refused

### Requirement: Run listing and detail
The system SHALL list the newest 100 runs through `list_documentation_runs` with `draft_chars` instead of draft text, and return one run through `get_documentation_run(run_id)` (MCP) or `GET /api/documentation/runs/{run_id}` including `draft_title` and `draft_body` of a refused draft, `error`, `summary`, `review_notes`, `revision_base`, the captured `profile_snapshot` and `retryable`; an unknown run id is an error (404 over HTTP).

#### Scenario: Reading a refused run
- **WHEN** a run's document failed review
- **THEN** `get_documentation_run` returns the refused `draft_title` and `draft_body` beside the findings in `error`

### Requirement: Restart admits unfinished runs again
The system SHALL, when the server starts, admit every unfinished documentation run again under its own run id and in its original admission order, restarting a running one from scratch with the current documentation model and writing profile. A run waiting for an outside agent keeps waiting.

#### Scenario: Server restarts mid-run
- **WHEN** the server restarts while a run is running and another is queued behind it
- **THEN** the running run starts again first and the queued run keeps its place behind it

#### Scenario: Server restarts while an agent run waits
- **WHEN** the server restarts while a run is `waiting_for_agent`
- **THEN** the run still reports `waiting_for_agent`

### Requirement: Runs that cannot be admitted after a restart
The system SHALL finish a run that had already written its document as `document_written`, and SHALL fail a run that cannot be admitted again with an error that names the reason and says Retry starts it again. In quarantine no run is admitted again; each fails with an error saying so.

#### Scenario: A run cannot be admitted again
- **WHEN** the server restarts while a run is queued and its documentation model has no key any more
- **THEN** the run reports `status` `failed` with an error naming the missing key and saying Retry starts it again

#### Scenario: Server restarts in quarantine
- **WHEN** the server starts with `--quarantine` while a run is queued
- **THEN** the run reports `status` `failed` with an error saying the server runs in quarantine

### Requirement: Profile snapshot at admission
The system SHALL capture the documentation instructions, review instructions and all writing profiles at admission and record on the run the selected guidance, exposure, template, audience and their versions (`profile_revisions`, `profile_snapshot`), so edits saved while a run is queued or running do not change that run.

#### Scenario: Template edited during a run
- **WHEN** a writer saves a new `billing-docs/how-to` template while a `how-to` run is queued
- **THEN** that run writes against the template version captured at admission

### Requirement: Guideline set resolution
The system SHALL use a request's named set and type as given; otherwise the run makes one forced model choice among the configured sets and types left open by the request, with the instance's default profile as the stated preference, sends an invalid pair back once, and ends `nothing_written` when it still cannot settle a configured pair, when no set is configured, or when the chosen set's template text is empty.

#### Scenario: Model picks a pair that does not exist
- **WHEN** the resolution turn twice chooses a set and type that do not appear together
- **THEN** the run ends `nothing_written` without falling back to an unconfigured set

### Requirement: Runs read only within the profile's audience
The system SHALL run each documentation run for its profile's audience (see the `audiences` capability), reading only statements, names and media that audience may see, and SHALL end the run `nothing_written` when the profile's audience is no longer configured.

#### Scenario: External profile
- **WHEN** a profile writes for an external audience and a cited statement is internal-only
- **THEN** the run's reads never return that statement and its emit cannot cite it

### Requirement: Runs are read-only over knowledge
The system MUST offer the writing model only read tools (`search_statements`, `get_statements`, `get_entity`, `list_statements`, `grep_statements`, `discover_facts`, `list_link_types`, `list_entity_link_types`, `list_statement_kinds`), `report_knowledge_gap` and the terminal `emit_document`, so a run can file knowledge gaps but cannot change statements, entities or links or enter the draft pipeline.

#### Scenario: Unsupported section
- **WHEN** the template asks for a section the knowledge base cannot support
- **THEN** the run may file a knowledge gap with `report_knowledge_gap`
- **AND** no statement or draft is created

### Requirement: Concept-anchored opening read
The system SHALL, for a run about a concept (an anchored request, or a revision of an anchored document), read the concept's names and description and up to 200 statements that mention it before the first writing turn and give them to the writer as already retrieved; an opening search of the prompt (`recon_k` results per part, default 30) also runs and counts toward the operation cap.

#### Scenario: Anchored request
- **WHEN** a writer requests a document with `anchor_entity_id` set to the SSO concept
- **THEN** the writer's first message carries the SSO concept's names and the statements mentioning it
- **AND** those statements may be cited without further reads

### Requirement: Grounding gate on emit
The system MUST refuse to record an emitted document whose title is blank or has no letters or digits, whose body is blank, that cites no statement ids, that cites an id outside the run's audience or one the run never retrieved, or that uses internal vocabulary (the word `substrate`, `stm_`/`ent_` ids, or tool names); a refused emit is sent back to the writer up to 3 times, after which the run ends `nothing_written`.

#### Scenario: Citation the run never read
- **WHEN** the writer emits a document citing a statement id no read returned
- **THEN** the emit is refused and the writer is told to retrieve it or cite only what it read

#### Scenario: Document resting on nothing
- **WHEN** the writer emits a document with empty `statement_ids`
- **THEN** no document is recorded

### Requirement: Independent review gate
The system MUST put every grounded document through a separate review conversation, without the writer's conversation, that reports `exposure` (`pass`, `fail`, or `unchecked` when the profile has neither exposure rules nor an audience) and `conformance` (`pass` or `fail`) with findings; the document is recorded only when exposure is not `fail` and conformance is `pass`, and a review that cannot run or is malformed refuses it.

#### Scenario: What the reviewer sees
- **WHEN** a grounded document is reviewed
- **THEN** the reviewer receives the request, the title and body, each cited statement's id, kind and text, the profile's exposure rules, template and audience, and the alt text of placed media
- **AND** it does not receive who changed the statements or when

#### Scenario: Review fails once
- **WHEN** the first review fails conformance
- **THEN** the writer gets one fresh attempt briefed with the findings
- **AND** a second failure ends the run `nothing_written` with the findings in `error` and the refused draft kept on the run

### Requirement: Run budgets
The system SHALL bound each run by the documentation limits (operation cap default 150, wall clock default 900 seconds, `max_tokens` default 32000 per turn, per-call timeout and retries) and, when a budget is exhausted or the model fails, make one final forced emit that still passes the grounding and review gates, ending `nothing_written` when it does not.

#### Scenario: Wall clock exhausted
- **WHEN** a run reaches its wall-clock budget before emitting
- **THEN** it makes one forced emit attempt and records nothing unless that document passes both gates

### Requirement: Run summary and trace
The system SHALL record on each run a `summary` with `activity` while running, `turns`, `duration_s`, `tokens`, `statements_retrieved`, `statements_cited`, `gaps_filed` and, for a refused review, `review_findings`; when `MYCELIUM_DOCGEN_TRACE_LOG` names a file, each run also appends one JSON line with its turns, tool calls and per-turn usage keyed by the run id.

#### Scenario: Polling a running run
- **WHEN** a caller reads a running run
- **THEN** `summary.activity` says what the run is currently doing

### Requirement: Document identity and creation
The system SHALL key a document on its guideline set, document type and a slug derived from the title (lowercased, non-word runs replaced by `-`, at most 80 characters), assigning ids prefixed `gdc_`; a creation run whose identity matches a stored document with a different body is refused rather than overwriting it, and a run without a target or anchor never writes into an existing document.

#### Scenario: Two unrelated requests choose the same title
- **WHEN** a second creation run emits title "Exporting invoices" under the same profile and type as an existing document with a different body
- **THEN** the run fails with a write refusal and the existing document is unchanged

### Requirement: Anchored document identity
The system SHALL treat `anchor_entity_id` together with `guideline_set` and `document_type` (both required alongside it) as a document's identity: a repeat request for the same concept, profile and type revises the document holding that identity at its current revision, and a new anchored document whose slug is taken gets a numbered slug. The model never decides which document a request updates.

#### Scenario: Repeat anchored request
- **WHEN** a writer requests `anchor_entity_id` SSO with `billing-docs` and `how-to` and such a document exists
- **THEN** the run revises that document instead of creating a second one

#### Scenario: Anchor without profile and type
- **WHEN** a request names an anchor but no `document_type`
- **THEN** the request is refused

### Requirement: Anchors follow concept merges and deletes
The system SHALL move a document's anchor to the surviving concept when concepts merge, unless the survivor already anchors a document of the same profile and type, in which case the merged-away concept's document loses its anchor; deleting a concept clears its anchors; both report `documents_unanchored`, documents keep their bodies and history, and an in-flight run writes under the anchor its concept has by then.

#### Scenario: Merge where both concepts have a document
- **WHEN** concept A and concept B each anchor a `billing-docs` `how-to` and A is merged into B
- **THEN** B's document keeps the identity, A's document becomes unanchored, and `documents_unanchored` is 1

### Requirement: Immutable revisions
The system SHALL store every saved version of a document as an immutable numbered revision with its body, title, cited `statement_ids`, review, run id and parent revision, list them newest first without bodies through `list_document_revisions`, return one with its delivery receipt through `get_document_revision`, and diff a revision against its parent through `GET /api/documentation/documents/{id}/revisions/{revision}/diff`.

#### Scenario: Reading an old revision
- **WHEN** a reader opens revision 1 of a document now at revision 3
- **THEN** revision 1's body and review are returned unchanged

### Requirement: Revising a document
The system SHALL expose `revise_document(document_id, expected_revision, prompt, provider?, start_from_destination?, update_sources?)`, advertised over MCP, that starts a run revising exactly that revision under the document's own profile and type; it requires a nonblank prompt unless `update_sources` is true, and a stale `expected_revision` is refused (409 over HTTP).

#### Scenario: Stale revision
- **WHEN** a writer revises with `expected_revision` 2 while the document is at revision 3
- **THEN** the request is refused asking to reload, and no run is created

### Requirement: Bringing an out-of-date document current
The system SHALL, for `update_sources=true`, brief the revision with the changed cited statements and placed media (up to 10 statement changes spelled out, each text clipped to 300 characters), appended after any prompt, and refuse when the document is not out of date.

#### Scenario: Nothing changed
- **WHEN** a writer revises a current document with `update_sources=true` and a blank prompt
- **THEN** the request is refused because nothing it cites or shows changed

### Requirement: Manual edits are grounded and reviewed
The system SHALL accept a manual edit (`POST /api/documentation/documents/{id}/edits` with `title` up to 300 characters, `body` up to 200000 characters and `expected_revision`, or `POST /api/documentation/runs/{run_id}/edits` for a finished run's unsaved draft) as a run that must keep the supplied text unchanged, find statements supporting it and pass the review gate; it is saved only then, and is not retryable as a run.

#### Scenario: Manual edit with unsupported claims
- **WHEN** a writer edits a document to add a claim no statement supports
- **THEN** the edit run ends `nothing_written` and the document keeps its current revision

### Requirement: Retrying a run that wrote nothing
The system SHALL let a writer retry a run whose outcome is `nothing_written` or `failed` through `POST /api/documentation/runs/{run_id}/retry`, starting a new run with the same request, profile, type and concept (or a revision of the same document); with `with_review_notes` true the new run's writer, and only the writer, is briefed with the refusing review's findings, which it lists as `review_notes`.

#### Scenario: Retry with notes
- **WHEN** a writer retries a review-refused run with `with_review_notes` true
- **THEN** a new run starts whose `review_notes` hold the earlier failed findings
- **AND** its review reads the unchanged request

#### Scenario: Retrying a written run
- **WHEN** a writer retries a run whose outcome is `document_written`
- **THEN** the retry is refused

### Requirement: Document freshness
The system SHALL report `stale` on `list_generated_documents` and `get_generated_document` with `status` `unknown` (saved before citations were recorded), `current` or `out_of_date`, comparing the cited statement text recorded at review with the current text and the document audience's visibility; `changes` give `statement_id`, `change` (`edited`, `deleted`, `merged`, `no_longer_visible`), `old_text`, `new_text` and `merged_into`, and `media_changes` give `media_id`, `change` and `alt_text`.

#### Scenario: Cited statement edited
- **WHEN** a statement cited by a document's current revision is reworded
- **THEN** the document reports `stale.status` `out_of_date` with an `edited` change carrying old and new text

#### Scenario: Reverted edit
- **WHEN** a cited statement is edited and then edited back to its recorded text
- **THEN** the document reports `current`

### Requirement: Reading documents
The system SHALL list documents newest first without bodies through `list_generated_documents` and return one with its body through `get_generated_document` (advertised over MCP) or `GET /api/documentation/documents/{id}`, each carrying `stale`, `audience`, `current_revision`, `published_revision`, `delivery_status` (`unpublished`, `changes_pending`, `published`, `merged` or `closed`), `pull_request` and `anchor_entity_id`; HTTP reads add rendered `body_html`.

#### Scenario: Newer revision not yet published
- **WHEN** a published document gets a new internal revision
- **THEN** its `delivery_status` is `changes_pending`

### Requirement: Maintenance policy per profile
The system SHALL act on out-of-date documents according to their profile's `maintenance` policy: `manual` does nothing unless the profile's plan review is `ai`, `propose` (and `manual` under an `ai` plan review) adds a high-priority `update` item to the profile's plan briefed with the changes, and `auto-revise` starts a revision briefed with the changes; each out-of-date revision is acted on at most once, and a background sweep runs every 60 seconds and keeps its decisions across restarts.

#### Scenario: Auto-revise after a cited edit
- **WHEN** a statement cited by an `auto-revise` profile's document is edited and stays unchanged for the quiet period
- **THEN** one revision run starts for that document

#### Scenario: Manual profile reviewed by AI
- **WHEN** a statement cited by a document of a `manual` profile whose plan review is `ai` is edited
- **THEN** an update item for that document is proposed to the AI reviewer

### Requirement: Automatic revision guard rails
The system MUST NOT start an automatic revision before the document's changes have been unchanged for `quiet_minutes` (default 30; new changes restart the wait), beyond `revisions_per_day` per profile in any 24 hours (default 5), while the active-run limit is full, or while documentation model credentials are missing; neither policy acts while a hidden cited statement awaits its new label or grant confirmation, or for a document dismissed in the plan.

#### Scenario: Burst of edits
- **WHEN** three cited statements are edited ten minutes apart
- **THEN** a single automatic revision starts 30 minutes after the last change

### Requirement: Automatic republishing
The system SHALL publish a successful automatic revision of a previously published document to the same destination, updating its open pull request or opening a new one, and leave a never-published document internal; a refused or failed automatic revision, one a restart interrupted before its run was admitted, or an interrupted publication is reported, not retried.

#### Scenario: Published document auto-revised
- **WHEN** an automatic revision of a document with an open pull request is written
- **THEN** the pull request is updated with the new revision and still awaits a person's merge

### Requirement: Maintenance feed
The system SHALL report maintenance activity through `GET /api/documentation/maintenance` as up to 100 entries, each with document, revision, `action`, `state` (`proposed`, `approved`, `dismissed`, `running`, `revised`, `refused` or `failed`), changes, run, `new_revision`, error, delivery, pull request and `waiting`; entries older than 30 days are omitted unless still waiting on a person.

#### Scenario: Proposal awaiting approval
- **WHEN** a `propose` profile's document went out of date and its item is not yet approved
- **THEN** the feed lists it with `state` `proposed` and `waiting` true

### Requirement: Documentation planning
The system SHALL let a real writer start a plan for a profile through `POST /api/documentation/plans/{guideline_set}` or the MCP tool `request_documentation_plan`, which returns the plan's summary: one background model call, or a `documentation_planning` agent task under External agent, that sees the profile's audience, templates, documents and an overview of what the audience may see (capped by `max_entities` and `max_capabilities`); one plan per profile runs at a time.

#### Scenario: Agent requests a plan
- **WHEN** a writer's agent calls `request_documentation_plan("billing-docs")` while documentation planning is set to External agent
- **THEN** a plan is created waiting for an agent and the result carries its `agent_task`

#### Scenario: Second plan while one runs
- **WHEN** a writer starts a plan for a profile that already has one running
- **THEN** the request is refused

#### Scenario: Profile that cannot be planned
- **WHEN** a writer plans a profile without a template, or whose audience was retired
- **THEN** the request is refused and no plan is created

#### Scenario: Restart during planning
- **WHEN** the server restarts while a plan is running
- **THEN** the plan is marked failed with error `orphaned by restart`

### Requirement: Plan items are filtered
The system SHALL keep a proposed plan item only when its template belongs to the profile, its concept is in the overview, an `update` names one of the profile's documents, it draws on at least one statement the audience may see, and it duplicates no existing document, other item or dismissed proposal, up to `max_items` (default 15); the plan reports dropped counts by reason.

#### Scenario: Proposal citing hidden statements only
- **WHEN** the planner proposes a document drawing only on statements the audience may not see
- **THEN** the item is dropped and counted under "no visible statements"

#### Scenario: Create for a concept that already has a document
- **WHEN** the planner proposes creating a `how-to` about the SSO concept and the profile already has an SSO `how-to`
- **THEN** the item is kept as an update of that document

### Requirement: Plan view
The system SHALL return a profile's plan through `GET /api/documentation/plans/{guideline_set}` with its audience, latest plan summary, items with their run state, out-of-date documents, up to 25 concepts with at least `coverage_min_statements` (default 10) visible statements and no anchored document of the profile, the visible statement count, statements newly visible since the last plan, and `replan_hint` once that count reaches `replan_hint_statements` (default 25).

#### Scenario: Concept without a document
- **WHEN** the SSO concept has 12 statements the audience may see and no document of the profile about it
- **THEN** it is listed among the concepts without a document

### Requirement: Approving, retrying and dismissing plan items
The system SHALL start each approved item's run through `POST /api/documentation/plan-items/approve` (at most `approve_batch` items, default 2, each reporting its own run or error): `request_documentation` with the item's concept for a `create`, a revision for an `update`, or an `update_sources` revision for a maintenance item; an item is approved once, and a run that cannot start returns it to proposed.

#### Scenario: Batch over the limit
- **WHEN** a writer approves three items with the batch limit at 2
- **THEN** the request is refused

#### Scenario: Maintenance item after a newer revision
- **WHEN** a maintenance item is approved after its document was revised again
- **THEN** that item reports that the document was revised since it was proposed, and stays proposed

### Requirement: Retrying and dismissing plan items
The system SHALL retry an approved item whose run wrote nothing through `POST /api/documentation/plan-items/{id}/retry` (optionally `with_review_notes`), the item following the new run, and remember a dismissal per profile so later plans drop the same proposal; dismissing an out-of-date document lasts until its next revision.

#### Scenario: Dismissed out-of-date document
- **WHEN** a writer dismisses an out-of-date document in the plan
- **THEN** it stops being listed and auto-revised until its next revision

#### Scenario: Dismissed proposal
- **WHEN** a writer dismisses a `create` item and later re-plans
- **THEN** the same proposal is dropped as "dismissed before"

### Requirement: Documentation destinations
The system SHALL publish only to destinations saved by an admin in the documentation settings, each with a unique name, GitHub owner, repository, base branch, path template and credential binding (an environment binding from `MYCELIUM_GITHUB_CREDENTIALS`, mapping a name to `host` and `token_env`, or a GitHub App connection); `list_documentation_destinations` reports names, path templates and coordinates without any credential or environment variable name.

#### Scenario: Path template escaping the root
- **WHEN** an admin saves a destination with path template `../docs/{slug}.md`
- **THEN** the settings save is refused

#### Scenario: Path template fields
- **WHEN** a path template uses a field other than `{slug}`, `{guideline_set}` or `{document_type}`, or starts with `/` or `-`
- **THEN** the destination is refused

### Requirement: Publishing a document
The system SHALL publish a selected revision through HTTP `POST /api/documentation/documents/{id}/delivery` for a real writer, or the MCP tool `deliver_document`, refused unless the document's profile `delivery` is `agents`, by committing it to branch `mycelium/docs/<slug>-<document id>` and opening or updating a pull request against the base branch; publication never merges, and a failure leaves the internal document saved and retryable without a new run.

#### Scenario: First publication
- **WHEN** a writer publishes revision 1 of "Exporting invoices" to destination `docs-repo` with template `docs/{slug}.md`
- **THEN** a pull request is opened adding `docs/exporting-invoices.md`
- **AND** the result carries `destination`, `path`, `reference`, `content_revision`, `pull_request_number` and `revision`, and the document reports `published_revision` 1

#### Scenario: Agent delivery off
- **WHEN** an agent calls `deliver_document` for a document whose profile's `delivery` is `people`
- **THEN** the call is refused naming the setting, and nothing is sent to GitHub

#### Scenario: Agent delivery on
- **WHEN** a writer turns on Agents may deliver for the profile and the agent calls `deliver_document` again
- **THEN** the pull request is opened as a person's publication would open it

#### Scenario: Quarantined server
- **WHEN** a writer publishes while the server runs in quarantine (see the `operations` capability)
- **THEN** publication is refused and nothing is sent to GitHub

### Requirement: Profile destinations
The system MUST refuse to publish a document, whoever publishes it and including automatic republishing, to a destination its profile's `destinations` do not name; a profile without destinations publishes to any destination.

#### Scenario: Destination the profile does not name
- **WHEN** a writer publishes a document of a profile whose destinations are `staff-wiki` to destination `help-site`
- **THEN** publication is refused naming the profile's destinations, and nothing is sent to GitHub

### Requirement: Recorded destination is reused
The system SHALL publish a document that was published before only to its recorded destination, repository, branch, path and credential binding, even if the destination settings change, and refuse when that binding or connection is no longer available or no longer authorized for the recorded host or repository.

#### Scenario: Different destination for a published document
- **WHEN** a writer publishes an already-published document to another destination name
- **THEN** publication is refused asking to use its recorded destination

### Requirement: Publication does not overwrite edits made on GitHub
The system MUST refuse publication when the file on the open pull request branch (or on the base branch when no pull request is open) holds text Mycelium did not publish or derive the revision from, and when the file was deleted in the open pull request.

#### Scenario: Reviewer edited the PR branch
- **WHEN** someone commits to the document's pull request branch and a writer publishes a manual edit made without reading it
- **THEN** publication is refused asking to revise the document first

### Requirement: Revisions start from the published copy
The system SHALL start a model revision of a published document from its GitHub copy when that copy holds someone's edits and the internal head was published (`revision_base` `destination`), refuse with 409 code `both_sides_edited` when the GitHub copy and an unpublished internal revision both changed unless `start_from_destination` is true, and refuse the revision when the published copy cannot be read.

#### Scenario: Both sides edited
- **WHEN** revision 3 was never published and the pull request branch was also edited
- **THEN** `revise_document` is refused with code `both_sides_edited`
- **AND** retrying with `start_from_destination` true starts from the GitHub text and keeps revision 3 in history

### Requirement: Pull request state tracking
The system SHALL, when a document with a pull request is read, ask GitHub for its state at most once per 60 seconds, record `open`, `merged` or `closed` with `pull_request.refreshed_at`, stop asking once it is merged, and keep the last known state when GitHub cannot be reached.

#### Scenario: GitHub unreachable
- **WHEN** a reader opens a document while GitHub is unreachable
- **THEN** the document is returned with its last known pull request state

### Requirement: GitHub App connection
The system SHALL let only an admin connect GitHub App repositories through the `/api/github` routes, available when `MYCELIUM_GITHUB_APP_ID`, `MYCELIUM_GITHUB_APP_CLIENT_ID`, `MYCELIUM_GITHUB_APP_CLIENT_SECRET`, `MYCELIUM_GITHUB_APP_SLUG`, `MYCELIUM_GITHUB_APP_PRIVATE_KEY_FILE` and `MYCELIUM_GITHUB_APP_CALLBACK_URL` are set; mutating calls must be same-origin JSON requests.

#### Scenario: Non-admin starts a connection
- **WHEN** a writer calls `POST /api/github/start`
- **THEN** the request is refused with 403

#### Scenario: Invalid callback URL
- **WHEN** the callback URL is not HTTPS (HTTP is allowed only on localhost or loopback), does not end in `/api/github/callback`, or uses another origin than the instance
- **THEN** connecting reports that GitHub App setup is incomplete or that the callback must use this instance's origin

### Requirement: GitHub connection setup state
The system SHALL hold connection setup state and temporary user tokens only in server memory for 10 minutes, bound to the admin and browser session, limited to 1000 pending attempts, so an expired setup or a restart requires connecting again; installation tokens are minted on demand, restricted to the selected repository with contents and pull request write permission, and never stored.

#### Scenario: Setup expires
- **WHEN** an admin returns from GitHub more than 10 minutes after starting
- **THEN** the callback reports that setup expired and asks to connect again

### Requirement: Repository choice is verified
The system SHALL offer only repositories, on github.com, that both the App installation (with Contents and Pull requests write permission, not suspended) and the admin's GitHub account can push to, omitting archived and disabled ones, verify the repository and base branch when connecting, and re-verify installation access to the repository on each publish or read; a saved connection cannot be re-pointed to a different repository.

#### Scenario: Archived repository
- **WHEN** an installation includes an archived repository
- **THEN** it is not offered in the repository picker

### Requirement: Disconnecting and restoring connections
The system SHALL disable a connection on disconnect without uninstalling the App or touching documents, publication history or pull requests, refuse publishing through a disabled connection until an admin reconnects it, and restore archived connections disabled.

#### Scenario: Publishing after restore
- **WHEN** an instance archive is restored and a writer publishes through a restored App connection
- **THEN** publication is refused until an admin reconnects that repository

### Requirement: Documentation storage
The system SHALL keep runs, documents, revisions, delivery receipts, plans, plan items, dismissals and maintenance decisions in `mycelium-drafts.db` and profiles and GitHub connections in the prompt store, and include them in instance exports, the documentation tables as the `documentation.json` archive member (see the `storage-and-backup` capability).

#### Scenario: Export includes documents
- **WHEN** an operator exports the instance
- **THEN** the archive contains `documentation.json` with the document library and its revisions

### Requirement: Planning policy per profile
The system SHALL keep a `planning` policy per profile, saved with the profile, and MUST refuse a planning text other than `off`, `propose` or `write`; a missing or unknown planning text reads as `off`.

#### Scenario: Existing profile after the upgrade
- **WHEN** a profile saved before the planning policy existed is read
- **THEN** its planning policy is `off`

### Requirement: Uncovered statements
The system SHALL treat a statement as uncovered for a profile when the profile's audience may see it, no document of the profile cites it and it was not dismissed for the profile through `POST /api/documentation/plans/{guideline_set}/uncovered/{statement_id}/dismiss`; the plan view reports their count, up to 50 of them (capabilities and procedures, then the most connected, first), the count of dismissed statements and the profile's planning policy.

#### Scenario: Statement no document cites
- **WHEN** the audience may see a statement that no document of the profile cites
- **THEN** the plan view counts and lists it as uncovered

#### Scenario: Dismissed statement
- **WHEN** a writer dismisses an uncovered statement for a profile
- **THEN** the profile's uncovered count drops by one and later plans are not offered it

### Requirement: Plans place uncovered statements
The system SHALL give each plan up to `max_uncovered` (default 40) of the profile's uncovered statements, those no earlier plan of the profile was offered first, and the opening of each existing document; an approved `update` that lists statements its document does not cite is briefed with those statements and their current text, as long as the audience may still see them.

#### Scenario: More uncovered statements than one plan places
- **WHEN** a profile has 60 uncovered statements, `max_uncovered` is 40 and a plan was offered 40 of them
- **THEN** the next plan is offered the 20 it was not offered first

#### Scenario: Update placing uncovered statements
- **WHEN** a writer approves an update item listing an SSO statement the sign-in document does not cite
- **THEN** the revision is briefed to add that statement, quoting its text

### Requirement: Automatic planning per profile
The system SHALL plan by itself, from the 60-second maintenance sweep, for a profile whose `planning` policy is `propose` or `write` once at least `replan_hint_statements` (default 25) of its uncovered statements were offered to no plan of the profile; under `propose` items wait for approval, and under `write` the sweep approves the plan's proposed items in order, or only those the reviewer approved when plan review is `ai`.

#### Scenario: Propose profile with new knowledge
- **WHEN** 30 statements the audience may see and no document cites are added to a `propose` profile's knowledge base
- **THEN** one plan starts by itself and its items wait for approval

### Requirement: Automatic planning guard rails
The system MUST NOT plan automatically while a plan of the profile runs, while its latest plan still has a proposed item or an approved item whose run has not finished, after its last automatic plan failed until a person plans, or while the planning model's credentials are missing; and MUST NOT start more than `approve_batch` automatic items per sweep or any while the active-run limit is full. An item whose run could not start is left proposed for a person.

#### Scenario: Write profile within limits
- **WHEN** an automatic plan of a `write` profile proposes three items with `approve_batch` at 2
- **THEN** two runs start in one sweep and the third in a later sweep

### Requirement: Plan review and delivery settings per profile
The system SHALL keep a `plan_review` setting (`person` or `ai`) and a `delivery` setting (`people` or `agents`) per profile, saved with the profile, and MUST refuse other texts for them; a missing or unknown `plan_review` reads as `person` and a missing or unknown `delivery` as `people`.

#### Scenario: Existing profile after the upgrade
- **WHEN** a profile saved before these settings existed is read
- **THEN** its plan review is `person` and its delivery is `people`

### Requirement: AI plan review
The system SHALL, from the 60-second maintenance sweep, have an AI reviewer decide every undecided proposed item of a profile whose `plan_review` is `ai`, out-of-date update items included, approving or dismissing each with a reason the plan view shows. It runs through the documentation planning action: a model call separate from the planner's, or a `plan_review` agent task under External agent; one review per profile at a time.

#### Scenario: Reviewer approves one item and dismisses another
- **WHEN** the reviewer approves "Export invoices" and dismisses "Invoice limits" as a duplicate
- **THEN** "Export invoices" starts its run and "Invoice limits" is dismissed, each showing the reviewer's reason
- **AND** a later plan drops "Invoice limits" as dismissed before

#### Scenario: Review that fails
- **WHEN** the review's model call fails, or its decisions leave an item undecided
- **THEN** its items stay proposed, marked as not reviewed with the reason, and are not reviewed again automatically

### Requirement: AI plan review limits
The system MUST start the runs of items the reviewer approved only within `approve_batch` per sweep and while the active-run limit has room, starting the rest on later sweeps; an approved item stays proposed until its run starts, and a person may still decide an item the reviewer has not.

#### Scenario: More approvals than the batch
- **WHEN** the reviewer approves three items with `approve_batch` at 2
- **THEN** two runs start at once and the third on a later sweep

### Requirement: Starter profiles
The system SHALL package three starters, `kb-authoring` (knowledge base), `help-center` (for `external-non-technical`) and `internal-guide` (for `internal-non-technical`), each with guidance, disclosure rules and templates, and guidance that names no profile row, file or path and asks the writer no question.

#### Scenario: Starter templates
- **WHEN** an editor lists the starters
- **THEN** `kb-authoring` offers `tutorial`, `how-to`, `reference`, `explanation` and `troubleshooting`, `help-center` offers `how-to`, `troubleshooting` and `explanation`, and `internal-guide` offers `reference`, `explanation`, `how-to` and `troubleshooting`

#### Scenario: Starters are not seeded
- **WHEN** a fresh instance starts
- **THEN** only `kb-authoring` is stored, and `help-center` and `internal-guide` are offered as starters only

### Requirement: Using a starter
The system SHALL return the starters, with their title, description, audience and texts, from `GET /api/documentation/starters` to any authenticated caller, storing nothing; a profile made from or reset to a starter SHALL be saved through the profile save, under its roles and revision check.

#### Scenario: Creating a profile from a starter
- **WHEN** a writer chooses New from starter, Internal guide, and saves the profile as `internal-guide`
- **THEN** profile `internal-guide` writes for `internal-non-technical` with the starter's guidance, disclosure rules and four templates

#### Scenario: Resetting a profile to a starter
- **WHEN** an admin resets profile `kb-authoring` to the Help center starter and saves
- **THEN** its guidance, disclosure rules and templates become the starter's, templates the starter lacks are retired, and its audience, policies and destinations are unchanged
