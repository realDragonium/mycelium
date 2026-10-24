## MODIFIED Requirements

### Requirement: Ask trace contents
An Ask trace record SHALL have `version: 2` and hold the question, model, provider, prompts, `outcome`, `op_count`, `op_cap`, `latency_ms`, `model_turns`, `phase_ms`, `model_turn_ms`, `tool_calls`, `floor`, `evidence_checks`, `combined_reads`, `evidence_refs`, `supplied_context_chars`, `tokens`, `forced_finalize`, `degraded`, `notes` and `stream_timing_ms`.

#### Scenario: Cancelled run timing
- **WHEN** a run is cancelled after answer text streamed
- **THEN** its trace has outcome `cancelled`, a `stream_timing_ms.first_answer_text_ms` and no `completion_ms`
