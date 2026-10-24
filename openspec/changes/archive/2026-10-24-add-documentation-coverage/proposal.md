## Why

A person had to notice what documentation was missing. The planner saw only
an overview of concepts and the most connected statements, so smaller
features slipped through; a document was flagged only when statements it
cites changed, never when new relevant statements appeared; and re-planning
was manual.

## What Changes

- A writing profile's **uncovered statements** are those its audience may see
  that no document of the profile cites. The plan view lists them with a
  count, and knowledge health reports the count per profile. No model is
  needed.
- A writer can dismiss an uncovered statement for a profile, so it stops
  counting.
- Every plan is given a bounded batch of uncovered statements
  (`max_uncovered`, default 40; those no plan was offered first) and the
  opening of each existing document, and places them through the existing
  item shapes: an `update` adding them to a document, or `create` items
  grouping them. An approved update that lists statements its document does
  not cite is briefed with those statements and their text.
- A profile gains a `planning` policy: `off` (default, also for every
  existing profile), `propose` or `write`. The maintenance sweep plans by
  itself once `replan_hint_statements` uncovered statements were offered to
  no plan; under `write` it starts the automatic plan's items within the
  batch and active-run limits, each through the usual document review.
- The planning slot name `planning` is reserved and can no longer name a
  template.

## Impact

- Specs: documentation, knowledge-health.
- Data: plans gain an `automatic` flag (drafts database, captured fixture);
  statement dismissals reuse the plan dismissals; the policy is a profile
  slot. No substrate migration.
- Code: documentation planning and profiles, the maintenance sweep, the plan
  and health routes, the Plan, profile, health and limits screens.
