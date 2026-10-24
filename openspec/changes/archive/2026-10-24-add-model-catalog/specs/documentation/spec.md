## MODIFIED Requirements

### Requirement: Run summary and trace
The system SHALL record on each run a `summary` with `activity` while running, `turns`, `duration_s`, `tokens`, `statements_retrieved`, `statements_cited`, `gaps_filed` and, for a refused review, `review_findings`; when `MYCELIUM_DOCGEN_TRACE_LOG` names a file, each run also appends one JSON line with its turns, tool calls and per-turn usage keyed by the run id.

#### Scenario: Polling a running run
- **WHEN** a caller reads a running run
- **THEN** `summary.activity` says what the run is currently doing
