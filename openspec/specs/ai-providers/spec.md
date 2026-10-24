# ai-providers Specification

## Purpose
Configure which language-model provider and model each AI action uses, keep provider credentials on the server, let people edit each action's behavioural instructions, and record, price and budget every model call.

## Requirements

### Requirement: Model-driven actions
The system SHALL configure models for exactly these actions: `ask`, `ingest`, `docgen`, `draft_review`, `alias_discovery`, `audience_labelling`, `documentation_planning` and `connect`, each with its own provider and model independent of the others.

#### Scenario: Listing the actions
- **WHEN** an authenticated caller requests `GET /api/model-settings`
- **THEN** the response lists one entry per action, in that order, each with `action`, `provider`, `model`, `claude_model`, `openai_model`, `claude_reasoning_effort`, `openai_reasoning_effort`, `revision`, `source`, `configuration_error`, `model_warning` and `providers`
- **AND** the top-level `can_configure` is true only for an admin

### Requirement: Provider choice per action
The system SHALL support the providers `claude` and `openai` for every action, remember one model ID and one reasoning effort per provider for each action, and use the model of the selected provider.

#### Scenario: Switching provider keeps the other provider's model
- **WHEN** an admin switches the `ask` action from `claude` to `openai` with `openai_model` `gpt-5.4-mini`
- **THEN** `model` becomes `gpt-5.4-mini`
- **AND** the previously saved `claude_model` is still returned and is used again if the provider is switched back

### Requirement: Built-in model defaults
The system SHALL start a fresh instance with every action on `claude`, using `claude-haiku-4-5` for `ask`, `claude-haiku-5-5` for `audience_labelling` and `claude-sonnet-4-6` for the other Claude actions, except `draft_review`, which starts on `openai` with no model selected; OpenAI model IDs MUST have no implicit default.

#### Scenario: Fresh instance
- **WHEN** a new data directory starts for the first time
- **THEN** `ingest` reports provider `claude` and model `claude-sonnet-4-6`
- **AND** `draft_review` reports provider `openai` with an empty `model`

### Requirement: Saving a model selection
The system SHALL let only an admin save an action's selection through `PATCH /api/model-settings/{action}` with `provider`, `claude_model`, `openai_model`, optional `claude_reasoning_effort` and `openai_reasoning_effort`, and the current `revision`, and SHALL increment the revision on each change.

#### Scenario: Non-admin save
- **WHEN** a writer sends a valid `PATCH /api/model-settings/ingest`
- **THEN** the request is refused with 403 and nothing is saved

#### Scenario: Stale revision
- **WHEN** an admin saves with a `revision` that no longer matches the saved one
- **THEN** the request fails with 409 and asks the caller to reload

#### Scenario: Unchanged save
- **WHEN** an admin saves exactly the values already saved
- **THEN** the revision does not change

### Requirement: Selected provider needs a model
The system MUST refuse a model selection whose selected provider has an empty model ID.

#### Scenario: Missing model for the chosen provider
- **WHEN** an admin saves `provider` `openai` with an empty `openai_model`
- **THEN** the request fails with 400 "Choose a model ID for the selected provider."

### Requirement: Model IDs belong to their provider
The system MUST refuse a model ID that is recognisably the other provider's, and SHALL accept an unrecognised ID with a `model_warning` that its cost cannot be estimated; model IDs are limited to 200 characters.

#### Scenario: Claude ID in the OpenAI field
- **WHEN** an admin saves `openai_model` `claude-sonnet-4-6`
- **THEN** the request fails with 400 naming the ID as a Claude model ID

#### Scenario: Unknown but plausible ID
- **WHEN** an admin saves `claude_model` `claude-workspace-preview-9`, which is not in the price table
- **THEN** the selection is saved
- **AND** the action's `model_warning` says the model is not one this version knows and its cost cannot be estimated

### Requirement: Reasoning effort
The system SHALL accept `none`, `minimal`, `low`, `medium`, `high`, `xhigh` or `max` as OpenAI reasoning effort and `low`, `medium`, `high`, `xhigh` or `max` as Claude reasoning effort, send no effort override when the effort is null ("Model default"), and treat an omitted effort field as keeping the saved value and an explicit `null` as restoring Model default.

