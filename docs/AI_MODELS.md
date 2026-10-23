# AI model configuration

Administrators configure Mycelium's language-model actions in **Settings → Models**
(see [the web app](WEB_APP.md)). Each action has its own default provider and
model:

- Ask: answer questions from existing knowledge.
- Ingest: extract proposed knowledge changes from supplied material.
- Documentation: generate and review documents.
- Draft review: assess submitted knowledge drafts.
- Alias discovery: propose alternative names from selected existing statements.
- Audience labelling: decide which documentation audiences may see each statement ([Audiences](AUDIENCES.md)).
- Documentation planning: propose which documents a writing profile's audience needs ([Documentation planning](DOCUMENTATION_PLANNING.md)).
- Connecting statements: propose links and concept mentions for statements nothing reaches ([Knowledge health](KNOWLEDGE_HEALTH.md)).

Choose Claude or OpenAI GPT independently for each action. Each action remembers
one model ID and reasoning effort per provider, so switching providers preserves the other provider’s settings.
The documentation generation screen can still override the default provider for
a particular document; it uses that action's configured model and effort for the chosen
provider. Draft review also has its own off/advisory/automatic mode and independent
reviewer account, described in [Draft review](DRAFT_REVIEW.md).

Alias discovery has independent model, reasoning effort, token, timeout, retry, and input-size settings. Ingestion proposes aliases within its existing run using the ingestion model. All alias suggestions require an individual human decision; the draft review automation mode cannot accept, reject, or alter them. See [Alias suggestions](ALIAS_SUGGESTIONS.md).

Saving takes effect for new runs without restarting the service. Existing runs
keep their admitted model selection. Changing either the draft-review controls
or its model settings prevents an older review from applying automatically; run
it again to use the new settings. Saving configuration does not start work.

## Reasoning effort

Choose **Reasoning effort** alongside each action’s model, including Draft review
(**Settings → Draft review**). **Model default** sends no effort override
and preserves existing behavior. OpenAI **None** is different: it explicitly
requests no reasoning, on models that support it.

