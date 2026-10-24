## Why

Documentation, documentation planning and audience labelling need a provider API key on the server. Teams that already run coding agents (Claude Code, Codex) should be able to do that model work with those agents instead, without a server key, and without weakening the boundaries a server run keeps.

## What Changes

- Settings → Models gets an **External agent** choice for `docgen`, `documentation_planning` and `audience_labelling`. With it, the server queues an agent task instead of calling a model.
- New MCP tools for real writers and admins: `claim_agent_task`, `read_for_agent_task`, `submit_agent_task`, `release_agent_task`. Claims are 30-minute renewable leases that expire back to the queue.
- An agent's result passes the same checks as a server model's: audience-scoped reads, the citation and vocabulary gates, template and exposure review, plan filtering and label validity. Refusals return findings, with bounded retries.
- Documentation review is a setting: the server's reviewer (default) or another agent that is never the writer.
- Documentation runs gain the status `waiting_for_agent`; runs, plans and labelling status show their task. Waiting runs and plans survive a restart.

## Capabilities

### New Capabilities
- `agent-tasks`: the queue, its tools, roles, leases, checks, retries and where task state shows.

### Modified Capabilities
- `ai-providers`: an action set to External agent needs a model only when the server still reviews its work.
- `documentation`: the `agent` provider choice, the `waiting_for_agent` status, and restart behaviour for agent runs.

## Impact

- New table `agent_tasks` in the drafts database, archived with documentation (archive version 4).
- `docs/AGENT_TASKS.md`, `docs/AI_MODELS.md`, `docs/MCP_TOOLS.md`; new skill `skills/mycelium-agent-tasks/`.