#### Scenario: Restoring Model default
- **WHEN** an admin saves the `docgen` action with `"claude_reasoning_effort": null`
- **THEN** the saved Claude effort becomes null and Claude requests for documentation carry no effort setting

#### Scenario: Effort the provider does not offer
- **WHEN** an admin saves `claude_reasoning_effort` `minimal`
- **THEN** the request is rejected as invalid

### Requirement: Settings apply to new work only
The system SHALL apply a saved model selection, limit or instruction to work admitted after the save, without a restart, and SHALL NOT start any work because of a save.

#### Scenario: Run in progress
- **WHEN** an admin changes the `docgen` model while a documentation run is under way
- **THEN** that run keeps the model it was admitted with and the next run uses the new one

### Requirement: No environment model selection
The system SHALL take each action's provider and model only from saved settings; environment variables MUST NOT select or override them, except for a one-time import on the first start of an instance that predates saved settings.

#### Scenario: Fresh instance ignores legacy variables
- **WHEN** a fresh data directory starts with `MYCELIUM_ASK_MODEL` set
- **THEN** the `ask` action uses its built-in default and the variable has no effect

#### Scenario: One-time upgrade import
- **WHEN** an instance that already holds data but has no saved model settings starts with `MYCELIUM_INGEST_PROVIDER=openai` and `MYCELIUM_INGEST_OPENAI_MODEL` set
- **THEN** those values are saved as the `ingest` selection and the import is recorded
- **AND** later changes to those variables have no effect

### Requirement: Unreadable configuration fails closed
The system MUST disable an action whose saved model or product settings cannot be read, rather than falling back to defaults or environment values, and SHALL let an admin repair it with an explicit save while other actions stay editable.

#### Scenario: Corrupt saved selection
- **WHEN** the saved `ask` selection cannot be parsed
- **THEN** `GET /api/model-settings` returns the `ask` entry with blank model fields and a `configuration_error` saying the action is disabled
- **AND** an `ask` call fails instead of using a default model

### Requirement: Credentials stay on the server
The system SHALL read OpenAI credentials only from `OPENAI_API_KEY` and Claude credentials through the Anthropic SDK's own discovery (API key, auth token or configured profile), and MUST NOT store credentials in model settings or accept them through the settings API.

#### Scenario: Availability without a provider request
- **WHEN** `OPENAI_API_KEY` is unset on the server
- **THEN** each action's `providers` list reports `openai` with `available` false and reason "Set OPENAI_API_KEY on the server."
- **AND** no request is made to a provider to determine this

### Requirement: Background work checks credentials first
The system SHALL check that the selected provider's credentials are present before the draft-review sweeper, the audience labeller, automatic document revision or the connect pass collects evidence or calls a model, and SHALL leave their queued work untouched when credentials are missing.

#### Scenario: Labeller without credentials
- **WHEN** automatic audience labelling is on and the labelling action's provider has no credentials
- **THEN** no labelling batch runs and the unlabelled statements stay queued

#### Scenario: Connect pass without credentials
- **WHEN** a caller invokes `connect_statements` while the `connect` action's provider has no credentials
- **THEN** the call fails with the credential reason before any model call

### Requirement: No provider fallback
The system MUST surface a provider failure as an explicit error and MUST NOT retry the work on a different provider or model.

#### Scenario: Rejected request
- **WHEN** Claude answers an `ingest` request with HTTP 400
- **THEN** the run fails with "Claude request failed (HTTP 400)." and guidance to check the model ID, reasoning effort and thinking settings
- **AND** no OpenAI request is made

#### Scenario: Missing OpenAI key at call time
- **WHEN** an action configured for OpenAI runs without `OPENAI_API_KEY`
- **THEN** it fails with "OPENAI_API_KEY is required on the server"

### Requirement: Provider request retries
The system SHALL retry an OpenAI request that fails to connect or returns 408, 409, 429 or a 5xx status up to the action's `max_retries`, and SHALL pass `max_retries` and `request_timeout_s` to the Claude client for each request.

#### Scenario: Rate limited OpenAI request
- **WHEN** an OpenAI request returns 429 and the action allows 2 retries
- **THEN** the request is sent at most three times before failing with guidance to check quota

### Requirement: Conversations stay on one provider
The system SHALL keep a multi-turn model conversation on the provider it started with and MUST refuse to continue it on another provider.

