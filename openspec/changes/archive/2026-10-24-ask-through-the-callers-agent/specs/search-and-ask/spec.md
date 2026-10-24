## ADDED Requirements

### Requirement: Ask through the caller's own agent
While Ask is set to External agent, the system SHALL run no model for `ask`: it MUST leave `ask` out of every caller's `tools/list` and refuse a call over MCP or `POST /ask` with a message telling the caller to research with the read tools as the `mycelium-research` skill describes. The web app SHALL hide Ask and keep Find.

#### Scenario: Ask called while external
- **WHEN** Ask is set to External agent and a reader posts a question to `/ask`
- **THEN** the request is refused naming the `mycelium-research` skill and no model is called

#### Scenario: Tool list while external
- **WHEN** Ask is set to External agent and a reader lists tools over MCP
- **THEN** `ask` is not listed and the read tools are
