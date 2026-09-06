# Internal draft review

Mycelium can review submitted drafts with Claude or an OpenAI GPT model.
Review starts on submission from MCP or either browser interface. It works for
all drafts; PR provenance is optional. Enabling the feature does not sweep the
existing backlog. A curator can explicitly review an existing submitted draft.

## Configuration

Administrators can open **AI settings** from cockpit Drafts or the existing
Settings screen. The draft-review card configures this action independently of
Ask, Ingest, Research, and Documentation. Choose the mode, provider, model ID, and independent reviewer
account, then save. Changes take effect for new submissions and explicit reruns
without restarting the server. The form can create a stored writer service
account if none exists. Saving settings does not start any reviews.

Credentials remain in the server environment. The form reports missing setup and
the separate application gate; it does not test model access or expose API keys.
Saving `off` is possible with an empty model or reviewer and no credentials.
Enabled modes require those prerequisites. Model IDs must support the selected
provider's structured outputs; account access is established only by a real run.

Until the first save, these environment values supply the defaults. After that,
saved review controls and model selections take precedence over their environment defaults.
The shared model settings remember a separate Claude and OpenAI model ID; see
[AI model configuration](AI_MODELS.md).

| Variable | Meaning |
| --- | --- |
| `MYCELIUM_DRAFT_REVIEW_MODE` | `off` (default), `review-only`, or `review-and-apply`. |
| `MYCELIUM_DRAFT_REVIEW_PROVIDER` | `openai` (default) or `claude`. |
| `MYCELIUM_DRAFT_REVIEW_MODEL` | Model ID supporting structured outputs for the selected provider. No model is silently selected. |
| `OPENAI_API_KEY` | OpenAI API key supplied to the server process. |
| Anthropic credentials | Claude uses the Anthropic SDK credential configuration, including `ANTHROPIC_API_KEY`, tokens, and profiles. |
| `MYCELIUM_DRAFT_REVIEW_USER_ID` | Required ID of an active stored Mycelium writer/admin, independent of the draft creator. |
| `MYCELIUM_REVIEWED_APPLY` | Existing application gate; defaults off. Set `on` to permit automatic changes in `review-and-apply`. |

Use an existing service user with the required role. The synthetic `local-admin`
identity and a drafter account do not qualify, even when authentication is off.
The internal worker resolves its own principal; it does not inherit the
submitting user's identity or session. Existing role checks still govern every
correction and application, including operations that require admin privileges.

`review-only` persists an advisory assessment. It never edits operations, creates
an applyable review, or finalizes rejection. `review-and-apply` can make up to eight
small corrections and record an authoritative review, reject the draft, or apply
it through `apply_reviewed_draft`. The separate application gate must be enabled
before any automatic operation edits or final decisions occur.

Each run captures its mode, provider, model, reviewer account, and configuration
revision when admitted, including runs waiting for a worker. Any saved settings
change prevents an older active run from automatically editing, rejecting, or
applying a draft. That run can finish with an advisory assessment; use **Run
again** to assess it under the new configuration. Turning the mode off and back
on does not restore an old run's authority. The reviewer remains subject to
current account status and permissions before automatic changes.

Review controls and shared per-action model settings live in dedicated tables in
`mycelium-prompts.db`, separate from editable
prompt texts and disposable drafts. They survive draft cleanup and backup/restore.
Conflicting admin saves return a conflict and require reloading. Unreadable saved
settings disable review instead of reviving environment defaults. The settings
form reports the error and allows an administrator to save an explicit repair;
saving off does not depend on credentials or a valid reviewer. Backup refuses
to omit unreadable instance settings; restore validates the required settings
section before replacing an existing instance. Older archives without settings
continue to use environment defaults.

## Evidence and scope

Before submission, the draft creator can call:

```text
set_draft_review_evidence(draft_id, evidence, expected_revision)
```

Supply source excerpts, a concrete change description, or facts supporting the
proposal, up to 30,000 characters. Evidence changes increment the draft revision.
PR source metadata remains available through `attach_draft_source`, but a PR URL,
commit hash, or workflow run ID does not supply the source contents. Attaching
metadata or evidence after a review starts makes that assessment stale; request
an explicit rerun after the draft is ready.

