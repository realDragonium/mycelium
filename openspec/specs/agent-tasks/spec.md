# agent-tasks Specification

## Purpose
Let outside agents do the model work of an action set to External agent instead of a server model: documentation, documentation planning, audience labelling, ingest, the connect pass and alias discovery as queued tasks for a writer's agent, inside the same boundaries and checks a server run keeps, and Ask as the caller's own agent's research.

## Requirements

### Requirement: Task kinds
The system SHALL queue tasks of kind `documentation`, `document_review`, `documentation_planning`, `plan_review`, `audience_labelling`, `ingest`, `connect`, `alias_discovery` and `draft_review`. Labelling batches are made when an agent claims, from the statements due then, at the labelling batch size, and a statement in an open batch is not put in another. Plan reviews are queued for profiles whose plan review is `ai` while proposed items wait undecided.

#### Scenario: Labelling batch at claim time
- **WHEN** audience labelling is set to External agent and an agent claims `audience_labelling` work
- **THEN** a batch of due statements no open task holds is queued and leased to that agent

### Requirement: Only real writers claim agent tasks
The system MUST allow `claim_agent_task`, `read_for_agent_task`, `submit_agent_task` and `release_agent_task` only to a real writer or admin; a drafter or reader is refused, and the tools are not listed to them over MCP.

#### Scenario: Drafter claims
- **WHEN** a drafter calls `claim_agent_task(kind="documentation")`
- **THEN** the call is refused with a role error and no task is leased

### Requirement: Leases
The system SHALL lease up to `limit` (0 to 5, default 1) waiting tasks of a kind to the caller for 30 minutes, oldest first, and extend the caller's lease on every task of that kind it already holds on each call; `limit=0` only renews. A task whose lease runs out returns to the queue; `release_agent_task(task_id, reason)` returns one at once. Only the holder of an unexpired lease may read for, submit or release a task.

#### Scenario: Lease expires
- **WHEN** an agent claims a task and makes no call for 30 minutes
- **THEN** the next claim by any writer may receive that task

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

### Requirement: Agent documents pass the emit gate
The system MUST refuse a submitted document that is malformed, cites no statements, cites a statement the task's audience may not see, cites a statement neither the brief's opening reads nor this claimant's reads returned, uses internal vocabulary or places media it was not offered. A refusal returns `status` `refused` with `findings` and `retries_left`; after 1 malformed or 3 grounding refusals more, the run is recorded as nothing written.

#### Scenario: Citing an invisible statement
- **WHEN** an agent submits a document whose `statement_ids` include a statement the profile's audience may not see
- **THEN** the submission is refused with a grounding finding naming that statement and nothing is saved

### Requirement: Agent document review
The system SHALL review a grounded agent document against the template and the audience's exposure rules before saving it: by the server's reviewer on the documentation provider when `agent_review` is `server` (the default), or by a `document_review` task when it is `agent`. `agent_review: agent` is accepted only for documentation.

#### Scenario: Server review passes
- **WHEN** review is `server` and the reviewer passes an agent's grounded document
- **THEN** the submission returns `accepted` and the run reports `document_written`

### Requirement: Reviewer independence
The system MUST never offer a `document_review` task to the principal that submitted the document it reviews, a `draft_review` task to the principal that created the draft, nor a `plan_review` task to the agent that made the plan it reviews. A claim that withheld such tasks SHALL say so in its `note`, and a submission by the draft's creator SHALL be refused naming the reason and the task returned to the queue.

#### Scenario: Another agent reviews
- **WHEN** documentation review is set to `agent` and writer A's document passes the emit gate
- **THEN** A's submission returns `in_review`, A is not offered the review, and writer B's passing review saves the document

#### Scenario: A drafter claims its own draft's review
- **WHEN** the only waiting `draft_review` task is for a draft writer A created and A claims `draft_review`
- **THEN** A gets no task and a `note` saying the waiting task is its own draft

#### Scenario: The planner claims its plan's review
- **WHEN** agent A made a plan and the only waiting `plan_review` task reviews it
- **THEN** A gets no task and a `note` saying the waiting task is a plan it made, and agent B is given it

### Requirement: Failed reviews return to the writer once
The system SHALL return the writing task to the queue with a failed review's findings once; a second failed review records the run as nothing written with the refused draft.

#### Scenario: First review fails
- **WHEN** the review of an agent's document fails conformance
- **THEN** the writing task is waiting again and its next claim carries the review's findings

### Requirement: Agent plans are filtered as a model's are
The system SHALL keep an agent's documentation plan as it keeps a model's: items citing statements the profile's audience may not see, using templates the profile lacks or naming documents it does not own are dropped, with the overview read again at submission. A malformed proposal is refused with findings, up to 2 times before the plan fails.

#### Scenario: Valid agent plan
- **WHEN** documentation planning is set to External agent and an agent submits a well-formed proposal
- **THEN** the plan's outcome is `planned` and its kept items are shown for review

