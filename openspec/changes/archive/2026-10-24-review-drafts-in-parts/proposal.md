## Why

Drafts submitted from CI should be reviewed and applied without a person,
but a draft affecting more than 30 knowledge records was refused outright,
nothing bounded what one review could cost, an old draft could land over
newer knowledge, and the backlog review started every waiting draft at once.

## What Changes

- **BREAKING** A draft too large for one review context is reviewed in
  connected parts instead of failing for size; it lands only when every part
  accepts, and its assessment lists the parts.
- A review is refused without a model call when its estimated cost passes a
  per-draft cap (`max_cost_usd`, default US$1) or when the draft would
  overwrite a record changed after the draft was created.
- A correction must name a draft's new statements the way they resolve, and
  must carry a JSON object payload; otherwise the attempt fails saying so.
- `POST /api/draft-review/backlog` starts one background job that reviews the
  backlog oldest first, within an optional budget, and can be paused and
  resumed.

## Impact

- Specs: drafts-and-review.
- Code: draft review runs, review store, product settings, backlog HTTP
  routes, the Drafts and Settings screens.
