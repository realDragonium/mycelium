## MODIFIED Requirements

### Requirement: Setup checklist
The system SHALL serve an admin-only `GET /api/setup` with the steps `credentials`, `models`, `audiences`, `profile`, `github` (optional) and `review`, each `done`, `todo` or `dismissed` with a detail and the settings screen it is completed on, plus `complete`, `blocked` and `quarantine`, computed from saved settings and counts without any provider request.

#### Scenario: Dismissing an optional step
- **WHEN** an admin sends `PUT /api/setup/steps/github` with `{"dismissed": true}` while no destination is set
- **THEN** the `github` step reports `dismissed`, and `complete` is true once every other step is done or dismissed

#### Scenario: Step done later
- **WHEN** a dismissed step's condition becomes satisfied
- **THEN** the step reports `done`
