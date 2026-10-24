## MODIFIED Requirements

### Requirement: External agent for an action
The system SHALL let an admin set `docgen`, `documentation_planning`, `audience_labelling`, `ingest`, `connect` or `alias_discovery` to External agent (`external_agent: true` on `PATCH /api/model-settings/{action}`), after which its model work is queued as agent tasks instead of calling a provider; other actions MUST refuse it. `GET /api/model-settings` reports `external_agent`, `agent_review` and `agent_supported` per action.

#### Scenario: Unsupported action
- **WHEN** an admin saves `external_agent: true` for `ask`
- **THEN** the request is refused saying the action cannot be done by an external agent

#### Scenario: Documentation set to External agent
- **WHEN** documentation is set to External agent and a writer requests a document without a `provider`
- **THEN** the run is created with provider `agent` and `status` `waiting_for_agent`, and no model is called to write it

### Requirement: Task kinds
The system SHALL queue tasks of kind `documentation`, `document_review`, `documentation_planning`, `audience_labelling`, `ingest`, `connect` and `alias_discovery`. Labelling batches are made when an agent claims, from the statements due then, at the labelling batch size, and a statement in an open batch is not put in another.

#### Scenario: Labelling batch at claim time
- **WHEN** audience labelling is set to External agent and an agent claims `audience_labelling` work
- **THEN** a batch of due statements no open task holds is queued and leased to that agent

### Requirement: Task briefs
The system SHALL give each claimed task a `brief` with `instructions` and `input` built by the same code that briefs the server's own model, the `result` description and `result_schema` a submission must match, `read_tools` for documentation, ingest and connect, and for documentation the `guideline_set`, `document_type` and `audience`. The brief MUST NOT contain knowledge the task's audience may not see.

#### Scenario: External profile brief
- **WHEN** a writer claims a documentation task for a profile writing for `external-technical`
- **THEN** the brief names that audience and contains no statement only internal audiences may see

### Requirement: Agent reads stay inside the audience
The system SHALL run `read_for_agent_task(task_id, tool, arguments)` for documentation, ingest and connect tasks, with one of the brief's read tools. A documentation task's reads run inside the audience boundary of its profile, captured again on every read; a statement the audience may not see is not returned.

#### Scenario: Reading an internal statement for an external document
- **WHEN** the agent calls `read_for_agent_task` with `get_statements` for an external statement and an internal-only one
- **THEN** only the external statement is returned and the other is reported missing

## ADDED Requirements

### Requirement: Queued ingest, connect and alias scans
While its action is set to External agent, the system SHALL answer `ingest`, `connect_statements` and an alias scan at once without calling a model: `ingest` and `connect_statements` return `outcome` `waiting_for_agent` with `agent_task`, and the scan returns no suggestions with `agent_task`.

#### Scenario: Ingest queued
- **WHEN** ingest is set to External agent and a writer calls `ingest` with text
- **THEN** the response has `outcome` `waiting_for_agent` and an `agent_task` an agent can claim as kind `ingest`

### Requirement: Agent drafts pass the ingest emit gate
The system MUST check an `ingest` or `connect` submission with the loop's emit gate: the reading floor counted from this claimant's `read_for_agent_task` reads, the ledger and coverage checks, then the same screening, validation and draft assembly. A floor or ledger refusal returns a `floor` finding; after 3, the submission is kept as a degraded draft.

#### Scenario: Submitting before reading
- **WHEN** an agent submits an ingest draft without having made a reconcile read and a later search
- **THEN** the submission is refused with a `floor` finding and no draft is created

### Requirement: Agent connect runs are recorded
The system SHALL record a finished `connect` task as a server connect run is recorded: what it looked at, rephrase gaps and submission of its draft. A statement an open `connect` task holds MUST NOT be offered by "connect next".

#### Scenario: Waiting connect batch
- **WHEN** a connect task for a statement is waiting for an agent
- **THEN** the knowledge-health "connect next" list does not offer that statement

### Requirement: Agent aliases quote the selection
The system MUST refuse an `alias_discovery` submission whose evidence names a statement outside the scan's selection, with an `evidence` finding, and SHALL keep accepted suggestions as the model's are, in a submitted draft by whoever started the scan. A change of names since the scan fails the task.

#### Scenario: Evidence from another statement
- **WHEN** an agent proposes an alias quoting a statement the scan did not select
- **THEN** the submission is refused with an `evidence` finding and no draft is created

### Requirement: Following queued work
The system SHALL let whoever queued a task, or an admin, call `get_agent_task(task_id)` for its status, findings, failures and, once done, its `result` (such as the draft it made); any other caller is told the task does not exist.

#### Scenario: Requester follows an ingest
- **WHEN** the writer who called `ingest` asks for its task after an agent's draft was accepted
- **THEN** the task is `done` and its `result` names the created draft

### Requirement: Actions that keep a server model
The system SHALL keep Ask and draft review on a server model: Ask is interactive, and a caller with its own agent already has the read tools, so a queued answer would only add waiting. Embeddings never use agents.

#### Scenario: Ask cannot be set to External agent
- **WHEN** an admin saves `external_agent: true` for `ask`
- **THEN** the request is refused
