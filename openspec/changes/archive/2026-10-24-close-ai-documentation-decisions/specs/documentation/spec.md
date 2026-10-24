## MODIFIED Requirements

### Requirement: Writing profiles are guideline-set rows
The system SHALL store each writing profile (guideline set) as prompt-store rows of type `guideline-set` named `<set>/<slot>`, where the slot is `guidance`, `exposure`, `audience`, one of the policy slots `maintenance`, `planning`, `plan_review`, `delivery`, `delivery_destination` and `recovery`, or a document type whose row is that type's template; any other slot name is a document type the set can write.

#### Scenario: Listing what a profile can write
- **WHEN** the live rows are `billing-docs/guidance`, `billing-docs/exposure`, `billing-docs/how-to` and `billing-docs/reference`
- **THEN** the catalogue offers profile `billing-docs` with document types `how-to` and `reference`
- **AND** `guidance` and `exposure` are not offered as document types

#### Scenario: Retired rows leave the catalogue
- **WHEN** every row of a profile is retired
- **THEN** the profile is no longer offered to runs, planning or the generate form

### Requirement: Profile names and reserved slots
The system MUST refuse profile and template names that are blank, contain `/` or have surrounding whitespace, MUST refuse a template named `guidance`, `exposure`, `audience`, `maintenance`, `planning`, `plan_review`, `delivery`, `delivery_destination` or `recovery`, MUST refuse duplicate template names within one save, and MUST refuse a maintenance text other than `manual`, `propose` or `auto-revise`; a stored maintenance text that is not one of those reads as `manual`.

#### Scenario: Reserved template name
- **WHEN** a writer saves a profile with a template named `recovery`
- **THEN** the save is refused and nothing is written

### Requirement: Automatic republishing
The system SHALL publish a successful automatic revision of a previously published document to the same destination, updating its open pull request or opening a new one, and leave a never-published document internal unless the profile's delivery is `auto`; a refused or failed automatic revision, one a restart interrupted before its run was admitted, or an interrupted or failed publication is reported, and retried only while the profile's recovery is `ai`.

#### Scenario: Published document auto-revised
- **WHEN** an automatic revision of a document with an open pull request is written
- **THEN** the pull request is updated with the new revision and still awaits a person's merge

#### Scenario: Interrupted claim under AI recovery
- **WHEN** a restart interrupts an automatic revision of an `ai`-recovery profile before its run was admitted
- **THEN** a later sweep claims the revision again and starts its run

### Requirement: Retrying a run that wrote nothing
The system SHALL let a writer retry a run whose outcome is `nothing_written` or `failed` through `POST /api/documentation/runs/{run_id}/retry`, starting a new run with the same request, profile, type and concept (or document) that records it as `retry_of`, and that the earlier run's plan item or automatic revision follows; with `with_review_notes` true only the new run's writer is briefed with the refusing review's findings, listed as `review_notes`.

#### Scenario: Retry with notes
- **WHEN** a writer retries a review-refused run with `with_review_notes` true
- **THEN** a new run starts whose `review_notes` hold the earlier failed findings
- **AND** its review reads the unchanged request

#### Scenario: Retrying a written run
- **WHEN** a writer retries a run whose outcome is `document_written`
- **THEN** the retry is refused

### Requirement: Documentation planning
The system SHALL let a real writer start a plan for a profile through `POST /api/documentation/plans/{guideline_set}` or the MCP tool `request_documentation_plan`, and read it through `GET` on the same path or `get_documentation_plan`. A plan is one background model call by default, or an agent task under External agent, that sees the profile's audience, templates, documents and an overview of what the audience may see; one plan per profile runs at a time.

#### Scenario: Agent requests a plan
- **WHEN** a writer's agent calls `request_documentation_plan("billing-docs")` while documentation planning is set to External agent
- **THEN** a plan is created waiting for an agent and the result carries its `agent_task`

#### Scenario: Agent reads the plan
- **WHEN** a writer's agent calls `get_documentation_plan("billing-docs")`
- **THEN** it gets the plan view the Plan page shows, with items, reviews and uncovered statements

#### Scenario: Second plan while one runs
- **WHEN** a writer starts a plan for a profile that already has one running
- **THEN** the request is refused

#### Scenario: Profile that cannot be planned
- **WHEN** a writer plans a profile without a template, or whose audience was retired
- **THEN** the request is refused and no plan is created

