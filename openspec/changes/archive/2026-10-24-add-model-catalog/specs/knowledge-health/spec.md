## MODIFIED Requirements

### Requirement: Connect pass availability
The system SHALL include in the health response `connect` with `batch_size`, `max_run_tokens`, `provider` and `model`, or `connect: null` with `connect_error` explaining why the connect pass is unavailable, such as missing credentials or an unavailable model setting.

#### Scenario: No credentials for the connect model
- **WHEN** the connect action's provider has no credentials configured
- **THEN** `connect` is null and `connect_error` gives the reason

### Requirement: Connect pass result
The system SHALL answer a connect call with the same `draft_created` or `nothing_to_ingest` shape as `ingest` (see the `ingest` capability), plus `tokens` (every token the run's model calls used) and `gaps_filed`; a created draft is submitted to the internal reviewer while review is on and otherwise stays open.

#### Scenario: Connect while review is on
- **WHEN** a connect run queues links and draft review is on
- **THEN** the response has `submitted_for_review: true`

### Requirement: Connect pass limits
The system SHALL bound each connect run by the saved connect limits: batch size (default 5), token cap (`max_run_tokens`, default 2,000,000, 0 for none), operation cap (default 60), wall clock (default 300 seconds), max tokens per turn (default 32000) and per-call timeout (default 120 seconds); before each model turn it stops reading and emits when the tokens used so far plus a reserve for one more turn and the final emit reach the cap.

#### Scenario: Token cap near
- **WHEN** the tokens used so far plus the reserve reach the token cap
- **THEN** the run stops reading and forces its final emit

### Requirement: Connect pass budget and model
The system SHALL run the connect pass on the model selected for the `connect` action, refusing the run while that action has no model chosen, with its instructions from the saved `connect` prompt followed by a fixed contract, meter its calls as `connect`, append its trace to `connect_trace.jsonl` in the data directory, and refuse the run while the monthly AI budget pauses background actions.

#### Scenario: Budget pauses background actions
- **WHEN** the monthly budget is spent with background pausing on and a caller requests a connect run
- **THEN** the call is refused with the pause reason and no draft is created