### Requirement: Agent labels are validated
The system MUST refuse an agent's labelling result that labels a statement outside the batch, labels one twice, leaves one unlabelled, names an audience id that is not live or gives an empty reason; after 2 refusals more, the batch's statements are recorded as a labelling failure.

#### Scenario: Unknown audience
- **WHEN** an agent labels a statement with an audience id that does not exist
- **THEN** the submission is refused with a labels finding and no label is stored

### Requirement: Agent labels are stored as the labeller's
The system SHALL store accepted agent labels as the server labeller's are stored, including holding new external grants for confirmation when that setting is on, and MUST NOT label a statement whose text changed since it was batched.

#### Scenario: Valid labels
- **WHEN** an agent labels every statement of its batch with live audiences and reasons
- **THEN** the submission returns `accepted` and the labels are stored

### Requirement: Task state is visible
The system SHALL show an open or finished task beside what it serves: documentation runs and plan summaries carry `agent_task` (status `waiting`, `claimed`, `in_review`, `done` or `failed`, holder, lease end, failures, last findings and release reason), and `GET /api/audiences/labelling` reports `external_agent` and the open labelling tasks.

#### Scenario: Claimed run
- **WHEN** a writer has claimed the task of a waiting run
- **THEN** `get_documentation_run` returns `agent_task` with status `claimed` and that writer as holder

### Requirement: Agent tasks persist
The system SHALL store agent tasks in the drafts database, include them in documentation archives, and keep a run or plan waiting for an agent unfailed across a restart.

#### Scenario: Restart while waiting
- **WHEN** the server restarts while a documentation run is `waiting_for_agent`
- **THEN** the run is still `waiting_for_agent` and its task can be claimed

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

### Requirement: External agent for every model action
The system SHALL let an admin set any model action to External agent (`external_agent: true` on `PATCH /api/model-settings/{action}`, or on `PATCH /api/draft-review/settings` for draft review), after which its model work is queued as agent tasks, or for `ask` done by the caller's own agent, instead of calling a provider. `GET /api/model-settings` reports `external_agent`, `agent_review` and `agent_supported` per action.

#### Scenario: Documentation set to External agent
- **WHEN** documentation is set to External agent and a writer requests a document without a `provider`
- **THEN** the run is created with provider `agent` and `status` `waiting_for_agent`, and no model is called to write it

#### Scenario: Draft review set to External agent
- **WHEN** draft review is set to External agent and a draft is submitted
- **THEN** its review run has provider `agent`, stays `running`, and a `draft_review` task waits; no model is called

### Requirement: Agent draft review briefs
The system SHALL brief a claimed `draft_review` task, at claim time, with the internal reviewer's system prompt and context for each part of the draft, the draft's previous review with its suggested corrections, the review mode and `auto_apply`, and SHALL take `{parts: [assessment, ...]}`, one assessment per part in the internal reviewer's shape. A draft the server refuses without a review (unsupported operations, newer knowledge, too large) SHALL get an advisory rejection and no brief.

#### Scenario: Re-reviewing held corrections
- **WHEN** an agent claims the review of a draft whose previous review was held with corrections
- **THEN** the brief's `earlier_review` carries that review and its corrections

### Requirement: Agent draft review verdicts
The system SHALL validate a `draft_review` submission as the internal reviewer's assessment and corrections, refusing it with findings up to 2 times, and SHALL then act on it exactly as on the internal reviewer's assessment, with the claiming agent's principal as the reviewer.

#### Scenario: Approve with corrections under review-and-apply
- **WHEN** draft review is External agent in `review-and-apply` with `auto_apply: with_corrections` and an agent submits `changes_suggested` with a valid correction
- **THEN** the correction is made, the draft is applied, and the recorded review names the agent's principal

#### Scenario: Inconsistent verdict
- **WHEN** an agent submits `changes_suggested` with no corrections
- **THEN** the submission is `refused` with a finding and the run keeps waiting

#### Scenario: Review-only
- **WHEN** the mode is `review-only` and an agent submits `good`
- **THEN** the draft stays submitted with an advisory assessment and no review record

### Requirement: Embeddings keep their model
The system SHALL never use agents for embeddings. Ask MUST NOT be queued as an agent task.

#### Scenario: Ask set to External agent
- **WHEN** Ask is set to External agent and a caller asks a question
- **THEN** no agent task is queued

### Requirement: Agent plan reviews decide every item
The system SHALL brief a `plan_review` task with the profile's audience, templates and documents and each item still proposed with the statements it draws on that the audience may see, and SHALL keep a submission only when it decides every briefed item exactly once (`approve` or `dismiss`, with a reason); a missing, repeated or unknown item is refused with findings, and after 2 refusals the task fails and its items wait for a person.

#### Scenario: An item left out
- **WHEN** an agent submits decisions for one of a review's two items
- **THEN** the submission is refused with a finding naming the undecided item

#### Scenario: A person decided meanwhile
- **WHEN** a person dismisses an item after the review was briefed and the agent approves it
- **THEN** the item stays dismissed and no run starts for it
