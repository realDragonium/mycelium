# Internal draft review

Mycelium can review submitted drafts with Claude or an OpenAI GPT model.
Review starts on submission from MCP or the web app. It works for
all drafts; PR provenance is optional. While review is on, `ingest` (over MCP,
HTTP, and the web app) submits its drafts itself; with review off those drafts
stay open for curation. Alias
suggestions from ingestion go to a separate draft that awaits individual human
decisions and is not sent to the reviewer.

Enabling the feature does not sweep the existing backlog. An administrator can
list it with `GET /api/draft-review/backlog` and review it once with
`POST /api/draft-review/backlog`; see [Inspecting and rerunning](#inspecting-and-rerunning).
In the web app, **Settings → Draft review** offers **Review N waiting drafts**
whenever review is on and the backlog is not empty.
A curator can explicitly review an existing submitted draft.

## Configuration

Administrators configure review in **Settings → Draft review**, also linked
from Drafts. It configures this action independently of
Ask, Ingest, and Documentation. Choose the mode, provider, model ID, and independent reviewer
account, then save. Changes take effect for new submissions and explicit reruns
without restarting the server. The form can create a stored writer service
account if none exists. Saving settings does not start any reviews.

Credentials remain in the server environment. The form reports missing setup and
the separate application gate; it does not test model access or expose API keys.
Saving `off` is possible with an empty model or reviewer and no credentials.
Enabled modes require those prerequisites. Model IDs must support the selected
provider's structured outputs; account access is established only by a real run.

Fresh instances start with reviews and reviewed application off. The mode
(`off`, `review-only` or `review-and-apply`), provider, model and reviewer
account all come from saved settings; no environment variable changes them.
The shared model settings remember a separate Claude and OpenAI model ID; see
[AI model configuration](AI_MODELS.md).

The server environment supplies only credentials: `OPENAI_API_KEY` for OpenAI,
and the Anthropic SDK's credential configuration (including `ANTHROPIC_API_KEY`,
tokens and profiles) for Claude.

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
again** to assess it under the new configuration. Turning the mode or application permission off and back
on does not restore an old run's authority. The reviewer remains subject to
current account status and permissions before automatic changes.

Review controls and shared per-action model settings live in dedicated tables in
`mycelium-prompts.db`, separate from editable
prompt texts and from drafts. They survive draft cleanup and backup/restore.
Conflicting admin saves return a conflict and require reloading. Unreadable saved
settings disable review instead of reviving environment defaults. The settings
form reports the error and allows an administrator to save an explicit repair;
saving off does not depend on credentials or a valid reviewer. Backup refuses
to omit unreadable instance settings; restore validates the required settings
section before replacing an existing instance. Older archives without settings receive built-in defaults with automation off. Restore never imports the target environment.

## Evidence and scope

Before submission, the draft creator can call:

```text
set_draft_review_evidence(draft_id, evidence, expected_revision)
```

Supply source excerpts, a concrete change description, or facts supporting the
proposal, up to 30,000 characters. Evidence changes increment the draft revision.
To back a single operation, the creator calls:

```text
set_operation_evidence(draft_id, operation_ref, evidence, expected_revision)
```

`operation_ref` is in the receipt of the queued write and in `get_draft`.
Each of up to five items has a `kind` (`code`, `ui`, `doc` or `other`), a
location (a repository-relative `path` with optional `lines` such as `40-52`
and `commit`, or a `url`), an `excerpt` of at most 1,500 characters and a
one-line `claim` of at most 200 saying what it shows. An empty list removes
the operation's evidence. The reviewer sees it on the operation. A link whose
type and direction a concrete code excerpt supports can be accepted on that
basis; a link without evidence is kept only when the statement texts plainly
support it. The Drafts screen shows each operation's evidence.

PR source metadata remains available through `attach_draft_source`, but a PR URL,
commit hash, or workflow run ID does not supply the source contents. Attaching
metadata or either kind of evidence after a review starts makes that assessment stale; request
an explicit rerun after the draft is ready.

The reviewer trusts the producer on what the product does and judges how the
draft fits the existing knowledge: duplicates, contradictions, link type and
direction, missing links to live neighbours, and entity variants or worse
descriptions. It receives draft operations, supplied evidence, affected
knowledge, the link type glossary, and the five closest live statements to each
new or changed statement, added best matches first until the context is full.
It makes one fresh structured-output model call, with no author conversation and
no external investigation tools. Bounds are 30 affected knowledge records, 90,000
context characters, 6,000 output tokens, and a 90-second HTTP timeout. Two workers
process accepted runs, sharing the existing model-loop capacity with other tasks.
A submission burst waits for those workers; duplicate requests for the same draft
return its current run. No repository checkout or GitHub access is required.

Affected knowledge is what the operations reference by id, the entities named in
their text, and the entities they upsert. Statements that mention an affected
entity are included only for operations that remap existing mentions:
`merge_entities`, `move_name`, `rename_name`, `delete_name`, and `delete_entity`.

Internal review supports entity, statement, name, and graph-link mutations whose
records the existing inspection contract fingerprints. Drafts containing other
operations, including glossary or link-alias edits, are rejected without a model
call. The model cannot append or revise those uninspected mutation families.

