## 1. Allow the writer's account to review

- [x] 1.1 Queue `document_review` tasks without an excluded account
- [x] 1.2 Reword the review setting, the task and tool descriptions, the docs and the agent-tasks skill
- [x] 1.3 Test that one account writes and reviews a document

## 2. Allow the maker's account to review plans, drafts and labels

- [x] 2.1 Queue `plan_review`, `draft_review` and `audience_review` tasks without an excluded account
- [x] 2.2 Accept a draft creator's review submission and apply an agent's review of its own account's draft
- [x] 2.3 Apply a grant or label decision by the account that labelled it, and stop grouping review batches per labeller
- [x] 2.4 Remove the excluded account from tasks and claims, and `note` from the claim result; leave the stored column
- [x] 2.5 Reword the tool description, the docs, the agent-tasks skill and the settings hints
- [x] 2.6 Test that one account plans and reviews a plan, creates and reviews a draft, and labels and reviews grants

## 3. Remove the remaining creator comparisons

- [x] 3.1 Let the configured reviewer account review and apply a draft it created
- [x] 3.2 Let `review_draft` and `reopen_draft` decide a draft the caller created
- [x] 3.3 Let a reviewer decide alias suggestions of a draft it created
- [x] 3.4 Let a draft's creator answer its reviewer's question through the curation queue
- [x] 3.5 Reword the tool descriptions, the docs and the curation and draft-review skills
