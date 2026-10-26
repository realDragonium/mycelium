## ADDED Requirements

### Requirement: Vector ids keep one slot
Writing a vector under an id the index already holds, live or marked deleted, SHALL overwrite that id's own slot. Only an id the index does not hold MAY take a deleted slot, so no id is left without a vector or on a stale one.

#### Scenario: Freed ids reused
- **WHEN** vector ids 0 and 1 are deleted and then written again with new vectors
- **THEN** each id holds its new vector and a search for it returns that id first

## MODIFIED Requirements

### Requirement: Index embedder identity
Each index file SHALL record the embedder that built it and the index format as `{"embedder": "<provider>/<model>/768", "format": 2}` in a sidecar named `<index file>.meta.json`. An index with no sidecar, or with a sidecar recording another format, MUST count as a mismatch and be rebuilt.

#### Scenario: Index written before format 2
- **WHEN** the server starts with `mycelium.vec` whose sidecar records the configured embedder but no format
- **THEN** the statement index is rebuilt by re-embedding, its sidecar records format 2, and the next start loads it without re-embedding

#### Scenario: Index predating sidecars
- **WHEN** the server starts with `mycelium.vec` but no `mycelium.vec.meta.json`
- **THEN** the statement index is rebuilt by re-embedding and its sidecar is written with format 2
