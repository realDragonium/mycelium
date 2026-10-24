## Why

Ask was the one interactive action left needing a provider key. Queuing a question for some other agent would only make the caller wait, but a caller with an agent of its own can research the question itself with the read tools, inside its own audience boundary.

## What Changes

- Ask can be set to External agent. Nothing is queued: the server's `ask` tool runs no model, is left out of `tools/list`, and refuses a call over MCP or `POST /ask` with a message naming the `mycelium-research` skill.
- New skill `mycelium-research`: the Ask loop's recon, targeted reads, adjacency search and answering rules, written for the caller's agent.
- The web app hides Ask (the command bar's Ask mode and every Ask entry point); Find stays. Settings → Models explains the setting for Ask.

## Capabilities

### Modified Capabilities
- `agent-tasks`: Ask joins the actions that take External agent; draft review and embeddings still do not.
- `search-and-ask`: what `ask` does while Ask is set to External agent.

## Impact

- An `asker` connection has no tools while Ask is external.
- No schema change.
