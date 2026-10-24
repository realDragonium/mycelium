## MODIFIED Requirements

### Requirement: Ingest role gate
The system MUST require the writer role for `ingest`; a drafter also satisfies the gate, and a reader is refused.

#### Scenario: Reader calls ingest
- **WHEN** a principal with the reader role calls `ingest`
- **THEN** the call is refused with a role error and no draft is created

#### Scenario: Drafter calls ingest
- **WHEN** a principal with the drafter role calls `ingest`
- **THEN** the loop runs and its outcome is returned
