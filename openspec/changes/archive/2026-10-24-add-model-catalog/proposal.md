## Why

Each action's model is a free-text ID, and an action with nothing saved
silently runs on a built-in Claude model. Admins cannot limit which models
people pick, and an instance can run, and spend, on a model nobody chose.

## What Changes

- AI settings gains a model catalog: per provider (Claude, OpenAI), the model
  IDs admins allow, added, removed and ordered by an admin. It is the
  `model_catalog` product settings section, revisioned like the others.
- Every action's model, the draft-review model and the documentation-run
  model become choices from the catalog of the chosen provider. Saving a
  model that is not in the catalog is refused.
- **BREAKING** No built-in model defaults. An action has a provider only once
  a model is saved for it; otherwise it reports "Choose a <provider> model
  for <action> in AI settings." Generate a document shows a provider with no
  model as disabled, with that reason.
- Removing a catalog model an action still uses is refused, naming the
  actions.
- **BREAKING** Mycelium keeps no prices. The built-in list-price table and
  every dollar estimate go; usage is recorded and shown in tokens (input,
  cached, output) per call, action and model, and the AI usage page points
  to each provider's billing dashboard for spend.
- **BREAKING** Every money limit becomes a token limit: the monthly budget
  (`monthly_limit_tokens`), the draft review cap (`max_draft_tokens`), the
  connect pass cap (`max_run_tokens`) and the backlog budget
  (`budget_tokens`, reporting `used_tokens`).
- Upgrade: an action that relied on a built-in default has that model saved
  explicitly and logged, and the catalog is seeded from every saved model,
  so no action changes the model it runs on.
- Upgrade and restore: a saved dollar limit at its shipped default takes the
  token default; any other becomes no limit and is logged. Historic
  `cost_usd` values stay in the ledger unread.

## Impact

- Specs: ai-providers, ingest, knowledge-health, storage-and-backup,
  drafts-and-review, search-and-ask, documentation, audiences.
- Code: model settings, product settings, settings startup migrations, the
  Ask, Ingest and documentation configs, the AI usage ledger and budget, the
  draft review and connect caps, run traces, the AI settings, AI usage and
  documentation workspace screens, the eval scripts.
- Embedding models are unchanged.