The reviewer receives draft operations, supplied evidence, affected knowledge,
and up to 12 related statements found using existing semantic search. It makes
one fresh structured-output model call, with no author conversation and no
external investigation tools. Bounds are 30 affected knowledge records, 90,000
context characters, 6,000 output tokens, and a 90-second HTTP timeout. Two workers
process accepted runs, sharing the existing model-loop capacity with other tasks.
A submission burst waits for those workers; duplicate requests for the same draft
return its current run. No repository checkout or GitHub access is required.

Internal review supports entity, statement, name, and graph-link mutations whose
records the existing inspection contract fingerprints. Drafts containing other
operations, including glossary or link-alias edits, receive `needs_context` with
a request for manual review; no model call or automatic decision is made for
them. The model cannot append or revise those uninspected mutation families.

Missing facts should produce `needs_context` with concrete questions. Failed
knowledge reads, oversized context, API errors, refusals, and incomplete or invalid
model output remain explicit failed attempts. They do not authorize application.
An automated assessment remains a model judgment; isolated tests verify the
execution safeguards and API contract, not the model's factual accuracy.

## Inspecting and rerunning

An identified curator can call `request_draft_review(draft_id)` to start review
or retrieve the latest attempt. Pass `rerun=true` to start a new attempt after
completion or failure. Requests while the mode is off are refused. A concurrent
request returns the active attempt, even with `rerun=true`.

Both browser draft detail views provide **Run review** and **Run again** for
submitted drafts. The control shows when review is off or already running and
requires a real writer/admin role. Each click starts a fresh review with the
current server configuration. After changing from `review-only` to
`review-and-apply`, **Run again** can review and apply the draft; the old advisory
result does not itself authorize application.

`get_draft_review_run(run_id)` retrieves an attempt. `get_draft`, draft lists, and
both browser interfaces expose the latest `review_assessment`, including:

- Status (`running`, `completed`, `failed`), assessed revision, and staleness.
- Selected provider/model, reviewer ID, and control/model settings revisions. Historical attempts
  retain unknown metadata; a selected model does not imply a provider was called.
- Label (`good`, `changes_suggested`, `reject`, `needs_context`), rationale,
  questions, and concrete suggested corrections.
- Application outcome (`unapplied`, `applied`, `rejected`) and explanatory detail.
- The authoritative `review_id`, when automatic mode records one.

The HTTP tool mirrors are `POST /request-draft-review` and
`POST /get-draft-review-run`, with the same named arguments as JSON fields.
Submission from `POST /api/drafts/{id}/submit` also starts review.
The browser bridge uses authenticated `GET /api/draft-review/settings` for
effective configuration, readiness, and caller permissions. Admin-only
`PATCH /api/draft-review/settings` accepts `mode`, `provider`, `model`,
`reviewer_id`, the current control `revision`, and `model_revision`; a conflicting
revision returns 409. The selected model and review controls save atomically.
`POST /api/drafts/{id}/review` with no body starts an
explicit rerun. The latter returns `{review: ...}` and enforces the current
server mode and the caller's real curator role.

An advisory `reject` label leaves the draft submitted. Suggested corrections are
validated without execution before they are published. Draft edits make the old
assessment visibly stale in lists and details. Existing curator controls remain
available for human decisions.

## Exact review and recovery

A run binds the submitted revision at request time. Before automatic action it
checks that the draft, supplied evidence, affected knowledge, and retrieved
supporting knowledge still match. Small corrections execute together in one draft
transaction using existing revision-checked correction APIs. A correction that
introduces uninspected knowledge is refused and the batch rolls back.

The authoritative review records both operation-derived preconditions and any
additional supporting entity and statement fingerprints, including records whose
original operation was removed by a correction. Recording and applying a review
require every operation-derived precondition; callers cannot omit them by adding
supporting records. Later manual/recoverable application also rechecks supporting
knowledge, preserving the same gate as immediate automatic application.

The review run links to its authoritative review before applying. On restart,
interrupted runs become failed and retryable; already committed application or
rejection receipts restore the actual outcome instead of reporting it unapplied.
When a reviewed application still needs finalization, inspect its durable receipt
and use the existing `apply_reviewed_draft(draft_id, review_id)` recovery path.
No startup recovery launches model work or replays an uncommitted application.

OpenAI uses the [Responses structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs)
with `store=false`. Claude uses the Anthropic SDK's
[structured-output parser](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
Both validate the same assessment schema and decision rules, reject incomplete or
invalid output, and never fall back to another provider. The wire contracts are
tested with isolated fake responses; live provider access and factual judgment
have not been validated by those tests.
