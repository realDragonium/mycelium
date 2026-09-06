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

Before an action is first saved, its existing environment defaults apply:

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

After an action is saved, its provider and both model IDs come entirely from saved
settings. Changing environment variables does not override that saved action.
The separate `MYCELIUM_REVIEWED_APPLY` gate remains server-controlled.

## Persistence and API

Privileged configuration uses dedicated tables in `mycelium-prompts.db`, separate
from editable prompt text and disposable draft data. Backup/restore includes
saved models and review controls. Unreadable saved configuration fails closed;
it never silently reactivates environment defaults. The settings screen isolates
an invalid action, reports the configuration error, and presents blank fields
for an administrator to repair with an explicit save. Other actions remain
editable. Database-level failures still require operator repair. Backup refuses to omit
unreadable instance configuration, and restore validates required settings
sections before replacing the target. Older archives without settings retain
legacy environment defaults.

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
