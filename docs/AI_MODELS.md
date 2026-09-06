# AI model configuration

Administrators configure Mycelium's language-model actions in **AI settings**.
Open Settings in the cockpit or the existing UI. Each action has its own default
provider and model:

- Ask: answer questions from existing knowledge.
- Ingest: extract proposed knowledge changes from supplied material.
- Research: investigate knowledge gaps and propose changes.
- Documentation: generate and review documents.
- Draft review: assess submitted knowledge drafts.

Choose Claude or OpenAI GPT independently for each action. Each action remembers
one model ID per provider, so switching providers preserves the other model ID.
The documentation generation screen can still override the default provider for
a particular document; it uses that action's configured model for the chosen
provider. Draft review also has its own off/advisory/automatic mode and independent
reviewer account, described in [Draft review](DRAFT_REVIEW.md).

Saving takes effect for new runs without restarting the service. Existing runs
keep their admitted model selection. Changing either the draft-review controls
or its model settings prevents an older review from applying automatically; run
it again to use the new settings. Saving configuration does not start work.

## Server credentials and initial defaults

API credentials stay on the server. OpenAI uses `OPENAI_API_KEY`. Claude uses the
Anthropic SDK's credential discovery, including API keys, tokens, and configured
profiles. The settings screen shows local credential availability; it does not
make a provider request to test a model or establish account access. Provider
errors remain explicit and never cause fallback to a different model.

Existing instances import these legacy environment values once at upgrade, preserving saved values. Fresh instances use built-in defaults. Subsequent environment changes have no effect:

| Action | Provider | Claude model | OpenAI model |
| --- | --- | --- | --- |
| Ask | `MYCELIUM_ASK_PROVIDER` | `MYCELIUM_ASK_MODEL` | `MYCELIUM_ASK_OPENAI_MODEL` |
| Ingest | `MYCELIUM_INGEST_PROVIDER` | `MYCELIUM_INGEST_MODEL` | `MYCELIUM_INGEST_OPENAI_MODEL` |
| Research | `MYCELIUM_RESEARCH_PROVIDER` | `MYCELIUM_RESEARCH_MODEL` | `MYCELIUM_RESEARCH_OPENAI_MODEL` |
| Documentation | `MYCELIUM_DOCGEN_PROVIDER` | `MYCELIUM_DOCGEN_MODEL` | `MYCELIUM_DOCGEN_OPENAI_MODEL` |
| Draft review | `MYCELIUM_DRAFT_REVIEW_PROVIDER` | `MYCELIUM_DRAFT_REVIEW_CLAUDE_MODEL` | `MYCELIUM_DRAFT_REVIEW_OPENAI_MODEL` |

Ask, ingest, research, and documentation retain their existing Claude defaults.
OpenAI model IDs have no implicit default. Draft review retains its OpenAI default
provider and accepts the existing `MYCELIUM_DRAFT_REVIEW_MODEL` as the selected
provider's initial model when its provider-specific variable is absent.

Each action’s provider and both model IDs come entirely from saved settings. Changing environment variables does not override that saved action.
The administrator controls **Allow applying accepted reviews** in AI settings. This separate permission covers manual curator application and automatic application.

## Persistence and API

Privileged configuration uses dedicated tables in `mycelium-prompts.db`, separate
from editable prompt text and disposable draft data. Backup/restore includes
saved models and review controls. Unreadable saved configuration fails closed;
it never silently reactivates environment defaults. The settings screen isolates
an invalid action, reports the configuration error, and presents blank fields
for an administrator to repair with an explicit save. Other actions remain
editable. Database-level failures still require operator repair. Backup refuses to omit
unreadable instance configuration, and restore validates required settings
sections before replacing the target. Older archives without settings receive built-in defaults, with automation off; restore never imports the target environment.

Authenticated `GET /api/model-settings` returns all five actions, their effective
provider, selected model, remembered model IDs, source, and revision. Admin-only
`PATCH /api/model-settings/{action}` accepts `provider`, `claude_model`,
`openai_model`, and the current `revision`. Concurrent or stale saves return 409
and require reloading. Model settings contain no credentials.

Draft review's combined settings endpoint saves its controls and selected model
in one transaction. Its request requires both the control `revision` and
`model_revision`; another administrator's model change cannot be overwritten by
a stale review-settings form.

