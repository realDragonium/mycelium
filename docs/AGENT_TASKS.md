# Agent tasks

An action set to **External agent** in **Settings → Models** (see
[AI models](AI_MODELS.md#external-agent)) does not call a server model.
The server queues the model's part of the work as a task, and an outside agent
claims it over MCP, does it and submits the result. The agent can be Claude
Code, Codex or any MCP client. The server keeps everything else: what the work
needs, the audience boundary, the checks and what is saved. A deployment can
then write documentation, plan it and label audiences with no provider key on
the server, using the agents its people already run.

## Actions

| Action | External agent | |
|---|---|---|
| Documentation (writing and revising) | Yes | Kind `documentation` |
| Documentation review | Yes, for documents an agent wrote | Kind `document_review`, when Review is **Another agent**. A person's manual edit is still reviewed by the server's reviewer |
| Documentation planning | Yes | Kind `documentation_planning`, and `plan_review` for a profile whose plan items an AI reviewer decides |
| Audience labelling | Yes | Kind `audience_labelling` |
| Review of waiting external grants | Yes, for grants another agent labelled | Kind `audience_review`, when **AI reviews waiting external grants** is on; see [Audiences](AUDIENCES.md#ai-review-of-waiting-grants) |
| Edited curator labels and kept grants | Yes, for labels another account set | Kind `audience_review`, when **AI decides edited curator labels and kept grants** is on; see [Audiences](AUDIENCES.md#ai-decisions-on-edited-labels) |
| Ingest | Yes | Kind `ingest` |
| Connect pass | Yes | Kind `connect` |
| Alias discovery | Yes | Kind `alias_discovery` |
| Draft review | Yes | Kind `draft_review`, set under **Settings → Draft review**; see [Draft review](DRAFT_REVIEW.md#external-agent) |
| Ask | Yes, as the caller's own agent | No task kind; see below |
| Embeddings | No | They use the local model or an embedding API, never agents |

**Ask** is interactive: the caller waits for an answer, so a queued Ask
would wait for some other agent to pick the question up. A caller that has
an agent of its own already has what an external Ask needs: the read tools
(`search_statements`, `get_statements` and the rest) and the audience
boundary of its own token. So External agent for Ask queues nothing. The
server runs no model for it: `ask` is left out of `tools/list` and a call to
it (over MCP or `POST /ask`) is refused with a message naming the
`mycelium-research` skill, which teaches the agent the Ask loop's research
and answering rules. The web app hides Ask (its mode in the command bar
and "Ask about this"); Find stays.

The `mycelium-agent-tasks` skill (`skills/`) walks an agent through the
workflow.

## Who may claim

The agent needs a **writer** or **admin** token. That is the role that may
already ask the server for documentation, so an agent can do no more than its
token could request. Drafters cannot claim: a drafter's writes go to a draft
for review, but an agent's document, plan or labels are saved as a server
model's would be. Readers cannot claim either. A draft's creator is never
given its review, nor the agent that made a plan its plan review, nor a
labeller the review of its own grants: a claim that held such tasks back says
so in `note`, and a submission by the creator is refused and the task goes
back to the queue (a grant review skips the grants it labelled).

## Kinds

| `kind` | Queued when | The agent submits |
|---|---|---|
| `documentation` | A documentation run starts, or a document is revised, while Documentation is set to External agent | The document: title, Markdown body and the statement ids it rests on, as the server's writer emits it |
| `document_review` | An agent's document passed its checks and Documentation's Review is **Another agent** | The review: exposure and conformance verdicts with findings |
| `documentation_planning` | A plan is requested for a writing profile, by a person or by the profile's automatic planning, while Documentation planning is set to External agent; and for each further call of a plan allowed more than one | The proposed documents, placing the brief's uncovered statements in updates of existing documents or in new ones, without proposing again what `already_proposed` lists |
| `plan_review` | A profile whose plan items an AI reviewer decides has proposed items no review decided (checked by the maintenance sweep and when an agent claims), while Documentation planning is set to External agent | A decision for every item: `approve` or `dismiss`, with a reason |
| `audience_labelling` | An agent asks for labelling work while Audience labelling is set to External agent | A label for each statement in the batch |
| `audience_review` | An agent asks for review work while Audience labelling is set to External agent and **AI reviews waiting external grants** or **AI decides edited curator labels and kept grants** is on; one batch per labeller (or curator) and subject | `decisions`: confirm or reject, with a reason, for each waiting grant (`statement_id` and `audience_id`), or for each statement of an edited-label or kept-grant batch (`statement_id`) |
| `ingest` | `ingest` is called while Ingest is set to External agent | The `emit_draft` input: proposed operations, the reconcile ledger, flags and skipped duplicates |
| `connect` | `connect_statements` is called while Connect is set to External agent | The same, for the statements in the batch |
| `alias_discovery` | An alias scan is started while Alias discovery is set to External agent | The aliases the statements show, with their evidence |
| `draft_review` | A draft is submitted, reviewed again, or reached by the backlog job while Draft review is set to External agent | One assessment per part of the draft: approve (`good`), approve with corrections (`changes_suggested`), `reject` or ask a person (`needs_context`) |

Labelling batches are made when an agent claims, from the statements due
then, at the labelling batch size set under Limits. A statement in an open
batch is not put in another. A statement whose text changed after it was
batched is not labelled from that batch; it is due again.

A manual edit of a document still goes through the server's reviewer and so
needs a documentation model. Asking for a run with an explicit `provider`
(`claude` or `openai`) runs it on the server whatever the setting.

## Workflow

1. **Claim.** `claim_agent_task(kind, limit=1)` (at most 5) leases waiting
   tasks for 30 minutes, oldest first. Each call also renews every task of
   that kind the caller holds; `limit=0` only renews. A task whose lease runs
   out goes back to the queue, and the task shows why it was released
   (`release_reason`) and how often (`releases`). Each task carries a `brief`:
   - `instructions` and `input`: the system prompt and first message a
     server model would get, built by the same code;
   - `read_tools`: the reads it could make (documentation, ingest and
     connect);
   - `result` and `result_schema`: what to submit;
   - for documentation, the `guideline_set`, `document_type` and `audience`;
   - for documentation, document review, documentation planning and plan
     review, `profile`: the whole writing profile the task is for (name,
     audience with its description, guidance, disclosure rules, the chosen
     template or every template for planning, policies and destinations),
     as `get_writing_profile` would return it. The skills tell the agent to
     follow it and carry no writing advice of their own.

   `findings` hold why the last submission was refused.
2. **Read** (documentation, ingest and connect). `read_for_agent_task(task_id,
   tool, arguments)` runs one of the brief's `read_tools`. Report missing
   knowledge with `report_knowledge_gap`.
3. **Submit.** `submit_agent_task(task_id, result)` with the result shaped
   as `result_schema`. It returns `accepted` (saved), `refused` (with
   `findings` and `retries_left`; fix and submit again), `in_review` (another
   agent reviews the document next) or `failed` (the work is closed and the
   run or plan records why).
4. **Or release.** `release_agent_task(task_id, reason)` gives a task back
   at once. The next claimant sees the reason.

A lease that runs out and a give-back both count toward the task's limit,
**Retries of an agent task whose claim ran out or was given back**
(**Settings → Limits → Agent tasks and background work**,
`task_release_retries`, default 2). Past it the task is `failed` with the
reason and the count, and what it served is closed as when its work fails: a
documentation run writes nothing, a plan fails, a draft review fails and is
followed up. Refused submissions have their own limit, **Retries of an agent
task whose submission was refused** (`task_refusal_retries`, default 2), for
kinds whose server run has no retry count of its own.

`ingest`, `connect_statements` and an alias scan return at once with
`waiting_for_agent` and the task id. Whoever queued the work, or an admin,
follows it with `get_agent_task(task_id)`: its status, the findings of a
refused submission and, once done, its `result`, such as the draft it made.

## The same boundaries as a server run

- **Audience.** A documentation task writes for its profile's audience, and
  every read runs inside that audience's boundary (`audience_scope`), as an
  internal run's reads do. A statement the audience may not see is not
  returned. The boundary is captured again on each read and each submission,
  so a statement whose label narrowed since is no longer readable or citable.
- **Citations.** A document may cite only statements a read returned to this
  claimant and the audience may still see. Statements the opening reads in the
  brief returned count as read. A new claimant starts again from those.
- **Vocabulary and media.** The internal-vocabulary refusal and the media check
  of the server's emit gate apply unchanged.
- **Template conformance and exposure.** A grounded document is reviewed
  against the template and the audience's exposure rules, by the server's
  reviewer or by a second agent (see [Review](#review)).
- **Plans.** A proposal is kept as a model's is: only items citing statements
  the profile's audience may see, using templates the profile has and naming
  documents it owns survive. The overview is read again when it is submitted.
- **Plan reviews.** Every item in the brief must be decided once, with a
  reason. An item a person decided meanwhile is left as they decided it. An
  approval starts the item's run within the batch-approval and active-run
  limits; a dismissal is remembered for the profile.
- **Labels.** Every statement in the batch must be labelled once, with
  audience ids that exist and a reason. New external grants wait for
  confirmation when the labelling settings ask for it, as the server labeller's
  do.
- **Ingest and connect.** A submission goes through the loop's own emit
  gate: the reading floor (a reconcile read, then a search around it, made
  with `read_for_agent_task` by this claimant), the ledger and coverage
  checks, then the same screening, validation and draft assembly. The draft
  goes to review as a server run's does; connect also records what it looked
  at and files its rephrase gaps.
- **Aliases.** Evidence must quote a selected statement. Suggestions are
  checked and kept as the model's are, in a draft made by whoever started the
  scan; a change of names since then fails the task, as it fails a scan.

## Retries

A refused submission can be followed by another, as often as the internal
loop would try again:

| Check | Refusals before the work closes |
|---|---|
| Malformed document | 1 |
| Citations, vocabulary or media | 3 |
| Review | 1 (the document returns to its writer with the review's findings) |
| Malformed review | 1 |
| Malformed or invalid plan, plan review, labels, grant review, aliases or draft review | 2 |
| Malformed ingest or connect draft | 1 |
| Ingest or connect reading floor or ledger | 3, then the last submission is kept as a degraded draft, as the loop's forced finalize keeps one |

When the last retry is used, the run is recorded as nothing written, the plan
fails, a plan review's items wait for a person, or the statements' labelling failure is counted, as for a server model.
A writing profile that retries failed AI work then queues the work again, as
for a server model, up to that kind's retries limit
([When AI work fails](DOCUMENTATION_PLANNING.md#when-ai-work-fails)).
A failed `audience_review` task counts a failure for each of its items; an item
past **Retries of a failed AI audience decision** is not queued again until its
statement or label changes or an admin retries it, and the task's result says
how many items stopped ([Audiences](AUDIENCES.md#stopped-decisions)).

## Review

**Server reviewer** (the default) reviews the document when it is submitted,
synchronously, on the documentation provider and model. **Another agent** puts
the writing task `in_review` and queues a `document_review` task. The task is
never offered to the writer who submitted the document. A passed review saves
the document. A failed one sends the writing task back to the queue with the
review's findings.

## Where it shows

- **Documentation runs** read **Waiting for agent** until the document is
  saved or refused. `get_documentation_run` and the run list carry
  `agent_task`: the task's status, who holds it and until when, failures and
  the last findings. A waiting run does not take one of the active-run slots.
- **Documentation plans** show the same in `latest.agent_task`, and an open
  plan review in `review_task`.
- **Audience labelling status** (`GET /api/audiences/labelling`) has
  `external_agent`, the open labelling batches in `agent_tasks` and the open
  grant review batches in `review_tasks`. Automatic labelling
  does not call a model while the setting is on.

Tasks live in the drafts database with documentation runs and plans. They are
in backups and survive a restart: a run or plan waiting for an agent keeps
waiting.

## Adding a kind

Every kind plugs into the queue the same way: a `Kind` value in
`agent_tasks`, a place that queues tasks while its action is set to External
agent, and an `agent_tasks.Handler` in the table in `server/agent_tasks.py`.
A handler has a `submit` that checks and keeps a result, and optionally a
`prepare` that briefs a claimed task, a `read` for kinds whose model reads
as it works, and a `queue` for work nobody requests. Kinds whose internal
run is one structured model call use `structured_brief`; refusals and
closing go through `refused` and `closed`. The action is then added to
`model_settings.AGENT_ACTIONS`.
