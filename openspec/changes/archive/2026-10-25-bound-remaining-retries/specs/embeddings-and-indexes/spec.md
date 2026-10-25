## ADDED Requirements

### Requirement: Failing pending embeddings
The system SHALL halve a failing batch of pending embeddings on later passes until the failing row is alone, set that row aside so the rest embed, and try it alone again after others embedded. Only a failure then SHALL count; after `embedding_retries` (Automation limits, default 2) such failures the row SHALL be passed over and listed as stopped until its text changes or an admin retries it.

#### Scenario: One row keeps failing
- **WHEN** one pending statement fails to embed every time while others embed
- **THEN** the others are embedded, and the failing statement is listed as stopped once past its limit

#### Scenario: Provider outage
- **WHEN** the provider fails every call
- **THEN** no row is counted toward its limit
