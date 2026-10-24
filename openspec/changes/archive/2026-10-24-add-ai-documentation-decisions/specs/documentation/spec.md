## MODIFIED Requirements

### Requirement: Writing profiles are guideline-set rows
The system SHALL store each writing profile (guideline set) as prompt-store rows of type `guideline-set` named `<set>/<slot>`, where the slot is `guidance` (set-wide writing instructions), `exposure` (set-wide disclosure boundary), `audience` (the id of the audience the set writes for), `maintenance` (`manual`, `propose` or `auto-revise`), `planning` (`off`, `propose` or `write`), `plan_review` (`person` or `ai`), `delivery` (`people` or `agents`), or a document type whose row is that type's template; any other slot name is a document type the set can write.

#### Scenario: Listing what a profile can write
- **WHEN** the live rows are `billing-docs/guidance`, `billing-docs/exposure`, `billing-docs/how-to` and `billing-docs/reference`
- **THEN** the catalogue offers profile `billing-docs` with document types `how-to` and `reference`
- **AND** `guidance` and `exposure` are not offered as document types

#### Scenario: Retired rows leave the catalogue
- **WHEN** every row of a profile is retired
- **THEN** the profile is no longer offered to runs, planning or the generate form

### Requirement: Profile names and reserved slots
The system MUST refuse profile and template names that are blank, contain `/` or have surrounding whitespace, MUST refuse a template named `guidance`, `exposure`, `audience`, `maintenance`, `planning`, `plan_review` or `delivery`, MUST refuse duplicate template names within one save, and MUST refuse a maintenance text other than `manual`, `propose` or `auto-revise`; a stored maintenance text that is not one of those reads as `manual`.

#### Scenario: Reserved template name
- **WHEN** a writer saves a profile with a template named `exposure`
- **THEN** the save is refused and nothing is written

### Requirement: Maintenance policy per profile
The system SHALL act on out-of-date documents according to their profile's `maintenance` policy: `manual` does nothing unless the profile's plan review is `ai`, `propose` (and `manual` under an `ai` plan review) adds a high-priority `update` item to the profile's plan briefed with the changes, and `auto-revise` starts a revision briefed with the changes; each out-of-date revision is acted on at most once, and a background sweep runs every 60 seconds and keeps its decisions across restarts.

#### Scenario: Auto-revise after a cited edit
- **WHEN** a statement cited by an `auto-revise` profile's document is edited and stays unchanged for the quiet period
- **THEN** one revision run starts for that document

#### Scenario: Manual profile reviewed by AI
- **WHEN** a statement cited by a document of a `manual` profile whose plan review is `ai` is edited
- **THEN** an update item for that document is proposed to the AI reviewer

### Requirement: Documentation planning
The system SHALL let a real writer start a plan for a profile through `POST /api/documentation/plans/{guideline_set}` or `request_documentation_plan(guideline_set)`, advertised over MCP, which returns the new plan's summary: one background model call through the documentation planning action, or a `documentation_planning` agent task while that action is set to External agent, that sees the profile's audience description, templates, existing documents and an overview of what that audience may see (up to `max_entities` concepts and `max_capabilities` key statements, default 150 each); one plan per profile runs at a time.

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

### Requirement: Automatic planning per profile
The system SHALL plan by itself, from the 60-second maintenance sweep, for a profile whose `planning` policy is `propose` or `write` once at least `replan_hint_statements` (default 25) of its uncovered statements were offered to no plan of the profile; under `propose` the items wait for approval, and under `write` the sweep approves the automatic plan's proposed items in order, each run passing the usual document review, unless the profile's plan review is `ai`, when only the items the reviewer approved start.

#### Scenario: Propose profile with new knowledge
- **WHEN** 30 statements the audience may see and no document cites are added to a `propose` profile's knowledge base
- **THEN** one plan starts by itself and its items wait for approval

### Requirement: Publishing a document
The system SHALL publish a selected revision through HTTP `POST /api/documentation/documents/{id}/delivery` for a real writer, or `deliver_document(document_id, destination, expected_revision)`, advertised over MCP to real writers and admins and refused unless the document's profile `delivery` is `agents`, by committing it to branch `mycelium/docs/<slug>-<document id>` and opening or updating a pull request against the base branch; publication never merges, and a failure leaves the internal document saved and retryable without a new run.

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

## ADDED Requirements

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
