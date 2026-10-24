## Why

Keeping documentation current still needed a person for three decisions:
asking for a plan (only the web app could), approving or dismissing what the
plan proposed, and publishing a document as a pull request. A deployment that
runs on outside agents, with no provider key, could write and plan documents
but not finish the loop.

## What Changes

- `request_documentation_plan(guideline_set)`, advertised over MCP to real
  writers and admins, starts the same plan as Documents → Plan, on the
  server's model or as a `documentation_planning` agent task.
- A writing profile gains a `plan_review` setting: `person` (default, also
  for every existing profile) or `ai`. Under `ai` an AI reviewer approves or
  dismisses every proposed item of the profile's plan, including update items
  for out-of-date documents, with a reason. It runs where documentation
  planning runs: one model call separate from the planner's, or a
  `plan_review` agent task the plan's own agent cannot claim. Approval starts
  runs within the batch-approval and active-run limits; dismissals are
  remembered as a person's are. A failed review leaves its items for a person.
- A writing profile gains a `delivery` setting: `people` (default) or
  `agents`. `deliver_document` is advertised over MCP to real writers and
  admins and is refused unless the document's profile is `agents`. People
  publish from the web app whatever the setting; merging stays with the
  destination repository.
- `plan_review` and `delivery` become reserved slot names.

## Impact

- Specs: documentation, agent-tasks.
- Data: both settings are profile slots in the revisioned prompt store; a
  review is kept in its plan's summary. No schema change; existing profiles
  read as `person` and `people`, so every new automation is off after the
  upgrade.
- Code: profiles, plan review and its agent task, the maintenance sweep, the
  MCP manifest (49 tools), the profile editor and Plan page.
