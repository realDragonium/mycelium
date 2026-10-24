## ADDED Requirements

### Requirement: Documentation briefs carry the profile
The system SHALL include in every `documentation`, `document_review`, `documentation_planning` and `plan_review` brief a `profile` with the writing profile's name, revision, audience (id, name, scope and description), guidance, disclosure rules, templates (only the chosen one for a document), maintenance, planning, plan review and delivery policies and destinations.

#### Scenario: Review brief
- **WHEN** an agent claims a `document_review` task for a profile writing for `external-technical`
- **THEN** its brief's `profile` holds that profile's guidance, disclosure rules, the document's template and the audience's description
