## ADDED Requirements

### Requirement: Writers and admins can propose instead of writing live
The system SHALL treat a real writer or admin whose request carries the propose-as-draft marker as a drafter for that request, so their substrate writes are queued onto their own open draft exactly as a drafter's are. A request without the marker SHALL be unchanged. The marker MUST only narrow: a reader or drafter sending it gains no permission.

#### Scenario: A writer proposes an edit
- **WHEN** a writer sends the marker while editing the text of "An invoice has a due date." and adding the statement "An export runs nightly."
- **THEN** both are queued on the writer's open draft and the live knowledge base is unchanged

#### Scenario: Without the marker
- **WHEN** the same writer edits a statement without the marker
- **THEN** the edit is written live and no operation is queued

#### Scenario: A reader sends the marker
- **WHEN** a reader sends a write with the marker
- **THEN** the write is refused as it would be without it

#### Scenario: Deciding drafts while proposing
- **WHEN** a writer sends the marker on a request to approve a draft
- **THEN** the request is refused, as it is for a drafter

### Requirement: Propose as draft mode in the web app
The web app SHALL offer writers and admins a **Propose as draft** mode that sends the marker on knowledge requests. While it is on, the web app SHALL show the caller's open draft with its operation count and a link to it, and SHALL let the person switch the mode off.

#### Scenario: The mode is on
- **WHEN** a writer with the mode on stages two changes
- **THEN** a banner shows two changes in their draft, linking to the draft

#### Scenario: Switching it off
- **WHEN** the writer switches the mode off and edits a statement
- **THEN** the banner is gone and the edit is written live
