## 1. Queue

- [x] 1.1 Add the `draft_review` kind and allow External agent for draft review
- [x] 1.2 Queue a task per run and brief it at claim time with the reviewer's context and the earlier review
- [x] 1.3 Validate a submission as a model assessment and act through `_finish` as the agent
- [x] 1.4 Withhold a draft's review from its creator and say why
- [x] 1.5 Keep waiting runs at restart; count held corrections as backlog while agents review

## 2. Settings and screens

- [x] 2.1 Save `external_agent` with the review settings, needing no model or reviewer
- [x] 2.2 Offer External agent in the Draft review form and name the agent reviewer on drafts

## 3. Docs

- [x] 3.1 Update AGENT_TASKS, DRAFT_REVIEW, MCP_TOOLS and AI_MODELS
- [x] 3.2 Add the draft-review task to mycelium-agent-tasks and align mycelium-draft-review
