## ADDED Requirements

### Requirement: Index snapshots
`mycelium snapshot-indexes <dir>` SHALL copy both index files and their sidecars into `<dir>` between index writes, so it is safe while the server runs, and each copied sidecar MUST also record a fingerprint of the database the copy matches: its mapped vector ids and their texts. It MUST exit non-zero and copy nothing when an index file is missing, carries a dirty marker or has no current sidecar.

#### Scenario: Snapshot during a write
- **WHEN** `snapshot-indexes` runs while a statement write is changing the statement index
- **THEN** it waits for the write to commit and copies the index with that statement's vector

#### Scenario: Dirty index
- **WHEN** `mycelium-names.vec.dirty` exists
- **THEN** `snapshot-indexes` exits non-zero saying the index is marked dirty

## MODIFIED Requirements

### Requirement: Startup index rebuild
At startup the system SHALL load each index only when its file exists, carries no dirty marker, records the configured embedder and, if its sidecar records a database fingerprint, that fingerprint is the database's. Otherwise it MUST rebuild the index by re-embedding every statement or name, logging the reason when an index file existed, so vectors from two embedders or another database state are never mixed. An unreadable sidecar MUST count as a mismatch.

#### Scenario: Switching provider
- **WHEN** the indexes were built with Ollama and the server restarts with `MYCELIUM_EMBED_PROVIDER=openai`
- **THEN** both indexes are rebuilt with OpenAI embeddings and their sidecars record the OpenAI embedder

#### Scenario: Missing index file
- **WHEN** `mycelium-names.vec` is absent, as after restoring a backup without vectors
- **THEN** the name index is rebuilt from the names in the database

#### Scenario: Snapshot of the restored database
- **WHEN** the server starts on a restored database beside a snapshot taken of that same database state
- **THEN** both indexes load without re-embedding

#### Scenario: Snapshot older than the database
- **WHEN** a statement "Invoice exports are queued" was added, or an existing statement's text edited or deleted, after the snapshot was taken, and the server starts on the newer database beside that snapshot
- **THEN** the statement index is rebuilt by re-embedding and the log names the fingerprint mismatch
