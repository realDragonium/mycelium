## MODIFIED Requirements

### Requirement: Restore never imports the environment
The system MUST NOT import legacy environment configuration into a restored instance; settings come from the archive, and an archive without them restores with no models chosen and draft review off.

#### Scenario: Restore on a host with legacy variables
- **WHEN** an archive is imported on a host where `MYCELIUM_INGEST_MODEL` is set and the restored instance is started
- **THEN** the `ingest` model comes from the archive, or is not chosen, never from the variable
