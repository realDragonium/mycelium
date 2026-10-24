## 1. Catalog

- [x] 1.1 Add the `model_catalog` product settings section with per-provider ID validation
- [x] 1.2 Refuse removing a model an action uses, naming the actions
- [x] 1.3 Refuse saving an action model that is not in the catalog
- [x] 1.4 Return the catalog, with list-price status, in the model settings views

## 2. No built-in models

- [x] 2.1 Remove the Ask, Ingest and documentation model defaults
- [x] 2.2 Report "Choose a <provider> model for <action> in AI settings" where an action has no model
- [x] 2.3 Save former defaults explicitly on upgrade, log them, and seed the catalog
- [x] 2.4 Captured-fixture upgrade test

## 3. Screens and docs

- [x] 3.1 Catalog card and model selects in AI settings and Draft review
- [x] 3.2 Generate a document marks providers without a model
- [x] 3.3 Update AI models, web app, draft review and MCP tools docs