In `review-and-apply` a draft waits for a person only when the reviewer asks
one. A new statement that contradicts a live one wins: the reviewer corrects the
live statement and lists the contradiction. Failed knowledge reads, oversized
context, API errors, refusals, and incomplete or invalid model output are
explicit failed attempts and never authorize application. A failed attempt that
recorded no review is run once more; if that fails too, the draft is rejected,
unless the failure came from the model provider, which leaves the draft
submitted.

A sweep retries submitted drafts whose latest attempt failed without recording a
review: provider failures, an unusable reviewer account, and attempts
interrupted by a restart. It runs every minute while review is on and starts a
retry 5 minutes after the failure, doubling the wait each time, at most 5
retries per draft (about two and a half hours). Each retry is a fresh attempt
with the usual single rerun. A curator's **Run again** or a backlog review
starts the count over. Drafts with no attempt at all are left for the backlog
review, and so are failures older than the whole retry schedule (about two
hours and forty minutes), such as those in a restored copy of another
instance or from before a long outage: the sweep does not review, and possibly
apply, them unasked.

An attempt stopped by the monthly AI budget (see [AI models](AI_MODELS.md)) is
`paused`, not failed: it uses no retry, is not rerun, and is not in the backlog.
The sweep resumes it once the budget allows, after a budget change or when the
month rolls over, with the attempt and retry counts it had.

When the supplied knowledge cannot settle how the draft fits and a person's
answer would, such as whether a new concept is the same as a live one, the
reviewer answers `needs_context` with specific questions. With the application
gate enabled, the run records an authoritative `needs_context` review carrying
the questions, ends with outcome `needs_human`, files a knowledge gap naming the
draft and the questions, and leaves the draft submitted. A curator answers with
`POST /api/drafts/{id}/review/answer` and the draft is reviewed again with the
answer. In the web app the questions and an answer form sit at the top of the
draft; such drafts sort first under Drafts and are counted on Home. The reviewer gets no new tools for this.

Every automatic rejection, every contradiction resolved in an applied draft, and
every question for a person is filed as a knowledge gap naming the draft, so a
person can find it on the Gaps page. Only the question holds its draft back.
The gap records the draft id, and the contradicted statement's id, as
references as well as in its text. When the reviewer applies a draft it
resolves that draft's open gaps, so an answered question closes once its
draft lands. Contradiction gaps are filed after the application and stay open
for a person to check. A draft approved by hand resolves its gaps the same way.
An automated assessment remains a model judgment; isolated tests verify the
execution safeguards and API contract, not the model's factual accuracy.

## Inspecting and rerunning

An identified curator can call `request_draft_review(draft_id)` over HTTP to start review
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

- Status (`running`, `completed`, `failed`, `paused`), assessed revision, and
  staleness.
- Selected provider/model, reviewer ID, and control/model settings revisions. Historical attempts
  retain unknown metadata; a selected model does not imply a provider was called.
- Label (`good`, `changes_suggested`, `reject`, `needs_context`), rationale,
  questions, concrete suggested corrections, resolved contradictions, and the
  attempt number (2 for the automatic rerun after a failure).
- Application outcome (`unapplied`, `applied`, `rejected`, `needs_human`) and
  explanatory detail.
- The sweep retry count, and curators' recorded answers to earlier questions.
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

`POST /api/drafts/{id}/review/answer` takes `run_id`, the attempt whose
questions are answered, and `answer`, up to 6,000 characters. It requires a
real curator role and is refused unless that attempt is the draft's latest, has
outcome `needs_human`, and the draft has not changed since. The answer is stored
on the review attempt with the curator's ID and carried to every later attempt
of the draft, where the reviewer receives it as `answers_from_curators`, apart
from the creator-supplied evidence. It returns `{review: ...}` for the new
attempt.

Admin-only `GET /api/draft-review/backlog` returns `{draft_ids: [...]}`: submitted
drafts the current configuration has not reached. That is a draft with no
attempt, a failed attempt that recorded no review, an advisory assessment
made under another mode, any unapplied assessment in `review-and-apply` (for
example one held by the application gate), or a question whose draft has
changed since it was asked. Drafts containing only alias suggestions are excluded.
`POST /api/draft-review/backlog` starts a review of each and returns their IDs.
The list is available while review is off; starting the reviews is refused.

In `review-only`, an advisory `reject` label leaves the draft submitted. Suggested corrections are
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
interrupted runs become failed and the sweep retries them; already committed
application or rejection receipts restore the actual outcome instead of
reporting it unapplied. A run that recorded its review before the interruption is
not retried.
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

## Upgrading from pre-settings versions

Before AI settings existed, review was configured with environment variables.
The first start of a version with saved settings imports them once; after that
they have no effect, and fresh and restored instances never read them:

| Variable | Imported into |
| --- | --- |
| `MYCELIUM_DRAFT_REVIEW_MODE` | The mode: `off`, `review-only` or `review-and-apply`. |
| `MYCELIUM_DRAFT_REVIEW_USER_ID` | The reviewer account. |
| `MYCELIUM_REVIEWED_APPLY` | **Allow applying accepted reviews** (`1`, `true`, `yes` or `on`). |
| `MYCELIUM_DRAFT_REVIEW_PROVIDER`, `MYCELIUM_DRAFT_REVIEW_MODEL`, `MYCELIUM_DRAFT_REVIEW_CLAUDE_MODEL`, `MYCELIUM_DRAFT_REVIEW_OPENAI_MODEL` | The draft-review model; see [AI model configuration](AI_MODELS.md#upgrading-from-pre-settings-versions). |
