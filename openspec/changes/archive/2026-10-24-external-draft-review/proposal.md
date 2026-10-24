## Why

Everything a person or the server's model does to keep the knowledge base
current should also be doable by an outside agent. Draft review was the one
model action that still needed a provider key: a deployment without one could
not review drafts at all, and more than a hundred drafts held with suggested
corrections had no reviewer to settle them.

## What Changes

- Draft review takes External agent as its runner, saved with the review
  settings. A review run queues a `draft_review` agent task instead of calling
  a model.
- The task's brief is built when it is claimed: the internal reviewer's system
  prompt and context (draft, operations, evidence, affected knowledge, nearest
  live statements, link types, curators' answers), the earlier review with its
  suggested corrections, the mode and `auto_apply`. The agent submits one
  assessment per part, in the internal reviewer's shape.
- A submission passes the same validation and acts through the same path as a
  model's assessment: exact-state checks, `auto_apply`, gap filing, review
  records and the application gate. The agent's principal is the reviewer.
- The draft's creator is never offered its review and is refused naming why.
- While agents review, held corrections count as backlog, so the backlog job
  queues them for another review.
- A run waiting for an agent survives a restart.

## Impact

- Specs: agent-tasks, drafts-and-review.
- Code: agent task kinds and claim, model settings, review settings, review
  runs and store, startup, the Draft review settings form and draft page.
- Docs and skills: AGENT_TASKS, DRAFT_REVIEW, MCP_TOOLS, AI_MODELS,
  mycelium-agent-tasks, mycelium-draft-review.
