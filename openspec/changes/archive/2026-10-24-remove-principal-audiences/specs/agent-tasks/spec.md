## MODIFIED Requirements

### Requirement: Only real writers claim agent tasks
The system MUST allow `claim_agent_task`, `read_for_agent_task`, `submit_agent_task` and `release_agent_task` only to a real writer or admin; a drafter, reader or asker is refused, and the tools are not listed to them over MCP.

#### Scenario: Drafter claims
- **WHEN** a drafter calls `claim_agent_task(kind="documentation")`
- **THEN** the call is refused with a role error and no task is leased
