## ADDED Requirements

### Requirement: Audiences over MCP
The system SHALL advertise `get_audiences(view, ...)` to readers, returning the audiences with their counts and the backfill's progress, one statement's label, statements by label state or by visibility to a live audience, an audience's pending external grants or a fresh sample of them, and the spot checks. It SHALL advertise `manage_audiences(request)` to real admins to create, save or retire an audience or run the backfill.

#### Scenario: Writer creates an audience
- **WHEN** a writer calls `manage_audiences` to create an audience
- **THEN** the call is refused for want of the admin role

### Requirement: Audience curation over MCP
The system SHALL advertise `curate_audiences(request)` to real writers and admins to set, confirm or clear a statement's curator label, decide a spot check, confirm or reject pending grants, or accept the rest after a sample, each decision recorded as the caller's.

#### Scenario: Agent confirms pending grants
- **WHEN** a writer agent confirms two pending external grants of an audience
- **THEN** both statements become visible to that audience, confirmed by that agent

#### Scenario: Drafter labels a statement
- **WHEN** a drafter sets a statement's label through `curate_audiences`
- **THEN** the call is refused for want of a real writer role
