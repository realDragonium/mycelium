## MODIFIED Requirements

### Requirement: Writing profiles are guideline-set rows
The system SHALL store each writing profile (guideline set) as prompt-store rows of type `guideline-set` named `<set>/<slot>`, where the slot is `guidance` (set-wide writing instructions), `exposure` (set-wide disclosure boundary), `audience` (the id of the audience the set writes for), `maintenance` (`manual`, `propose` or `auto-revise`), `planning` (`off`, `propose` or `write`), or a document type whose row is that type's template; any other slot name is a document type the set can write.

#### Scenario: Listing what a profile can write
- **WHEN** the live rows are `billing-docs/guidance`, `billing-docs/exposure`, `billing-docs/how-to` and `billing-docs/reference`
- **THEN** the catalogue offers profile `billing-docs` with document types `how-to` and `reference`
- **AND** `guidance` and `exposure` are not offered as document types

#### Scenario: Retired rows leave the catalogue
- **WHEN** every row of a profile is retired
- **THEN** the profile is no longer offered to runs, planning or the generate form

### Requirement: Profile names and reserved slots
The system MUST refuse profile and template names that are blank, contain `/` or have surrounding whitespace, MUST refuse a template named `guidance`, `exposure`, `audience`, `maintenance` or `planning`, MUST refuse duplicate template names within one save, and MUST refuse a maintenance text other than `manual`, `propose` or `auto-revise`; a stored maintenance text that is not one of those reads as `manual`.

#### Scenario: Reserved template name
- **WHEN** a writer saves a profile with a template named `exposure`
- **THEN** the save is refused and nothing is written

## ADDED Requirements

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
The system SHALL plan by itself, from the 60-second maintenance sweep, for a profile whose `planning` policy is `propose` or `write` once at least `replan_hint_statements` (default 25) of its uncovered statements were offered to no plan of the profile; under `propose` the items wait for approval, and under `write` the sweep approves the automatic plan's proposed items in order, each run passing the usual document review.

#### Scenario: Propose profile with new knowledge
- **WHEN** 30 statements the audience may see and no document cites are added to a `propose` profile's knowledge base
- **THEN** one plan starts by itself and its items wait for approval

### Requirement: Automatic planning guard rails
The system MUST NOT plan automatically while a plan of the profile runs, while its latest plan still has a proposed item or an approved item whose run has not finished, after its last automatic plan failed until a person plans, or while the planning model's credentials are missing; and MUST NOT start more than `approve_batch` automatic items per sweep or any while the active-run limit is full. An item whose run could not start is left proposed for a person.

#### Scenario: Write profile within limits
- **WHEN** an automatic plan of a `write` profile proposes three items with `approve_batch` at 2
- **THEN** two runs start in one sweep and the third in a later sweep
