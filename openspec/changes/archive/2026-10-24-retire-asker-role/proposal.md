## Why
Every account with access must be able to read all statements. The `asker` role, which could call only `ask`, is the one role that could not, and it cost a separate route gate in front of the web app.

## What Changes
- **BREAKING** The `asker` role is removed; `reader` is the minimum role. The asker route gate (every `/api/*` route but `/api/me` refused) is removed, and `ask` requires reader.
- The auth store turns askers into readers on users, tokens (OAuth grants included) and invites at startup, logging how many rows changed.
- An older backup naming `asker`, and `MYCELIUM_JIT_DEFAULT_ROLE=asker`, are read as `reader` with a deprecation warning.

## Impact
- Code: `auth`, `auth_store`, the authentication middleware, the tool routes, `backup` and the web app's start-up check.
- Specs: `access-control`, `agent-tasks`, `search-and-ask`, `embeddings-and-indexes`.
