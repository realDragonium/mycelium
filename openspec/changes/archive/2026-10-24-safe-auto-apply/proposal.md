## Why

An evaluation of automatic review on CI drafts found every draft the reviewer
approved without corrections landed correctly, but its corrections did about
as much harm as good: a `revise` replaced a whole operation, so fixing one
statement could renumber the batch and silently move or drop links and
conditions the reviewer never meant to touch.

## What Changes

- **BREAKING** `review-and-apply` gains `auto_apply`. The default, `clean`,
  applies only `good` assessments; a `changes_suggested` assessment ends
  `held`, changing nothing, until a curator accepts its corrections.
  `with_corrections` keeps the earlier behaviour.
- `POST /api/drafts/{id}/review/accept` lets a curator make a held review's
  corrections, as suggested or edited, and approve the draft in one step.
- **BREAKING** Corrections become precise: `edit` (one statement's text or
  kind, or an entity's description), `add_link`, `drop_link`,
  `drop_statement`, `strike` and `append`. `revise` is no longer accepted;
  stored ones stay readable. Indices name the draft as submitted, references
  follow a dropped statement, and a correction set that changes anything it
  does not name is refused. Up to 12 corrections per review.

## Impact

- Specs: drafts-and-review.
- Code: draft corrections, review runs and store, review settings, the
  accept route, the reviewer prompt, the Drafts and Settings screens.
