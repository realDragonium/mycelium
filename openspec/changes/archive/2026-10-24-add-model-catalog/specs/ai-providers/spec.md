## ADDED Requirements

### Requirement: Model catalog
The system SHALL keep, as the `model_catalog` product settings section, an ordered list of model IDs per provider (`claude`, `openai`) that admins edit, and SHALL refuse a list that names a model twice or a model ID of the other provider. Model IDs are limited to 200 characters. `GET /api/model-settings` and the draft review settings SHALL return the catalog as `catalog`, each entry with `provider` and `model`.

#### Scenario: Adding a model
- **WHEN** an admin saves the `model_catalog` section with `claude` `["claude-opus-5-5"]` at the current revision
- **THEN** `claude-opus-5-5` can be chosen for any action on Claude

#### Scenario: Stale catalog save
- **WHEN** an admin saves the catalog with a revision that no longer matches
- **THEN** the request fails with 409

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

### Requirement: Usage counted in tokens
The system SHALL count usage in tokens, a call's total being its input, cache-read, cache-write and output tokens, and SHALL keep no prices and report no money amounts; `cost_usd` values written by earlier versions SHALL be kept and not read.

#### Scenario: A call's tokens
- **WHEN** a call reports 1,000 input, 4,000 cache-read, 500 cache-write and 200 output tokens
- **THEN** the usage report counts it as 1,500 input, 4,000 cached, 200 output and 5,700 tokens in total

### Requirement: Upgrade replaces dollar limits
The system SHALL, on start and on restoring an archive, replace a saved dollar limit by its token field: `ai_budget.monthly_limit_usd` by `monthly_limit_tokens`, and `max_cost_usd` by `max_draft_tokens` for draft review and by `max_run_tokens` for connect. A value still at its shipped default ($0, $1 and $0.50) SHALL take the token default; any other value SHALL become 0, meaning no limit, with a log warning naming the old amount.

#### Scenario: A set monthly budget
- **WHEN** an instance with `monthly_limit_usd` 50 upgrades
- **THEN** `monthly_limit_tokens` is 0 and the log says the $50 budget became no limit

#### Scenario: A default review cap
- **WHEN** an instance with draft review `max_cost_usd` 1.0 upgrades
- **THEN** `max_draft_tokens` is 300,000

## MODIFIED Requirements

### Requirement: Model IDs belong to their provider
The system MUST refuse a model ID that is recognisably the other provider's, and SHALL accept any other ID without a warning; model IDs are limited to 200 characters.

#### Scenario: Claude ID in the OpenAI field
- **WHEN** an admin saves the catalog with `claude-sonnet-4-6` in the OpenAI list
- **THEN** the request fails with 400 naming the ID as a Claude model ID

#### Scenario: Unknown but plausible ID
- **WHEN** an admin adds `claude-workspace-preview-9` to the catalog and saves it as an action's Claude model
- **THEN** the selection is saved
- **AND** the action's `model_warning` is null

### Requirement: No environment model selection
The system SHALL take each action's provider and model only from saved settings; environment variables MUST NOT select or override them, except for a one-time import on the first start of an instance that predates saved settings.

#### Scenario: Fresh instance ignores legacy variables
- **WHEN** a fresh data directory starts with `MYCELIUM_ASK_MODEL` set
- **THEN** the `ask` action has no model and the variable has no effect

#### Scenario: One-time upgrade import
- **WHEN** an instance that already holds data but has no saved model settings starts with `MYCELIUM_INGEST_PROVIDER=openai` and `MYCELIUM_INGEST_OPENAI_MODEL` set
- **THEN** those values are saved as the `ingest` selection, the model is added to the catalog and the import is recorded
- **AND** later changes to those variables have no effect

### Requirement: Usage ledger
The system SHALL record every model call, whether it succeeded or failed, as one row in the `ai_usage` table of `mycelium-drafts.db` with time, action, provider, model, input, cache-read, cache-write and output tokens, duration, success and, when known, the run and draft it served; a call made outside any action is recorded as `other`, and OpenAI embedding calls are recorded as `embedding`.

#### Scenario: Truncated turn
- **WHEN** an ingest turn stops at `max_tokens`
- **THEN** a failed row is recorded with the tokens the provider reported

#### Scenario: Request that never reached the provider
- **WHEN** a request fails before the provider answers
- **THEN** a failed row is recorded with zero tokens

#### Scenario: Recording failure
- **WHEN** writing the usage row fails
- **THEN** the model call's own result is unaffected

### Requirement: Usage report
The system SHALL serve an admin-only `GET /api/ai-usage?days=N`, with `days` from 1 to 366 and default 30, returning the totals (calls, failed calls, and input, cached, output and total tokens), tokens per UTC day, the same token counts per action and per model, the ten runs or drafts that used the most tokens, and this month's budget.

#### Scenario: Out-of-range window
- **WHEN** an admin requests `GET /api/ai-usage?days=400`
- **THEN** the request is rejected as invalid

#### Scenario: Non-admin
- **WHEN** a reader requests `GET /api/ai-usage`
- **THEN** the request is refused with 403

### Requirement: Monthly AI budget
The system SHALL support an `ai_budget` settings section with `monthly_limit_tokens` (default 0, meaning no budget), `warn_percent` (1 to 100, default 80) and `pause_background` (default false), count tokens per UTC calendar month, and report `warning` once usage reaches `warn_percent` and `paused` once usage reaches 100% with pausing on.

#### Scenario: Budget banner
- **WHEN** the monthly limit is 20,000,000 tokens and 17,000,000 have been used this month
- **THEN** `GET /api/ai-usage/budget` returns `percent` 85 and `warning` true to an admin
- **AND** returns `null` to a non-admin

#### Scenario: No budget
- **WHEN** `monthly_limit_tokens` is 0
- **THEN** `GET /api/ai-usage/budget` returns `null`

## REMOVED Requirements

### Requirement: Built-in model defaults
**Reason**: An action no longer falls back to a model nobody chose; see "No built-in models".
**Migration**: The upgrade saves each former default explicitly for the actions that relied on it.

### Requirement: Cost estimates from list prices
**Reason**: Mycelium keeps no prices; usage is counted in tokens ("Usage counted in tokens").
**Migration**: Historic `cost_usd` values stay in the ledger unread; spend is on each provider's billing dashboard.
