## Why

The automations that connect statements left an open, empty draft behind about sixty times a day: the ingest loop opened a draft whenever the model raised a flag, even when every operation was then dropped or failed to queue. An empty draft cannot be submitted to review, so it stayed open with no author, and the Knowledge health count of pending drafts counted every one of them next to the drafts that actually waited for a curator.

## What Changes

- A server-created draft is opened together with its first operation, in one transaction. A run with nothing to queue, flags or not, answers `nothing_to_ingest` and creates no draft; its flags stay in the trace.
- Each start withdraws open drafts that have no operations and no creator (no account and no repository source). The withdrawal is recorded as made by `upgrade`. Drafts a person or agent created stay, even when empty.
- `pending_drafts` counts submitted drafts awaiting a decision; the new `open_drafts` counts drafts still open with their authors. The Knowledge health card shows the first, with the second as its sub-count, the same split the home page and the Drafts screen show. `get_knowledge_health` returns the same counts.

## Impact

- Ingest and connect runs that only raised flags no longer produce a draft.
- MCP and HTTP clients reading `pending_drafts` get a smaller number: drafts open with their authors moved to `open_drafts`.