#### Scenario: Restart during planning
- **WHEN** the server restarts while a plan is running
- **THEN** the plan is marked failed with error `orphaned by restart`

### Requirement: Uncovered statements
The system SHALL treat a statement as uncovered for a profile when the profile's audience may see it, no document of the profile cites it and it was not dismissed for the profile through `POST /api/documentation/plans/{guideline_set}/uncovered/{statement_id}/dismiss`, which `…/restore` undoes. The plan view reports their count, up to 50 of them (capabilities and procedures, then the most connected, first), and the dismissed ones the audience may still see.

#### Scenario: Statement no document cites
- **WHEN** the audience may see a statement that no document of the profile cites
- **THEN** the plan view counts and lists it as uncovered

#### Scenario: Dismissed statement
- **WHEN** a writer dismisses an uncovered statement for a profile
- **THEN** the profile's uncovered count drops by one and later plans are not offered it

#### Scenario: Restored statement
- **WHEN** a writer restores a dismissed statement
- **THEN** it counts as uncovered again and later plans are offered it

### Requirement: Automatic planning guard rails
The system MUST NOT plan automatically while a plan of the profile runs, while its latest plan still has a proposed item or an approved item whose run has not finished, after its last automatic plan failed until a person plans, or while the planning model's credentials are missing; and MUST NOT start more than `approve_batch` automatic items per sweep or any while the active-run limit is full. An item whose run could not start is left proposed for a person with the reason.

#### Scenario: Write profile within limits
- **WHEN** an automatic plan of a `write` profile proposes three items with `approve_batch` at 2
- **THEN** two runs start in one sweep and the third in a later sweep

### Requirement: Plan review and delivery settings per profile
The system SHALL keep a `plan_review` setting (`person` or `ai`), a `delivery` setting (`people`, `agents` or `auto`), a `delivery_destination` and a `recovery` setting (`person` or `ai`) per profile, saved with the profile, and MUST refuse other texts for the policies and a `delivery_destination` that names no configured destination; a missing or unknown `plan_review` reads as `person`, `delivery` as `people`, `recovery` as `person` and `delivery_destination` as none.

#### Scenario: Existing profile after the upgrade
- **WHEN** a profile saved before these settings existed is read
- **THEN** its plan review is `person`, its delivery is `people`, its recovery is `person` and it has no delivery destination

#### Scenario: Unknown destination
- **WHEN** a writer saves a profile with delivery `auto` and a destination that is not configured
- **THEN** the save is refused naming the destination

### Requirement: AI plan review
The system SHALL, from the 60-second maintenance sweep, have an AI reviewer decide every undecided proposed item of a profile whose `plan_review` is `ai`, out-of-date update items included, approving or dismissing each with a reason the plan view shows. It runs through the documentation planning action: a model call separate from the planner's, with the `plan_review` instructions and a fixed review contract, or a `plan_review` agent task under External agent; one review per profile at a time.

#### Scenario: Reviewer approves one item and dismisses another
- **WHEN** the reviewer approves "Export invoices" and dismisses "Invoice limits" as a duplicate
- **THEN** "Export invoices" starts its run and "Invoice limits" is dismissed, each showing the reviewer's reason
- **AND** a later plan drops "Invoice limits" as dismissed before

#### Scenario: Review that fails
- **WHEN** the review's model call fails, or its decisions leave an item undecided, and the profile's recovery is `person`
- **THEN** its items stay proposed, marked as not reviewed with the reason, and are not reviewed again automatically

#### Scenario: Review that fails under AI recovery
- **WHEN** every review of an `ai`-recovery profile's items fails with `retry_attempts` at 2
- **THEN** the items are reviewed three times and then stay proposed for a person, showing how often the review failed

### Requirement: Publishing a document
The system SHALL publish a selected revision through HTTP `POST /api/documentation/documents/{id}/delivery` for a real writer, or the MCP tool `deliver_document`, refused unless the document's profile `delivery` is `agents` or `auto`, by committing it to branch `mycelium/docs/<slug>-<document id>` and opening or updating a pull request against the base branch; publication never merges, and a failure leaves the internal document saved and retryable without a new run.