OpenAI accepts `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max` through
`reasoning.effort`. Claude uses `low`, `medium`, `high`, `xhigh`, or `max` through
`output_config.effort`. These are provider options, not a guarantee that every
model accepts every level. Check the selected model’s
[OpenAI](https://developers.openai.com/api/docs/guides/reasoning) or
[Claude](https://platform.claude.com/docs/en/build-with-claude/effort) documentation.
An unsupported combination fails explicitly without changing models or effort.

Claude’s existing extended-thinking toggle remains separate: effort controls
response work even without thinking blocks. Forced final tool calls retain the
existing thinking policy and still receive the configured effort. Claude Fable
5.1, Mythos 5.1, Opus 5.5 and Sonnet 5.5 refuse a forced tool choice, so on
those models a turn that needs a tool asks for it in the prompt instead, keeps
thinking, and still fails unless the reply is exactly that one call. Any other
model that answers a forced tool choice with that refusal is retried once the
same way and is not forced again until the server restarts. Increasing
effort does not raise token, timeout, or whole-run limits automatically.

Effort is captured when work starts and included in saved draft-review attempts
and documentation runs. Existing settings and backups without effort use Model
default; changing an environment variable does not configure effort.

## Server credentials and initial defaults

API credentials stay on the server. OpenAI uses `OPENAI_API_KEY`. Claude uses the
Anthropic SDK's credential discovery, including API keys, tokens, and configured
profiles. The settings screen shows local credential availability; it does not
make a provider request to test a model or establish account access. Provider
errors remain explicit and never cause fallback to a different model.

Background AI work checks credentials before it collects evidence or calls a
model. Without them, the review sweeper, the audience labeller and automatic
document revision leave their queues untouched, and admins see one banner
naming each waiting worker instead of a stream of failed runs.

A model ID must belong to its provider: saving an OpenAI ID in a Claude field,
or the reverse, is refused. IDs this version does not know are accepted with a
warning, since their cost cannot be estimated.

A fresh instance starts every action on Claude with its built-in Claude model,
except Draft review, which starts on OpenAI with no model selected. OpenAI model
IDs have no implicit default. Each action’s provider and both model IDs come
entirely from saved settings; no environment variable selects or overrides them.
Instances that predate saved settings imported their environment once; see
[Upgrading from pre-settings versions](#upgrading-from-pre-settings-versions).
The administrator controls **Allow applying accepted reviews** in **Settings → Draft review**. This separate permission covers manual curator application and automatic application.

## Persistence and API

Privileged configuration uses dedicated tables in `mycelium-prompts.db`, separate
from editable prompt text and from draft data. Backup/restore includes
saved models and review controls. Unreadable saved configuration fails closed;
it never silently reactivates environment defaults. The settings screen isolates
an invalid action, reports the configuration error, and presents blank fields
for an administrator to repair with an explicit save. Other actions remain
editable. Database-level failures still require operator repair. Backup refuses to omit
unreadable instance configuration, and restore validates required settings
sections before replacing the target. Older archives without settings receive built-in defaults, with automation off; restore never imports the target environment.

Authenticated `GET /api/model-settings` returns every action, their effective
provider, selected model, remembered model IDs, source, and revision. Admin-only
`PATCH /api/model-settings/{action}` accepts `provider`, `claude_model`,
`openai_model`, optional `claude_reasoning_effort` and `openai_reasoning_effort`, and the current `revision`. Omitted effort fields preserve saved values; explicit `null` restores Model default. Concurrent or stale saves return 409
and require reloading. Model settings contain no credentials.

Draft review's combined settings endpoint saves its controls and selected model
in one transaction. It accepts `reasoning_effort` for the selected provider, with the same omission/null behavior. Its request requires both the control `revision` and
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
remain a separate Ollama configuration, and search indexes are not changed by
this screen.

## AI usage and budget

`mycelium.ai` meters every `turn` and `structured` call, so no action needs its
own accounting. Each call becomes one row in the `ai_usage` table of
`mycelium-drafts.db`: time, action, provider, model, input, cache-read,
cache-write and output tokens, estimated cost, duration, success, and the run
and draft it served when there is one (documentation runs, documentation plans
and draft review runs). A call is attributed by the action around it with
`ai.usage.attributed(action, run_id=..., draft_id=...)`; a call made outside
any attribution is still recorded, as `other`. Truncated turns and turns
rejected after the provider answered (a missing required tool call, an
incomplete OpenAI response) are recorded with the tokens they used; a request
that failed before the provider answered is recorded with none. The ledger
is archived with drafts in backups: it is small, and restoring without it
would reset the month's spend and the budget with it.

Costs are estimates from the list prices in `mycelium.ai.pricing` (Claude and
OpenAI, standard tier, base context). They leave out long-context surcharges,
batch or priority tiers and attempts the SDK retried after a timeout. A model
without a list price records tokens but no cost, and the usage page says how
many such calls a total leaves out.

**Settings → AI usage** shows admins the totals, spend per UTC day, per action
and per model, and the most expensive recent runs, linked. `GET
/api/ai-usage?days=N` (admin, 1–366, default 30) returns the same report with
the budget; `GET /api/ai-usage/budget` returns this month's budget state to
admins and `null` to everyone else.

The optional monthly budget is the `ai_budget` product settings section:
`monthly_limit_usd` (0 means none), `warn_percent` (default 80) and
`pause_background` (default off). Spend is counted per UTC calendar month.
Past the warning percentage, admins see a banner. With pausing on, at 100% the
background actions (audience labelling, draft review and the connect pass,
which attributes its calls as `connect`) are refused before a request is sent,
until the month ends or the budget is raised. A refused labelling batch stays
due; a refused review run is paused with the reason and resumed by the review
sweep once the budget allows, without using a retry. Ask, ingest, documentation, planning and alias
discovery are never paused.

## Limits and repository integrations

**Settings → Limits** provides independent limits for Ask, Ingest, Documentation,
and Draft review. Output tokens, request timeouts, and retries
apply to each provider request. The three tool loops additionally expose operation
and run time limits and adaptive thinking; Ask exposes its existing cache switch.
Input limits and retrieval widths appear only on the actions that support them.
Draft review is a single structured assessment, so it has no tool-operation or
thinking control. Provider support for adaptive thinking depends on the chosen
model.

The defaults preserve the existing runtime budgets, including Ask's 90-second
run and 75-second request budgets. Quick Ask still applies ceilings of 8
operations, 25 seconds per run, and 20 seconds per request, and disables its
retrieval floor. Smaller saved limits remain effective. Ingest allows 32,000
output tokens per request, thinking included, because a full draft outgrew the
earlier 8,000; an instance whose saved Ingest limit was still 8,000 is raised
once on upgrade. Documentation allows 32,000 for the same reason: a document
body with adaptive thinking outgrew 12,000 and fell back to the forced final
attempt, so a saved 12,000 is raised once too.

Shared model concurrency and the documentation active-run limit are
editable. Lowering shared concurrency lets current work finish and holds new
work until capacity becomes available. Increasing it wakes waiting workers.
There is one shared counting gate; changing its limit does not create a second
pool. The active-run limit counts admitted unfinished runs, including
those waiting for shared capacity.

Documentation settings selects the default guideline set and configures named
GitHub destinations using an owner, repository, base branch, and path template.
Path templates support `{slug}`, `{guideline_set}`, and `{document_type}` and
must remain relative to the repository root.

Authenticated integrations select a named credential binding. Deployment
configuration defines bindings in `MYCELIUM_GITHUB_CREDENTIALS`, for example:

```json
{"company-github":{"host":"github.com","token_env":"COMPANY_GITHUB_TOKEN"}}
```

The referenced variable contains the token. The UI displays binding names,
hosts, and whether the referenced credential is present; it never accepts token
values or arbitrary environment-variable names. A binding fixes the host to
which its credential can be sent. Documentation destinations require a binding,
or a [GitHub App connection](GITHUB_APP.md) to the same repository.
Changing a token value rotates credentials without changing saved repository
settings.

Ports, storage and trace paths, authentication, credentials, and other
deployment configuration remain on the server.

Documentation jobs capture AI budgets, the guideline preference, and
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

## Upgrading from pre-settings versions

Before AI settings existed, these actions were configured with environment
variables. The first start of a version with saved settings imports them once,
into saved settings, and records that the import happened. After that they have
no effect, and fresh and restored instances never read them. They are listed
here only so an operator upgrading an old instance knows what carried over.

| Action | Provider | Claude model | OpenAI model |
| --- | --- | --- | --- |
| Ask | `MYCELIUM_ASK_PROVIDER` | `MYCELIUM_ASK_MODEL` | `MYCELIUM_ASK_OPENAI_MODEL` |
| Ingest | `MYCELIUM_INGEST_PROVIDER` | `MYCELIUM_INGEST_MODEL` | `MYCELIUM_INGEST_OPENAI_MODEL` |
| Documentation | `MYCELIUM_DOCGEN_PROVIDER` | `MYCELIUM_DOCGEN_MODEL` | `MYCELIUM_DOCGEN_OPENAI_MODEL` |
| Draft review | `MYCELIUM_DRAFT_REVIEW_PROVIDER` | `MYCELIUM_DRAFT_REVIEW_CLAUDE_MODEL` | `MYCELIUM_DRAFT_REVIEW_OPENAI_MODEL` |

Documentation falls back to `MYCELIUM_INGEST_MODEL` for its Claude model. Draft review takes `MYCELIUM_DRAFT_REVIEW_MODEL` as the selected
provider's model when the provider-specific variable is absent. Its mode,
reviewer and application permission are covered in
[Draft review](DRAFT_REVIEW.md#upgrading-from-pre-settings-versions).

The same import reads:

- task budgets as `MYCELIUM_<ACTION>_<FIELD>`, for example
  `MYCELIUM_ASK_WALL_CLOCK_S` or `MYCELIUM_INGEST_OP_CAP`;
- `MYCELIUM_MODEL_LOOP_MAX_CONCURRENT` and `MYCELIUM_DOCGEN_MAX_ACTIVE` for the
  concurrency limits;
- `MYCELIUM_DOC_DESTINATIONS` for documentation destinations, and
  `MYCELIUM_DOCGEN_GUIDELINE_SET`.

Credential host/reference pairs from destinations become stable
`imported-` bindings in a separate registry that the settings API cannot edit.
Explicit deployment bindings override a registry entry with the same name.
Invalid legacy sections are recorded as disabled without storing their raw
text; an administrator must repair that section.
