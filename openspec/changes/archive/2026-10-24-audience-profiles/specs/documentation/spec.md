## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Profile destinations
The system MUST refuse to publish a document, whoever publishes it and including automatic republishing, to a destination its profile's `destinations` do not name; a profile without destinations publishes to any destination.

#### Scenario: Destination the profile does not name
- **WHEN** a writer publishes a document of a profile whose destinations are `staff-wiki` to destination `help-site`
- **THEN** publication is refused naming the profile's destinations, and nothing is sent to GitHub

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
