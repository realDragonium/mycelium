## Why

A statement's vector id could stay mapped in the database while the index
held no vector under it. The statement then dropped out of semantic search,
and editing its text failed until v0.7.1. The cause was `Index.add`, written
in the initial commit. It always let hnswlib fill a deleted slot, and hnswlib
fills an arbitrary deleted slot without checking whether the label is already
in the index. It then erases the label that slot carried from its lookup.

Two writes passed it a label the index already held:
- every text edit, because `replace` deleted and re-added the same id;
- every reuse of a freed id, because `next_vector_id` hands out MAX + 1 again
  once the highest ids are deleted, merged or dropped by an edit during a
  provider outage.

Either one could leave the id on a stale slot, or on no slot at all.

## What Changes

- Writing a vector under an id the index already holds, live or deleted,
  overwrites that id's own slot. Only a new id can fill a deleted slot.
- The index sidecar records an index format, now 2, beside the embedder. An
  index without a sidecar, or with an earlier format, fails the existing
  identity check and is rebuilt once at startup. This repairs indexes written
  by the old code on the next deploy, with no check that runs on every start.

## Impact

- `embeddings-and-indexes`: index identity includes the format, and
  vector-id reuse gets a requirement.
- Every existing instance re-embeds its statements and names once on the
  first start of this build, so the start needs the embedding provider.
