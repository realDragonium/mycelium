## MODIFIED Requirements

### Requirement: Connect pass budget and model
The system SHALL run the connect pass on the model selected for the `connect` action, refusing the run while that action has no model chosen, with its instructions from the saved `connect` prompt followed by a fixed contract, meter its calls as `connect`, append its trace to `connect_trace.jsonl` in the data directory, and refuse the run while the monthly AI budget pauses background actions.

#### Scenario: Budget pauses background actions
- **WHEN** the monthly budget is spent with background pausing on and a caller requests a connect run
- **THEN** the call is refused with the pause reason and no draft is created
