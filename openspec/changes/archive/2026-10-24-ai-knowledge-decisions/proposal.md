## Why

Some decisions that keep the knowledge base current can only be made by a
person today: answering the draft reviewer's questions, closing knowledge
gaps, confirming AI grants to external audiences and deciding alias
suggestions. Anything a person can or must do to keep the knowledge base
current should also be doable by AI, by the server's model or by an outside
agent, through the queues and review paths that already exist. Each new
automation is off by default.

## What Changes

- The curation queue gets a `question` kind: the reviewer's open question
  about a submitted draft. A code-aware agent answers it by releasing it as
  `answered` with the answer and evidence; the answer is recorded as a
  curator's is, with the agent as author and its evidence, and starts the
  next review. An answer without evidence, or from the draft's creator, is
  refused.
- `release_curation_work` takes gap outcomes `resolved` (by an applied
  draft) and `not_applicable` (with a reason), which resolve or dismiss the
  gap as a person's status change does, and outcomes are checked against
  the item's kind. Gap listings carry the agent's closing reason.
- New audience-labelling setting `ai_grant_review` (off): a second AI
  confirms or rejects waiting external grants with a reason, as a server
  model call in the labelling pass or as `audience_review` agent tasks that
  the labeller is never given.
- New draft-review setting `alias_decisions` (off): the draft reviewer, on a
  server model or an outside agent, accepts or rejects alias suggestions
  with a quote from the suggestion's evidence, through the same review path.
- Creating, editing and retiring audiences, writing profiles, prompts and
  admin operations stay human-only.

## Impact

- Specs: knowledge-health, agent-tasks, audiences, drafts-and-review.
- Code: curation queue and release, the curation attempts table (migration
  v27), gap listing, audience labelling and grant review, the agent task
  registry, draft review settings, assessment, runs and backlog, alias
  suggestions, and the knowledge health, gaps, audiences, limits and
  draft-review screens.
- Docs: knowledge health, draft review, audiences, agent tasks, alias
  suggestions, MCP tools, web app; the agent-tasks, code-curation and
  curation skills.
