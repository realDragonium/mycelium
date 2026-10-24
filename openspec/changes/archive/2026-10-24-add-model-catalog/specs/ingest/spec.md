## ADDED Requirements

### Requirement: Ingest model from AI settings
The system SHALL run ingest with the model selected for the `ingest` action and its reasoning effort, as configured in the `ai-providers` capability, refuse the run without calling a model while none is chosen, and attribute its model calls to `ingest`.

#### Scenario: No model chosen
- **WHEN** no ingest model has been saved
- **THEN** ingest is refused with "Choose a Claude model for ingestion in AI settings." and no model is called

## REMOVED Requirements

### Requirement: Ingest model selection
**Reason**: Its default model no longer exists; replaced by "Ingest model from AI settings".
**Migration**: The upgrade saves the former default for an instance that relied on it.
