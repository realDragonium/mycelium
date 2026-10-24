## MODIFIED Requirements

### Requirement: External agent for an action
The system SHALL let an admin set `docgen`, `documentation_planning`, `audience_labelling`, `ingest`, `connect`, `alias_discovery` or `ask` to External agent (`external_agent: true` on `PATCH /api/model-settings/{action}`), after which its model work is queued as agent tasks, or for `ask` done by the caller's own agent, instead of calling a provider; other actions MUST refuse it. `GET /api/model-settings` reports `external_agent`, `agent_review` and `agent_supported` per action.

#### Scenario: Unsupported action
- **WHEN** an admin saves `external_agent: true` for `draft_review`
- **THEN** the request is refused saying the action cannot be done by an external agent

#### Scenario: Documentation set to External agent
- **WHEN** documentation is set to External agent and a writer requests a document without a `provider`
- **THEN** the run is created with provider `agent` and `status` `waiting_for_agent`, and no model is called to write it

## REMOVED Requirements

### Requirement: Actions that keep a server model
**Reason**: Ask now takes External agent, done by the caller's own agent rather than a task.
**Migration**: See "Draft review and embeddings keep their model" and the search-and-ask requirement "Ask through the caller's own agent".

## ADDED Requirements

### Requirement: Draft review and embeddings keep their model
The system SHALL keep draft review on a server model until its reviewer has an agent task handler, and SHALL never use agents for embeddings. Ask MUST NOT be queued as an agent task.

#### Scenario: Draft review cannot be set to External agent
- **WHEN** an admin saves `external_agent: true` for `draft_review`
- **THEN** the request is refused
