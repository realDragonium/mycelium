## MODIFIED Requirements

### Requirement: Model choice for a run
The system SHALL take `provider` `claude`, `openai` or `agent` per request, defaulting to the saved documentation model settings (default `claude`, or `agent` while documentation is set to External agent), record the provider, model and reasoning effort on the run, and refuse the request when no model is configured for a provider the run needs or that provider is unavailable; a run never switches provider on failure. A run with provider `agent` is written by an outside agent (see agent-tasks) and needs a model only when the server reviews it; a manual edit always uses a server provider. `list_documentation_models` reports the default provider and each provider's model, availability and reason, and lists `agent` while documentation is set to External agent.

#### Scenario: GPT selected without a model
- **WHEN** a writer requests `provider="openai"` and no OpenAI documentation model is configured
- **THEN** the request is refused asking to choose an OpenAI documentation model

#### Scenario: Explicit server provider while External agent is selected
- **WHEN** documentation is set to External agent and a writer requests `provider="claude"`
- **THEN** the run is written on the server with the Claude documentation model

### Requirement: Run status derivation
The system SHALL report each run's `status` as `queued` before it starts, `waiting_for_agent` while an outside agent's task serves it, `running` until it finishes, then `document_written`, `nothing_written` or `failed` from its outcome, except that a run whose written document has since been rewritten by another run reports `document_superseded` while its stored `outcome` stays `document_written` and `document_superseded` is true. A `waiting_for_agent` run has no `queue_position` and does not count against the active-run limit.

#### Scenario: A later run revises the document
- **WHEN** run A wrote document D and run B later writes a new revision of D
- **THEN** `get_documentation_run(A)` reports `status` `document_superseded` and `outcome` `document_written`

#### Scenario: Agent run before it is written
- **WHEN** a run is requested with provider `agent`
- **THEN** it reports `status` `waiting_for_agent` until the agent's document is saved or refused

### Requirement: Restart fails unfinished runs
The system SHALL mark every unfinished documentation run, queued or running, as `failed` with error `orphaned by restart` when the server starts, except a run waiting for an outside agent, which keeps waiting.

#### Scenario: Server restarts mid-run
- **WHEN** the server restarts while a run is running and another is queued
- **THEN** both runs report `status` `failed` with error `orphaned by restart`

#### Scenario: Server restarts while an agent run waits
- **WHEN** the server restarts while a run is `waiting_for_agent`
- **THEN** the run still reports `waiting_for_agent`
