## 1. Recovery

- [x] 1.1 Add the `recovery` profile setting, `person` by default, and the `retry_attempts` limit
- [x] 1.2 Retry failed automatic plans, plan reviews and plan items that could not start, then give up with a reason
- [x] 1.3 Retry runs that wrote nothing, with the review's notes when refused, and let plan items and automatic revisions follow the retry
- [x] 1.4 Release failed or interrupted automatic-revision claims for another attempt

## 2. Delivery

- [x] 2.1 Add `auto` delivery and the `delivery_destination` profile setting, validated against configured destinations
- [x] 2.2 Publish every reviewed current revision under `auto`; retry failed publications under `ai` recovery

## 3. Planning

- [x] 3.1 Add `max_calls` and plan over several calls with `already_proposed`, one agent task per call
- [x] 3.2 Make the plan-review instructions an editable prompt
- [x] 3.3 Add `get_documentation_plan` to MCP
- [x] 3.4 Restore a dismissed uncovered statement

## 4. Data, screens and docs

- [x] 4.1 Add run and maintenance columns in place; mark runs finished before the upgrade as decided; capture a migration fixture
- [x] 4.2 Profile editor, limits, Plan page and run view
- [x] 4.3 Update DOCUMENTATION_PLANNING, DOCUMENTATION_MODELS, AGENT_TASKS, MCP_TOOLS, WEB_APP and the documentation and agent-task skills
