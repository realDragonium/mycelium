## ADDED Requirements

### Requirement: Ingest model from AI settings
The system SHALL run ingest with the model selected for the `ingest` action and its reasoning effort, as configured in the `ai-providers` capability, refuse the run without calling a model while none is chosen, and attribute its model calls to `ingest`.

#### Scenario: No model chosen
- **WHEN** no ingest model has been saved
- **THEN** ingest is refused with "Choose a Claude model for ingestion in AI settings." and no model is called

## MODIFIED Requirements

### Requirement: Run limits
The system SHALL bound each run by the saved ingest limits: an operation cap (default 50, counting the vocabulary fetch and every read), a wall clock (default 300 seconds, with reading stopped after two thirds so the final emit has the last third), max tokens per turn (default 32000), a per-call timeout (default 90 seconds), provider retries (default 4) and adaptive thinking (default on). Ingest has no token cap.

#### Scenario: Default operation cap reached
- **WHEN** a run has made 50 counted operations
- **THEN** the model gets no further read turns and is forced to emit

### Requirement: Ingest trace
The system SHALL return a `trace` with the model, provider, outcome, input length, operation count and cap, latency, model turns, every tool call, the candidate ledger, proposed operations, flags, skipped duplicates, gaps, floor state, token totals, `forced_finalize`, `degraded`, notes and the prompt version used, and append it as one JSON line to `ingest_trace.jsonl` in the data directory unless `MYCELIUM_INGEST_TRACE_LOG` names another file.

#### Scenario: Trace written
- **WHEN** an ingest run finishes
- **THEN** a JSON line with its trace is appended to the ingest trace log

## REMOVED Requirements

### Requirement: Ingest model selection
**Reason**: Its default model no longer exists; replaced by "Ingest model from AI settings".
**Migration**: The upgrade saves the former default for an instance that relied on it.
