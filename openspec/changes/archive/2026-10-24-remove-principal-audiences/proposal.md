## Why
Audiences were doing two jobs: bounding what a writing profile's documents and plans draw on, and scoping what a user, token or OAuth grant may read. The second job cost a tool and route allowlist, scoped Ask, history and document filtering, and a parallel scoped web app, for a use nobody relies on. Audiences are now a documentation concept only; who may read what is decided by role alone.

## What Changes
- **BREAKING** Users, personal tokens and OAuth grants no longer carry an audience. The `audience_id` fields leave `/api/me`, the token list, `PATCH /api/admin/users/{user_id}`, `POST /api/me/tokens` and the consent screen; `PATCH /api/admin/tokens/{token_id}` is removed.
- The scoped tool and route allowlists, scoped Ask, scoped history, scoped generated-document filtering and the scoped media 404 are removed. Every principal reads what its role allows.
- The auth store drops `audience_id` from users, MCP tokens and OAuth codes at startup, logging each principal that was scoped. Backups made before the change restore with the column dropped.
- Audience labels, inclusion, external-grant confirmation, the documentation-run boundary, planning and maintenance are unchanged.

## Impact
- Code: `auth`, `auth_store`, `oauth_server`, `http` account, admin, substrate, history and media routes, the tool registry, Ask, documentation reads, media, backup and the web app.
- Specs: `audiences`, `access-control`, `agent-tasks`, `media`, `embeddings-and-indexes`, `knowledge-model`, `knowledge-health`, `ingest`, `search-and-ask`, `documentation`.