#### Scenario: First publication
- **WHEN** a writer publishes revision 1 of "Exporting invoices" to destination `docs-repo` with template `docs/{slug}.md`
- **THEN** a pull request is opened adding `docs/exporting-invoices.md`
- **AND** the result carries `destination`, `path`, `reference`, `content_revision`, `pull_request_number` and `revision`, and the document reports `published_revision` 1

#### Scenario: Agent delivery off
- **WHEN** an agent calls `deliver_document` for a document whose profile's `delivery` is `people`
- **THEN** the call is refused naming the setting, and nothing is sent to GitHub

#### Scenario: Agent delivery on
- **WHEN** a writer sets the profile's delivery to `agents` and the agent calls `deliver_document` again
- **THEN** the pull request is opened as a person's publication would open it

#### Scenario: Quarantined server
- **WHEN** a writer publishes while the server runs in quarantine (see the `operations` capability)
- **THEN** publication is refused and nothing is sent to GitHub

## ADDED Requirements

### Requirement: Automatic delivery
The system SHALL, from the 60-second maintenance sweep, publish once each finished run's revision of an `auto`-delivery profile that passed review and is still current: to the document's recorded destination, or for a document never published to the profile's `delivery_destination`, leaving it internal when there is none. The run records its `delivery` and `delivery_error`.

#### Scenario: Plan-item document delivered
- **WHEN** an approved plan item of an `auto` profile with destination `docs-repo` writes a new document
- **THEN** the next sweep opens a pull request for it in `docs-repo`, which still awaits the repository's merge

#### Scenario: Run finished before the upgrade
- **WHEN** a profile's delivery is set to `auto` after an upgrade
- **THEN** revisions written before the upgrade are not published by the sweep

#### Scenario: Publication that fails under AI recovery
- **WHEN** publishing a reviewed revision fails and the profile's recovery is `ai`
- **THEN** the run shows the error and a later sweep publishes it again, up to `retry_attempts` times

### Requirement: Recovering failed runs
The system SHALL, from the 60-second maintenance sweep, retry each finished run that wrote nothing of an `ai`-recovery profile, except manual edits, as a writer's retry would, briefed with the review's notes when the review refused it, within the active-run limit. After `retry_attempts` automatic retries (default 2) the run is given up with `recovery` `gave_up` and a `recovery_note` giving the last reason; a person's retry starts the count again.

#### Scenario: Refused revision retried with notes
- **WHEN** the review refuses an automatic revision of an `ai`-recovery profile
- **THEN** a later sweep starts a retry briefed with the review's findings, which the document's maintenance entry follows

#### Scenario: Run finished before the upgrade
- **WHEN** a profile's recovery is set to `ai` after an upgrade
- **THEN** runs that wrote nothing before the upgrade are not retried

#### Scenario: Given up after the attempts
- **WHEN** the second automatic retry with `retry_attempts` at 2 also writes nothing
- **THEN** no further retry starts and the run shows `recovery` `gave_up` with the reason

### Requirement: Recovering failed planning
The system SHALL, while a profile's recovery is `ai`, try a failed automatic plan, a failed plan review and a plan item that could not start again on later sweeps, up to `retry_attempts` times each, instead of waiting for a person; an item given up on, or whose review failed beyond those attempts, stays proposed for a person and no longer holds up automatic planning.

#### Scenario: Failed automatic plan under AI recovery
- **WHEN** every automatic plan of an `ai`-recovery profile fails with `retry_attempts` at 2
- **THEN** three plans are made, and the plan view says automatic planning gave up until someone plans

#### Scenario: Item that could not start
- **WHEN** an automatic item of an `ai`-recovery `write` profile cannot start once
- **THEN** it shows the reason and starts on a later sweep

### Requirement: Planning over several calls
The system SHALL let one plan make up to `max_calls` planning calls (default 1, at most 5) while uncovered statements no plan of the profile was offered remain; each call gets the next batch, the same overview and, as `already_proposed`, the items earlier calls kept, keeps up to `max_items` of its own, and merges an update of a document an earlier call updates into that item. The plan records its items, the statements offered, the dropped counts, the number of calls and their tokens together.

#### Scenario: Backlog larger than one batch
- **WHEN** a profile has 3 uncovered statements, `max_uncovered` is 2 and `max_calls` is 3
- **THEN** the plan makes two calls, the second told what the first proposed, and keeps the items of both