#### Scenario: Provider history from another provider
- **WHEN** a conversation carrying Claude history is sent to OpenAI
- **THEN** the request fails with "Cannot change providers within a model conversation"

### Requirement: OpenAI responses are not stored by the provider
The system SHALL send OpenAI Responses API requests with `store` false.

#### Scenario: Tool turn
- **WHEN** a tool-using action calls an OpenAI model
- **THEN** the request carries `"store": false`

### Requirement: Forced tool calls on models that refuse them
The system SHALL ask for a required tool in the prompt instead of forcing `tool_choice` on `claude-fable-5-1`, `claude-mythos-5-1`, `claude-opus-5-5` and `claude-sonnet-5-5`, SHALL retry once the same way for any other Claude model that refuses a forced tool choice and stop forcing it until the server restarts, and MUST still fail the turn unless the reply is exactly the required call.

#### Scenario: Model that refuses forcing
- **WHEN** an ingest run on `claude-opus-5-5` reaches its final emit
- **THEN** the request uses an automatic tool choice with the emit tool requested in the prompt, with thinking kept on
- **AND** a reply that is not exactly one emit call fails the turn

#### Scenario: Model that refuses thinking while forced
- **WHEN** a Claude model rejects a forced tool choice combined with thinking
- **THEN** the turn is retried once without thinking and that model is forced without thinking until restart

### Requirement: Tool-loop limits
The system SHALL bound each `ask`, `ingest`, `docgen` and `connect` run by saved per-action limits on output tokens, request timeout, retries, operations and whole-run time, defaulting to: `ask` 8,000 tokens, 75 s, 4 retries, 25 operations, 90 s; `ingest` 32,000, 90 s, 4, 50, 300 s; `docgen` 32,000, 120 s, 4, 150, 900 s; `connect` 32,000, 120 s, 4, 60, 300 s.

#### Scenario: Fresh limits
- **WHEN** an authenticated caller reads `GET /api/product-settings` on a fresh instance
- **THEN** the `ingest` section has `max_tokens` 32000, `op_cap` 50 and `wall_clock_s` 300

#### Scenario: Higher effort does not raise limits
- **WHEN** an admin raises an action's reasoning effort to `max`
- **THEN** its token, timeout and run limits are unchanged

### Requirement: Loop-specific options
The system SHALL default `ask` to thinking off and prompt caching on, the other tool loops to thinking on, `ingest` to 20,000 input characters, `docgen` to 2,000 prompt characters, and `connect` to at most 5 statements and $0.50 estimated spend per run.

#### Scenario: Connect batch over the limit
- **WHEN** a caller passes 6 statement IDs to `connect_statements` with credentials configured and the default settings
- **THEN** the call fails with "at most 5 statements per run; got 6"

### Requirement: Single-request limits
The system SHALL bound `draft_review` and `alias_discovery` model requests by saved output tokens, request timeout and retries, defaulting to 6,000 tokens, 90 s and no retries, with alias discovery also limited to 100,000 input characters.

#### Scenario: Fresh review limits
- **WHEN** an authenticated caller reads `GET /api/product-settings` on a fresh instance
- **THEN** the `draft_review` section has `max_tokens` 6000, `request_timeout_s` 90 and `max_retries` 0

### Requirement: Outgrown limit defaults are raised once
The system SHALL, once per instance, raise a saved `ingest` `max_tokens` of 8,000 and a saved `docgen` `max_tokens` of 12,000 to 32,000, and a saved `ingest` `wall_clock_s` of 120 to 300, leaving any other saved value alone.

#### Scenario: Upgrade with the old ingest default
- **WHEN** an instance whose saved `ingest` limits still hold `max_tokens` 8000 starts on this build
- **THEN** the saved value becomes 32000 with a new revision
- **AND** if an admin later saves 8000 again, it is not raised a second time

### Requirement: Product settings API
The system SHALL return every product settings section with its own `revision` from `GET /api/product-settings` to any authenticated caller, and SHALL save one section per admin-only `PATCH /api/product-settings` carrying `{revision, settings: {kind, ...}}`, refusing a stale revision with 409.

#### Scenario: Independent sections
- **WHEN** one admin saves the `ask` section while another saves the `ingest` section
- **THEN** both saves succeed because each section has its own revision

#### Scenario: Unknown field
- **WHEN** an admin saves an `ask` section carrying a field the section does not define
- **THEN** the request is rejected and nothing is saved

