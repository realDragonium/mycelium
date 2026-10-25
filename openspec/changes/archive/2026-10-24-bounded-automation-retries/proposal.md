## Why

The AI decisions added for statements, concepts and labels retry
automatically, and some retries had no bound or lived only in memory: a
failing connect run took the same statements every minute, a failed
`audience_review` task was queued again on every pass, the reviewer could
review a draft again after every alias refresh, and a rejected curation
proposal filed a gap that the curation pass acted on again, so curation and
review could loop. Every automatic retry should be bounded by a saved limit,
end in a visible terminal state with its reason, and stay stopped until its
inputs change or a person retries it.

## What Changes

- Limits, default 2 retries: `answer_retries` and `refresh_reviews` (draft
  review), `decision_retries` (audience labelling), `connect_retries` and
  `follow_up_retries` (Connecting statements).
- A persistent stop ledger (`automation_stops`, substrate schema v28) counts
  failures per item and its inputs for audience decisions and connect
  runs, and records gap follow-ups the chain guard stopped.
- Knowledge health lists stopped automations with their reasons; an admin
  retries one.
- Draft review runs note when AI answers or refreshed reviews stopped.

## Impact

- Specs: audiences, drafts-and-review, knowledge-health.
- Data: substrate migration v28 with a captured fixture.
