## ADDED Requirements

### Requirement: Connect pass model
The system SHALL run the connect pass on the model selected for the `connect` action, refusing the run while that action has no model chosen, with its instructions from the saved `connect` prompt followed by a fixed contract, meter its calls as `connect`, and append its trace to `connect_trace.jsonl` in the data directory.

#### Scenario: No model chosen
- **WHEN** a caller requests a connect run while the `connect` action has no model saved
- **THEN** the call is refused naming the missing model and no draft is created

## REMOVED Requirements

### Requirement: Connect pass budget and model
**Reason**: Mycelium sets no AI budget, so nothing pauses the connect pass; the rest moves to "Connect pass model", and `max_run_tokens` still caps each run.
**Migration**: None.