### Requirement: Credentials are never saved in settings
The system MUST refuse product settings whose content contains the value of a configured GitHub credential.

#### Scenario: Pasted token
- **WHEN** an admin saves documentation settings in which a field holds the token value of a configured credential binding
- **THEN** the request fails with "Configuration contains a credential. Use credential variable names only."

### Requirement: Shared model concurrency
The system SHALL bound every running model loop or model-backed background job (ask, ingest, `connect_statements`, documentation runs and plans, draft reviews, audience labelling batches and alias discovery) by one shared limit, `concurrency.model_loops` (default 2), whatever transport started it.

#### Scenario: Limit reached
- **WHEN** two `ask` calls are running with the default limit and a third arrives over HTTP or MCP
- **THEN** the third waits for a slot instead of starting

#### Scenario: Lowering the limit
- **WHEN** an admin lowers `model_loops` from 3 to 1 while three loops run
- **THEN** the running loops finish and new work waits until a slot is free under the new limit

#### Scenario: Raising the limit
- **WHEN** an admin raises `model_loops` while work is waiting
- **THEN** waiting work is woken and starts up to the new limit

### Requirement: Usage ledger
The system SHALL record every model call, whether it succeeded or failed, as one row in the `ai_usage` table of `mycelium-drafts.db` with time, action, provider, model, input, cache-read, cache-write and output tokens, estimated cost, duration, success and, when known, the run and draft it served; a call made outside any action is recorded as `other`, and OpenAI embedding calls are recorded as `embedding`.

#### Scenario: Truncated turn
- **WHEN** an ingest turn stops at `max_tokens`
- **THEN** a failed row is recorded with the tokens the provider reported

#### Scenario: Request that never reached the provider
- **WHEN** a request fails before the provider answers
- **THEN** a failed row is recorded with zero tokens

#### Scenario: Recording failure
- **WHEN** writing the usage row fails
- **THEN** the model call's own result is unaffected

### Requirement: Cost estimates from list prices
The system SHALL estimate each call's cost from built-in standard-tier list prices per million tokens, pricing Claude cache writes at 1.25 times the input rate, and SHALL record no cost for a model missing from the price table.

#### Scenario: Unpriced model
- **WHEN** a call is made to a model that is not in the price table
- **THEN** its tokens are recorded with a null cost
- **AND** the usage report counts it in `unpriced_calls`

### Requirement: Usage report
The system SHALL serve an admin-only `GET /api/ai-usage?days=N`, with `days` from 1 to 366 and default 30, returning the totals (calls, failed calls, unpriced calls, tokens, cost), spend per UTC day, per action and per model, the ten most expensive runs or drafts, and this month's budget.

#### Scenario: Out-of-range window
- **WHEN** an admin requests `GET /api/ai-usage?days=400`
- **THEN** the request is rejected as invalid

#### Scenario: Non-admin
- **WHEN** a reader requests `GET /api/ai-usage`
- **THEN** the request is refused with 403

### Requirement: Monthly AI budget
The system SHALL support an `ai_budget` settings section with `monthly_limit_usd` (default 0, meaning no budget), `warn_percent` (1 to 100, default 80) and `pause_background` (default false), count spend per UTC calendar month, and report `warning` once spend reaches `warn_percent` and `paused` once spend reaches 100% with pausing on.

#### Scenario: Budget banner
- **WHEN** the monthly limit is $20 and $17 has been spent this month
- **THEN** `GET /api/ai-usage/budget` returns `percent` 85 and `warning` true to an admin
- **AND** returns `null` to a non-admin

#### Scenario: No budget
- **WHEN** `monthly_limit_usd` is 0
- **THEN** `GET /api/ai-usage/budget` returns `null`

### Requirement: Budget pauses only background actions
The system SHALL, while the budget is paused, refuse model calls from `audience_labelling`, `draft_review` and `connect` before any request is sent, and MUST NOT pause ask, ingest, documentation, documentation planning, alias discovery or embeddings; a budget that cannot be read MUST NOT block any call.

#### Scenario: Paused review run
- **WHEN** a draft review run starts while the budget is paused
- **THEN** the run is saved as `paused` with the budget reason and makes no provider request
- **AND** the review sweep resumes it once the budget allows, without using a retry

