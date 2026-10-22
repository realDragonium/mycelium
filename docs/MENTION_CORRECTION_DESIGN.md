# Adding mentions from statement detail

Historical design note. The per-occurrence review queue is retired; see
[alias-based discovery](MENTIONS.md). Vocabulary editing belongs in Names & aliases.

Milestone 02. The need: while reviewing, be able to **add new names/aliases for
entities, or new entities**, so statements get proper mentions — because the
matcher is only as good as its vocabulary.

## The approach: grow the vocabulary, let the matcher derive

Mentions are derived from entity names/aliases. So "add a mention" is not a new
kind of record — it's a vocabulary edit:

- **Add an alias to an existing entity** → `upsert_name(text, entity_id)`.
- **Create a new entity** → `upsert_entity(name, description)`.

Both already exist as tools / HTTP endpoints, and both enqueue a **recompute
scan** server-side (`_create_name_with_plural` → `enqueue_recompute_scan`). The
background worker then re-scans existing statements whose text contains the new
word and materializes the `statement_mentions`. No new table, no assertion model,
no API change — the matcher stays the single source of mentions.

> An earlier draft of this note proposed an `asserted_mentions` ledger. Rejected:
> the real need is vocabulary editing, which the existing endpoints already serve.

## What was built

- **Client** (`frontend/ui/api.ts`): `upsertEntity` / `upsertName`.
- **UI** (`frontend/ui/inspect.tsx`, `AddMention`): an "+ add mention" control
  in the statement view's mentions section. Two modes — attach an alias to an
  entity found by search, or create a new entity (name + description). On success
  it explains the matcher will link it on the next scan and offers a reload.

## Known limitation

The recompute is asynchronous (worker drain), and the app holds a snapshot of
`/api/data`. So a newly-derived mention appears after **Reload data** re-pulls
the snapshot once the worker has drained, not instantly — surfaced honestly in
the success banner.
