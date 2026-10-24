## Why

AI could already plan, review plans, write, review and deliver documents, but
every failure stopped the loop for a person: a failed plan, plan review or
run, a plan item that could not start, a refused automatic revision, a failed
publication. New documents and plan-item documents waited for someone to
publish them. A large backlog took one plan per batch, the plan reviewer's
instructions could not be edited, an agent could not read a plan over MCP,
and a statement dismissal could not be undone.

## What Changes

- A writing profile gains a `recovery` setting: `person` (default, also for
  every existing profile) or `ai`. Under `ai` the maintenance sweep retries
  failed automatic plans, failed plan reviews, plan items that could not
  start, runs that wrote nothing (briefed with the review's notes when the
  review refused them), automatic revisions that could not start or were
  interrupted, and failed automatic publications, up to `retry_attempts`
  (default 2), then gives up with a reason. Given-up items no longer hold up
  automatic planning.
- `delivery` gains `auto`, and a profile gains `delivery_destination`. Under
  `auto` the sweep publishes every revision of the profile that passed review
  while it is still current: to its recorded destination, or for a document
  never published to `delivery_destination`. Merging stays with the
  repository. Agents may still deliver under `auto`.
- `max_calls` (default 1, at most 5) lets one plan make more planning calls
  while statements no plan was offered remain; each later call is told what
  earlier calls proposed (`already_proposed`). Under External agent each call
  is its own `documentation_planning` task.
- The plan reviewer's instructions become the `plan_review` prompt under
  Settings → Prompts, with a fixed review contract appended.
- `get_documentation_plan(guideline_set)` reads a profile's plan over MCP.
- A dismissed uncovered statement can be restored
  (`POST …/uncovered/{statement_id}/restore`); the plan view lists the
  dismissed statements the audience may still see.
- `delivery_destination` and `recovery` become reserved slot names.

## Impact

- Specs: documentation, agent-tasks.
- Data: settings are profile slots and limits in the revisioned stores.
  `documentation_runs` gains `retry_of`, `attempt`, `recovery`,
  `recovery_note`, `delivery`, `delivery_error` and `delivery_attempts`, and
  `document_maintenance` gains `attempts`, by in-place `ALTER TABLE` in the
  drafts store; runs finished before the upgrade are marked decided, so no
  automation acts on them. Every new automation is off after the upgrade.
- Code: profiles, planning, plan review, maintenance sweep, run retry, the
  MCP manifest (50 tools), the profile editor, Plan page and run view.
