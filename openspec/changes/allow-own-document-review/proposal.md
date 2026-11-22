## Why

The server never offered a review task to the account that made the thing under review: a document's review to the account that submitted it, a plan's review to the agent that planned, a draft's review to its creator, or a grant or label review to its labeller. A deployment that wants no provider key therefore needed two service accounts only to get a page saved, a plan decided or a draft applied. The rule gave nothing in return: two tokens of one agent setup were never told apart, and a review already sees only its brief, not the maker's conversation.

## What Changes

- A `document_review`, `plan_review`, `draft_review` or `audience_review` task is offered to any writer or admin account, the one that made the thing included. One account can make and review.
- A submission by that account is acted on like any other reviewer's: a draft's creator is no longer refused when it submits the review, an agent's review of its own account's draft is applied under `review-and-apply`, and a grant or label review no longer skips the items the reviewer labelled.
- **BREAKING** `claim_agent_task` no longer returns `note`; no task is withheld.
- `audience_review` batches are no longer grouped per labeller or curator.
- The review setting reads **An agent** instead of **Another agent**, and the agent-tasks skill tells an agent to review in a session that did not make the thing.
- The same comparison is removed everywhere else it was made: the configured reviewer account may be the draft's creator, `review_draft` and `reopen_draft` accept a draft the caller created, a reviewer may decide alias suggestions of a draft it created, and a draft's creator may answer its reviewer's question through the curation queue.
- Unchanged: deciding, reviewing or reopening a draft still needs a real writer or admin, so a drafter-scoped token can approve nothing, its own drafts included. Withdrawing a draft stays its creator's choice.

## Impact

- The independence of a review now rests on how the agents are run, not on the account. A setup that reviews in the conversation that made the thing gets a weaker review.
- Tasks queued before this change that named an excluded account can be claimed by anyone; the stored value is ignored.
