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
- A catalog model without a list price records its cost as unknown.
- Upgrade: an action that relied on a built-in default has that model saved
  explicitly and logged, and the catalog is seeded from every saved model,
  so no action changes the model it runs on.

## Impact

- Specs: ai-providers, ingest, knowledge-health, storage-and-backup.
- Code: model settings, product settings, settings startup migrations, the
  Ask, Ingest and documentation configs, the AI settings and documentation
  workspace screens.
- Embedding models are unchanged.
