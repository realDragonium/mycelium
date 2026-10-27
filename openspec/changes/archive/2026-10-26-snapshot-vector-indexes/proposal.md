## Why

A host with ephemeral storage restores its databases on every start and
caches the vector indexes beside them, so a start does not have to re-embed
everything. Copying the index files out of a live data dir had two faults:

- The copy could miss the `.meta.json` sidecars. Since index format 2, an index
  without one is rebuilt, so every start re-embedded every statement and name.
- The copy could be older than the restored database, or torn by a write in
  progress. Statements written after it had a vector id but no vector, and
  deleted ones kept theirs, so semantic search quietly disagreed with the
  knowledge base.

## What Changes

- `mycelium snapshot-indexes <dir>` copies both indexes and their sidecars
  while no index write is in flight, and records in each copied sidecar a
  fingerprint of the database it matches. It is safe while the server runs and
  refuses to copy an index that is missing or marked dirty.
- At startup, an index whose sidecar records a fingerprint loads only when the
  database still has it. Otherwise it goes through the existing rebuild, with a
  log line naming the reason. A matching copy loads without re-embedding.
- Nothing runs at a start to repair a mismatch in place: the check decides
  between loading the cache and the existing full rebuild.

## Impact

- `embeddings-and-indexes`: a new requirement for index snapshots; the startup
  rebuild also rebuilds a snapshot of another database state.
- Hosts that cache indexes should copy them with `snapshot-indexes`, including
  once after the server exits. Index files copied any other way carry no
  fingerprint and are trusted as before.
