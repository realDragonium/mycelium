## Why

An agent working in a product's repository can check a draft's operations
against the code, which the server's reviewer cannot, but it could only
recommend: approving, rejecting, accepting corrections and editing operations
were web-app only, and a rejection was final. Drafts the automatic reviewer
wrongly rejected or held stayed that way until a person acted.

## What Changes

- `review_draft` lets a real writer or admin decide a submitted draft it did
  not create, over MCP: `approve`, `approve_with_corrections` (the reviewer's
  precise corrections, which also cover editing operations), `reject` with a
  reason, or `needs_context` with a question filed as a knowledge gap. It
  reuses the web app's approve, accept-corrections and reject paths, refuses
  a draft whose revision changed since it was read and an approval over
  knowledge written after the draft, and works under every review setting.
- `reopen_draft` and **Reopen** on the Drafts screen return a rejected draft
  to `submitted`, refused over newer knowledge.
- Every decision, from the web app or an agent, is logged with its decider,
  reason, evidence and corrections; `get_draft` and the draft page show it.
- `list_drafts` returns each draft's review summary and filters on the review
  `label` and `application`, and `GET /api/drafts` filters the same way.

## Impact

- Specs: drafts-and-review.
- Code: a draft decision log table, the decision tools, the approve, reject
  and accept-corrections paths, the drafts list, the Drafts screen.
- Docs: DRAFT_REVIEW, MCP_TOOLS, WEB_APP, AGENT_TASKS and the
  draft-review, agent-tasks, code-curation and draft skills.
