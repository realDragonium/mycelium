## Why

Only documentation, planning and labelling could be done by an outside agent. Ingest, the connect pass and alias discovery still needed a provider key on the server. Each action also had its own branch in the task tools, so adding one meant editing every tool.

## What Changes

- Ingest, Connect and Alias discovery can be set to External agent. `ingest`, `connect_statements` and an alias scan then queue a task and return `waiting_for_agent` with its id.
- An agent's ingest or connect draft goes through the loop's own emit gate: the reading floor counted from `read_for_agent_task`, the ledger and coverage checks, screening, validation and draft assembly. An agent's aliases must quote a selected statement.
- New tool `get_agent_task` for whoever queued work, or an admin: status, findings and the draft it made. Tasks record who requested them and their result.
- One handler per kind (`agent_tasks.Handler`), in one table; the tools have no per-kind branches.
- Ask and draft review keep a server model. Ask is interactive and a caller's own agent already has the read tools. Draft review gets a handler once its reworked reviewer lands.

## Capabilities

### Modified Capabilities
- `agent-tasks`: the new kinds and their checks, reads for ingest and connect, `get_agent_task`, and which actions do not support External agent.

## Impact

- `agent_tasks` gains `requested_by` and `result` (unreleased table; fixture recaptured).
- Knowledge health does not offer statements an open connect task holds.
- UI: ingest, connect and alias scan show a queued state.
