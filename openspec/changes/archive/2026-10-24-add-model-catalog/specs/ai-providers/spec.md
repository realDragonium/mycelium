## ADDED Requirements

### Requirement: Model catalog
The system SHALL keep, as the `model_catalog` product settings section, an ordered list of model IDs per provider (`claude`, `openai`) that admins edit, and SHALL refuse a list that names a model twice or a model ID of the other provider. Model IDs are limited to 200 characters. `GET /api/model-settings` and the draft review settings SHALL return the catalog as `catalog`, each entry with `provider`, `model` and `priced` (whether the price table knows it).

#### Scenario: Adding a model
- **WHEN** an admin saves the `model_catalog` section with `claude` `["claude-opus-5-5"]` at the current revision
- **THEN** `claude-opus-5-5` can be chosen for any action on Claude

#### Scenario: Stale catalog save
- **WHEN** an admin saves the catalog with a revision that no longer matches
- **THEN** the request fails with 409

#### Scenario: Unpriced model
- **WHEN** an admin adds `acme-large` to the OpenAI list
- **THEN** its catalog entry has `priced` false and its calls record no cost

### Requirement: Actions choose from the catalog
The system MUST refuse saving an action model, including the draft review model, that is not in the catalog of its provider, unless it is the model already saved.

#### Scenario: Model outside the catalog
- **WHEN** an admin saves `ask` with `claude_model` `claude-sonnet-5-5`, which the catalog does not list
- **THEN** the request fails with 400 saying the model is not in the Claude model catalog

### Requirement: Removing a model in use
The system MUST refuse a catalog save that removes a model an action still uses, naming the actions; an action uses its selected provider's model, and documentation uses both of its models, because a run may choose either provider.

#### Scenario: Removing the documentation model
- **WHEN** documentation runs on `claude-opus-5-5` and an admin saves the catalog without it
- **THEN** the save fails with "'claude-opus-5-5' is used by Document generation. Choose another model for them first."

### Requirement: No built-in models
The system SHALL start a fresh instance with an empty catalog and every action on `claude`, except `draft_review` on `openai`, with no model chosen. An action without a model for its provider MUST NOT call a model and SHALL report "Choose a <provider> model for <action> in AI settings."

#### Scenario: Fresh instance
- **WHEN** a new data directory starts for the first time
- **THEN** `ingest` reports provider `claude` with an empty `model`
- **AND** an ingest call fails with "Choose a Claude model for ingestion in AI settings."

### Requirement: Upgrade keeps each action on its model
The system SHALL, once, on the first start of an instance with saved settings but no catalog, save the former built-in model for each action that has none saved, logging each, and SHALL add every saved Claude and OpenAI model to the catalog.

#### Scenario: Action that ran on a built-in default
- **WHEN** an instance whose `connect` action has no saved selection upgrades
- **THEN** `connect` is saved on `claude-sonnet-4-6`, the log says so, and `claude-sonnet-4-6` is in the Claude catalog

## MODIFIED Requirements

### Requirement: Model IDs belong to their provider
The system MUST refuse a model ID that is recognisably the other provider's, and SHALL accept an unrecognised ID with a `model_warning` that its cost cannot be estimated; model IDs are limited to 200 characters.

#### Scenario: Claude ID in the OpenAI field
- **WHEN** an admin saves the catalog with `claude-sonnet-4-6` in the OpenAI list
- **THEN** the request fails with 400 naming the ID as a Claude model ID

#### Scenario: Unknown but plausible ID
- **WHEN** an admin adds `claude-workspace-preview-9`, which is not in the price table, to the catalog and saves it as an action's Claude model
- **THEN** the selection is saved
- **AND** the action's `model_warning` says the model is not one this version knows and its cost cannot be estimated

### Requirement: No environment model selection
The system SHALL take each action's provider and model only from saved settings; environment variables MUST NOT select or override them, except for a one-time import on the first start of an instance that predates saved settings.

#### Scenario: Fresh instance ignores legacy variables
- **WHEN** a fresh data directory starts with `MYCELIUM_ASK_MODEL` set
- **THEN** the `ask` action has no model and the variable has no effect

#### Scenario: One-time upgrade import
- **WHEN** an instance that already holds data but has no saved model settings starts with `MYCELIUM_INGEST_PROVIDER=openai` and `MYCELIUM_INGEST_OPENAI_MODEL` set
- **THEN** those values are saved as the `ingest` selection, the model is added to the catalog and the import is recorded
- **AND** later changes to those variables have no effect

## REMOVED Requirements

### Requirement: Built-in model defaults
**Reason**: An action no longer falls back to a model nobody chose; see "No built-in models".
**Migration**: The upgrade saves each former default explicitly for the actions that relied on it.
