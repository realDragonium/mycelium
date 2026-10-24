## Why

People cannot judge token budgets sensibly, and a monthly token budget
inside Mycelium duplicates, badly, the dollar spend limits each provider's
console already enforces. Mycelium should report what AI work used and
guard single runs against running away, and leave spend limits to the
providers.

## What Changes

- **BREAKING** The monthly AI budget goes: the `ai_budget` settings section
  (`monthly_limit_tokens`, `warn_percent`, `pause_background`), the pause
  that refused background model calls, `GET /api/ai-usage/budget`, the admin
  banner, the budget line on the AI usage card, the budget in
  `GET /api/ai-usage` and the setup checklist's `budget` step.
- **BREAKING** The draft-review backlog has no token budget: the offer drops
  `estimated_tokens`, the start request takes no `budget_tokens`, and the
  job runs until no waiting draft is left. It still pauses and resumes, and
  still reports `used_tokens`.
- Per-run safety limits stay under Settings › Limits with their defaults:
  `max_draft_tokens`, `max_run_tokens` and the per-call token limits, worded
  as runaway guards rather than spend limits.
- The AI usage page keeps its token reports and points to each provider's
  billing dashboard for spend and spend limits.
- Upgrade and restore drop a saved `ai_budget` section, logging the limit
  when one was set, and a dismissed `budget` setup step. A review an earlier
  budget paused is resumed by the retry sweep.

## Impact

- Specs: ai-providers, knowledge-health, drafts-and-review, operations.
- Code: AI metering, the usage ledger and route, product settings and their
  startup and restore upgrades, the setup checklist, the backlog job and
  route, and the AI usage, limits, setup, shell and draft-review screens.
- Docs: AI models, draft review, web app, knowledge health; the draft skill.
