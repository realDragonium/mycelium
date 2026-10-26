## Why

Some automatic retries still had no bound. An agent task whose lease ran out,
or that an agent gave back, went back to the queue with no count, and a
give-back's reason was lost on the next claim. Unfinished documentation runs
started again on every server start. The mention and embedding workers
retried a failing row forever, and that row held up its queue. Each sweep
retry of a failed draft review brought its own extra attempt, so an outage
cost about twelve runs per draft with no visible end. A curation agent could
answer the reviewer's questions forever, a skipped curation item came
straight back, and a dismissed plan proposal came back under another key or
title. Every automatic retry should be bounded by a saved limit, end in a
visible terminal state with its reason, and stay stopped until its inputs
change or a person retries it.

## What Changes

- New limits, each default 2:
  - `task_release_retries`, `task_refusal_retries`, `mention_retries` and
    `embedding_retries` in a new Automation section ("Agent tasks and
    background work");
  - `restart_retries` (document generation);
  - `failure_retries` (draft review);
  - `skip_retries` (Connecting statements).
- Agent tasks count expired leases and give-backs (`releases`, keeping
  `release_reason`) and fail at the limit, closing what they served.
- A documentation run counts the restarts that cut it off and fails past
  the limit.
- The mention and embedding workers isolate a failing row, count its failures
  and pass over it at the limit. An outage counts against no row.
- One failure count per draft review covers the rerun and the sweep retries.
  Past the limit the draft review is a stopped automation.
- A curation agent's answer to the reviewer counts toward `answer_retries`.
  Past it the question leaves the curation queue.
- Curation skips and expired claims count per item, and the item stops at
  the limit.
- A dismissed or given-up out-of-date document and a plan update of the same
  revision block each other. A reworded unanchored create drawing on a
  declined one's statements is dropped.
- The stop ledger takes the kinds `draft_review`, `curation`, `mention` and
  `embedding` (substrate schema v29).

## Impact

- Specs: agent-tasks, documentation, drafts-and-review, knowledge-health,
  knowledge-model, embeddings-and-indexes.
- Data:
  - substrate migration v29 with a captured fixture;
  - idempotent columns `agent_tasks.releases` and
    `documentation_runs.restarts`.