## Shared execution boundary

The five workflows send tasks and an explicit model configuration through
`mycelium.ai`. `turn(ToolTask, ModelConfig)` provides conversation and tool-call
execution; `structured(StructuredTask[T], ModelConfig)` returns a validated typed
result. Provider adapters handle credentials, wire formats, continuation data,
usage, and safe failures. Workflow code retains evidence collection, tool
permissions, validation, budgets, and domain decisions.

Provider choice is deterministic configuration. A model does not choose its own
provider. Claude and OpenAI conversations retain their provider-specific history
inside the adapter and cannot switch provider halfway through a run. Embeddings
remain a separate Ollama configuration; local NLI classification also retains
its existing model contract. Neither search indexes nor classifier models are
changed by this screen.

## Limits and repository integrations

AI settings also provides independent limits for Ask, Ingest, Research,
Documentation, and Draft review. Output tokens, request timeouts, and retries
apply to each provider request. The four tool loops additionally expose operation
and run time limits and adaptive thinking; Ask exposes its existing cache switch.
Input limits and retrieval widths appear only on the actions that support them.
Draft review is a single structured assessment, so it has no tool-operation or
thinking control. Provider support for adaptive thinking depends on the chosen
model.

The defaults preserve the existing runtime budgets, including Ask's 90-second
run and 75-second request budgets. Quick Ask still applies ceilings of 8
operations, 25 seconds per run, and 20 seconds per request, and disables its
retrieval floor. Smaller saved limits remain effective.

Shared model concurrency and the documentation/research active-run limits are
editable. Lowering shared concurrency lets current work finish and holds new
work until capacity becomes available. Increasing it wakes waiting workers.
There is one shared counting gate; changing its limit does not create a second
pool. Per-action active-run limits count admitted unfinished runs, including
those waiting for shared capacity.

Documentation settings selects the default guideline set and configures named
GitHub destinations using an owner, repository, base branch, and path template.
Path templates support `{slug}`, `{guideline_set}`, and `{document_type}` and
must remain relative to the repository root. Research sources specify a name,
owner, repository, and optional branch/ref. Both lists use structured forms.

Authenticated integrations select a named credential binding. Deployment
configuration defines bindings in `MYCELIUM_GITHUB_CREDENTIALS`, for example:

```json
{"company-github":{"host":"github.com","token_env":"COMPANY_GITHUB_TOKEN"}}
```

The referenced variable contains the token. The UI displays binding names,
hosts, and whether the referenced credential is present; it never accepts token
values or arbitrary environment-variable names. A binding fixes the host to
which its credential can be sent. Public research sources can omit a binding
and supply a validated host. Documentation destinations require a binding.
Changing a token value rotates credentials without changing saved repository
settings.

Existing instances import legacy task budgets, `MYCELIUM_SOURCES`,
`MYCELIUM_DOC_DESTINATIONS`, and `MYCELIUM_DOCGEN_GUIDELINE_SET` once. Their
credential host/reference pairs become stable `imported-` bindings in a separate
registry that the settings API cannot edit. Explicit deployment bindings override
a registry entry with the same name. Fresh and restored instances never import
unrelated legacy environment configuration. Invalid legacy sections are recorded
as disabled without storing their raw text; an administrator must repair that
section. Ports, storage and trace paths, authentication, credentials, and other
deployment configuration remain on the server.

Admitted research jobs capture their source coordinates and AI budgets before
queuing. Documentation jobs capture AI budgets, the guideline preference, and
destination coordinates used to read existing documents. Draft reviews capture
their request limits. Subsequent settings changes affect later admissions.
Delivery records pin their repository, host, and base branch: editing a destination
under the same name cannot redirect an existing document's recorded path or
revision. Use a new destination name when deliberately delivering to a different
repository or branch. Older delivery records are pinned once during upgrade;
a target that cannot be resolved remains disabled.

`GET /api/product-settings` returns typed sections, individual revisions, and
safe binding choices. Admin-only `PATCH /api/product-settings` accepts
`{revision, settings: {kind, ...}}`; stale writes return 409. Each section saves
independently. Backup includes product sections and imported credential
references in `product-settings.json`, validates them before restore, and
refuses to silently omit corrupt saved configuration. Tokens remain outside the
archive.
