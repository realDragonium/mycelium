## Why

A statement's vector id could stay mapped in the database while the index no
longer held a vector under it, which kept the statement out of semantic search
and made an edit of its text fail until v0.7.1. Nothing at startup compared the
database's vector id mappings with the index, so the drift lasted until each
statement was edited. The cause was `Index.add`: it always let hnswlib fill a
deleted slot, and hnswlib fills an arbitrary deleted slot without checking
whether the label is already in the index. Re-adding a vector id the index
already held, as every text edit and every reuse of a freed id did, left the
id's old slot behind with a stale vector and could erase another id from the
index's label lookup.

## What Changes

- Re-adding a vector id overwrites the slot that id already has, live or
  deleted. Only a new id can fill a deleted slot.
- On startup, a loaded index is reconciled with its database mappings:
  - slots the label lookup no longer reaches are compacted away;
  - a mapped id with no vector loses its mapping, so the embedding worker
    re-embeds the row as pending, in batches and within the embedding retry
    limit. Startup calls no provider;
  - a vector with no mapping is pruned. This generalises the existing pruning
    of stranded name vectors to both indexes.
  - Both counts are logged.

## Impact

- `embeddings-and-indexes`: stranded-name pruning becomes reconciliation of
  both indexes, and vector-id reuse gets a requirement.
- No schema change. A corrupted index heals on the next start without a full
  rebuild.
