## ADDED Requirements

### Requirement: Retired defaults stay on instances that ran with them
The system SHALL, on start, save a default instruction text a release stopped shipping as an action's version authored by `upgrade` when the instance recorded serving it and the action has no saved version, and SHALL do this for the previous `audience_labelling` default.

#### Scenario: Instance that ran the old labelling default
- **WHEN** a server that served the previous `audience_labelling` default and never saved one starts this build
- **THEN** `audience_labelling` resolves to the previous default as a saved version by `upgrade`

#### Scenario: Fresh instance
- **WHEN** a server starts on a data directory that never served the previous default
- **THEN** `audience_labelling` uses the current default
