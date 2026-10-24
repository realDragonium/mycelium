## MODIFIED Requirements

### Requirement: Degraded reads while the provider is unavailable
While the embedding provider cannot embed a query, `search_statements` and `search_entities` SHALL fall back to keyword or name-substring matching marked `retrieval: "keyword"`, so Ask and documentation runs keep working with weaker retrieval, whereas `discover_facts` MUST report the error. `find_duplicates` compares only stored vectors and SHALL keep working. Fallback ranking is specified in the `search-and-ask` capability.

#### Scenario: Ask during an outage
- **WHEN** the provider is down and a reader calls `ask`
- **THEN** the run retrieves through keyword fallback and returns an answer rather than an error

#### Scenario: Duplicate audit during an outage
- **WHEN** the provider is down and a curator calls `find_duplicates`
- **THEN** it returns the near-duplicate pairs among statements that already have vectors
