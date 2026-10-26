## ADDED Requirements

### Requirement: Vector ids keep one slot
Writing a vector under an id the index already holds, live or marked deleted, SHALL overwrite that id's own slot. Only an id the index does not hold MAY take a deleted slot, so no id is left on two slots and no other id loses its slot.

#### Scenario: Freed ids reused
- **WHEN** vector ids 0 and 1 are deleted and then written again with new vectors
- **THEN** a search for each new vector returns its own id first, and no slot keeps an old vector

### Requirement: Loaded indexes are reconciled with their mappings
When an index loads at startup, the system SHALL compare its live vector ids with the database's mappings for that index and log both counts. A mapping with no live vector SHALL be removed, so its row is pending again for the background worker. A live vector with no mapping SHALL be deleted and the index persisted. Reconciliation MUST NOT call the embedding provider or rebuild the whole index.

#### Scenario: Mapped vectors missing from the index
- **WHEN** a statement and a name have vector id mappings but the indexes hold no live vector under them, and the provider is down
- **THEN** startup succeeds, logs the counts, and lists the statement and the name as pending embeddings
- **AND** they stay pending across a failed pass and a restart, and the next successful pass restores them to search

#### Scenario: Names merged by a migration
- **WHEN** a migration removed name rows but left their vectors in `mycelium-names.vec`
- **THEN** startup deletes those vectors and persists the index

#### Scenario: Vector without a mapping
- **WHEN** `mycelium.vec` holds a vector under an id that no statement maps
- **THEN** startup deletes that vector, persists the index and leaves no dirty marker

### Requirement: Unreachable index slots are compacted
When an index loads at startup with slots that its label lookup no longer reaches, the system SHALL rebuild the index graph from the vectors of its live ids, without re-embedding, before reconciling it with the mappings.

#### Scenario: Index written before vector ids kept one slot
- **WHEN** `mycelium.vec` has a slot that serves an old vector under an id now held by another slot
- **THEN** startup compacts the index and a search no longer returns the old vector

## REMOVED Requirements

### Requirement: Stranded name vectors are pruned
**Reason**: Superseded by "Loaded indexes are reconciled with their mappings", which prunes stranded vectors in both indexes and also handles mappings without a vector.
**Migration**: None. Stranded name vectors are still pruned at startup.
