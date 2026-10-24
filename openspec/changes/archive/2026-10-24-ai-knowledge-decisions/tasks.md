## 1. Reviewer questions and gap outcomes

- [x] 1.1 Offer reviewer questions as `question` curation items carrying the draft, run and questions
- [x] 1.2 Release a question as `answered` with an answer and evidence, recorded on the review with the agent and starting the next attempt; refuse no evidence and the draft's creator
- [x] 1.3 Release gaps as `resolved` by an applied draft or `not_applicable` with a reason, changing the gap's status as the agent; check outcomes against the item's kind
- [x] 1.4 Widen the curation attempts outcomes (migration v27) and show agents' closing reasons on gaps and the new outcomes on knowledge health

## 2. Grant review

- [x] 2.1 Add `ai_grant_review`, off by default
- [x] 2.2 Review waiting grants with the audience-labelling model in the labelling pass
- [x] 2.3 Queue `audience_review` agent tasks per labeller, never offered to or applied for the labeller

## 3. Alias decisions

- [x] 3.1 Add `alias_decisions` to the draft review controls, off by default
- [x] 3.2 Review alias-only drafts and count them in the backlog while on
- [x] 3.3 Validate and apply the reviewer's alias decisions through the suggestion's accept and reject path

## 4. Docs and skills

- [x] 4.1 Update knowledge health, draft review, audiences, agent tasks, alias suggestions, AI models and MCP tools docs
- [x] 4.2 Update the agent-tasks, code-curation, curation and draft-review skills
