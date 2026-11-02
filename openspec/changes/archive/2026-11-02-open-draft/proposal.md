## Why

A writer or admin agent could not open a draft over MCP. Passing `draft_id` to a write needed an existing open draft, no tool opened one, and the only way to propose was a second, drafter-scoped token. The web app's **Propose as draft** gives a writer a draft with no second token.

## What Changes

- An `open_draft(title?)` tool for drafters, writers and admins, with its HTTP route, returning the caller's open draft id, status, title, operation count and whether it was just created.
- A caller keeps one open draft: while one is open, `open_draft` returns it, the same draft the web app's Propose as draft fills and a drafter's writes go onto.
- The MCP way for a writer or admin to propose is now `open_draft`, writes with `draft_id`, then `submit_draft`. A drafter-scoped token stays documented as the alternative.

## Impact

- A writer or admin write without `draft_id` still lands live; the skills tell agents to pass it on every write.