#### Scenario: Paused labelling batch
- **WHEN** the audience labeller's batch is refused by the budget
- **THEN** the batch is not recorded as failed and stays due

#### Scenario: Interactive work continues
- **WHEN** the budget is paused and a user calls `ask`
- **THEN** the question is answered normally

### Requirement: Editable AI instructions
The system SHALL keep editable behavioural instructions for `ask`, `ingest`, `docgen`, `document_review`, `draft_review`, `alias_discovery`, `audience_labelling`, `documentation_planning` and `connect`, shared by both providers, readable by every authenticated caller and saveable only by a caller whose real role is writer or admin.

#### Scenario: Listing instructions
- **WHEN** an authenticated caller requests `GET /api/ai-instructions`
- **THEN** the response lists each action with its `title`, whether it is `edited`, and `newer_default_since`, plus `can_write`

#### Scenario: Reader save
- **WHEN** a reader saves new `ask` instructions through `PUT /api/documentation/prompts`
- **THEN** the request is refused with 403

### Requirement: Instruction versions
The system SHALL save instructions as an append-only new version recording its author, refuse a save whose `revision` does not match the current version with 409, refuse empty text, create no version when the text is unchanged, and restore an earlier version as a new version.

#### Scenario: Concurrent edit
- **WHEN** two writers load the `ingest` instructions at version 4 and both save
- **THEN** the first save creates version 5 and the second fails with 409 "This text changed. Reload before saving."

#### Scenario: Restoring a version
- **WHEN** a writer restores version 2 of the `ask` instructions
- **THEN** its text is saved as the next version and earlier versions stay in history

### Requirement: Instruction resolution
The system SHALL use the newest saved version of an action's instructions, otherwise for `ingest` and `docgen` the doctrine file named by `MYCELIUM_INGEST_DOCTRINE_PATH` or `MYCELIUM_DOCGEN_DOCTRINE_PATH` or the packaged file, otherwise the packaged default, and SHALL fall back to the default with a recorded note when the prompt store is unavailable.

#### Scenario: Retired override
- **WHEN** the saved override for `connect` instructions has been retired
- **THEN** runs use the packaged default

### Requirement: Packaged doctrines cannot be retired
The system MUST refuse `retire_prompt_text` for the `ingest` and `docgen` doctrines, and SHALL allow retiring other prompt texts only to a caller whose real role is admin.

#### Scenario: Retiring the ingest doctrine
- **WHEN** an admin calls `retire_prompt_text` with type `doctrine` and name `ingest`
- **THEN** the call fails saying the text is seeded at startup and should be edited in Settings instead

### Requirement: Instruction preview
The system SHALL return, from `POST /api/ai-instructions/{action}/preview` with up to 100,000 characters of `text`, the combined system prompt the action would send, built by the same code as the action, with placeholders for per-request evidence and documentation-profile content.

#### Scenario: Previewing documentation instructions
- **WHEN** a reader previews draft `docgen` instructions
- **THEN** the preview contains the text together with placeholders such as "[Writing guidance from the selected profile]"

### Requirement: Runs record the instructions they used
The system SHALL capture an action's instructions once per run and record a reference with `action`, `version`, `source` (`saved`, `default` or `file`) and a SHA-256 `digest` of the text: in the `prompts` list of ask, ingest and documentation traces, and as `prompt` on draft-review runs and alias scan results.

#### Scenario: Instructions edited mid-run
- **WHEN** a writer saves new `docgen` instructions while a documentation run is under way
- **THEN** that run keeps the version it captured and its trace reference names that version

### Requirement: Shipped defaults follow releases without overriding edits
The system SHALL, on every start, append a release's new default as another `seed` version when the newest version of an action's instructions is authored by `seed`, never change a version a person saved, and report `newer_default_since` (and log a warning) when a person's saved text predates a default first seen on this instance after that save.

#### Scenario: Untouched seeded instructions
- **WHEN** a build with new default `ingest` instructions starts on an instance whose newest `ingest` version is authored by `seed`
- **THEN** the new default becomes the newest version, authored by `seed`

#### Scenario: Edited instructions
- **WHEN** a build with a new `ask` default starts on an instance whose `ask` instructions were saved by a person before that default appeared
- **THEN** the saved text stays in force
- **AND** `GET /api/ai-instructions/ask` reports `newer_default_since` until any version is saved
