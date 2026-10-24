# Internal draft review

Mycelium can review submitted drafts with Claude, an OpenAI GPT model or an
external agent (see [External agent](#external-agent)).
Review starts on submission from MCP or the web app. It works for
all drafts; PR provenance is optional. While review is on, `ingest` (over MCP,
HTTP, and the web app) submits its drafts itself; with review off those drafts
stay open for curation. Alias
suggestions from ingestion go to a separate draft that awaits individual
decisions: a person's, or the reviewer's while **Reviewer decides alias
suggestions** is on (see [Alias decisions](#alias-decisions)).

Enabling the feature does not sweep the existing backlog. An administrator can
list it with `GET /api/draft-review/backlog` and review it, oldest first, with
`POST /api/draft-review/backlog`; see [Inspecting and rerunning](#inspecting-and-rerunning).
In the web app, **Settings → Draft review** offers **Review N waiting drafts**,
with the tokens it is likely to use and an optional token limit, whenever review is on
and the backlog is not empty, and shows the review's progress with **Pause**
and **Resume**.
A curator can explicitly review an existing submitted draft.

## Configuration

Administrators configure review in **Settings → Draft review**, also linked
from Drafts. It configures this action independently of
Ask, Ingest, and Documentation. Choose the mode, where it runs (**Claude**,
**OpenAI** or **External agent**), model (from the
[model catalog](AI_MODELS.md#model-catalog)), reasoning
effort (empty uses the model's default), independent reviewer account, and
whether **Allow applying accepted reviews** (`application_enabled`) is on, then
save. Changes take effect for new submissions and explicit reruns
without restarting the server. The form can create a stored writer service
account if none exists. Saving settings does not start any reviews.

Credentials remain in the server environment. The form reports missing setup and
the separate application gate; it does not test model access or expose API keys.
Saving `off` is possible with an empty model or reviewer and no credentials.
Enabled modes require those prerequisites. Model IDs must support the selected
provider's structured outputs; account access is established only by a real run.

Fresh instances start with reviews and reviewed application off. The mode
(`off`, `review-only` or `review-and-apply`), provider, model, reasoning effort,
reviewer account and application gate all come from saved settings; no environment variable changes them.
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
an applyable review, or finalizes rejection. `review-and-apply` can record an
authoritative review, reject the draft, or apply it through
`apply_reviewed_draft`. The separate application gate, **Allow applying
accepted reviews** (`application_enabled`), must be enabled before any automatic
operation edits, questions or final decisions occur; it also governs a curator's
`apply_reviewed_draft`, but not **Approve**.

**Reviewer decides alias suggestions** (`alias_decisions`, off by default)
lets the reviewer decide alias suggestions; see
[Alias decisions](#alias-decisions).

**Apply automatically** decides what `review-and-apply` lands unattended.
**Only clean approvals** (`clean`, the default) applies a draft only when the
reviewer labels it `good`, which never carries corrections. A draft the
reviewer wants to correct (`changes_suggested`) waits for a curator with its
corrections as a suggestion; see [Held corrections](#held-corrections).
**Approvals with corrections too** (`with_corrections`) also applies those
drafts after making the corrections itself.

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
section before replacing an existing instance. Older archives without settings restore with no model chosen and automation off. Restore never imports the target environment.

### Alias decisions

While **Reviewer decides alias suggestions** is on, a draft holding only alias
suggestions is reviewed on submission and counts in the backlog like any
other, and the reviewer (on a server model or an
[external agent](#external-agent)) returns `alias_decisions`: for each pending
`alias_suggestion` operation, `accept` or `reject`, a `quote` copied from the
suggestion's source text that supports the decision, and a `reason`. Every
pending suggestion needs exactly one decision unless the label is
`needs_context`; a missing, duplicated or foreign decision, or a quote the
source text does not contain, fails the model's attempt or refuses the
agent's submission with findings.

In `review-and-apply`, with the application gate on, the decisions are made
through the suggestion's own accept and reject path, as the reviewer account
(or agent) and never as the draft's creator, and recorded with the quote and
reason. A suggestion whose concept names or source text changed since stays
pending for a person, and the rest of the draft waits with it. A draft of
only suggestions then closes as it does after a person's last decision. In
`review-only`, or with the setting off, the assessment stays advisory and
every suggestion waits for a person.

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
Each of up to five items has a `kind` (`code`, `ui`, `doc`, `media` or
`other`), a location (a repository-relative `path` with optional `lines` such
as `40-52` and `commit`, or a `url`), an `excerpt` of at most 1,500 characters
and a one-line `claim` of at most 200 saying what it shows. A `media` item
names a `media_id` from `create_media_upload` instead of a location; an empty
excerpt is filled with the media's alt text and caption, and applying the
draft attaches the media to what the operation wrote (see [Media](MEDIA.md)). An empty list removes
the operation's evidence. The reviewer sees it on the operation. A link whose
type and direction a concrete code excerpt supports can be accepted on that
basis; a link without evidence is kept only when the statement texts plainly
support it. The Drafts screen shows each operation's evidence.

`attach_draft_source` records the merged pull request the draft documents:
repository, PR number, merge commit, and workflow run id and attempt. The
reviewer sees it as `draft.source` and checks that the draft stays within what
that change is about; a draft without one is judged the same way. The Drafts
screen links the pull request, the merge commit and the workflow run. A PR URL,
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
no external investigation tools. Bounds are 90,000 context characters and, by
default, 6,000 output tokens, a 90-second HTTP timeout and no provider retries
per call; the last three are in **Settings → Product → Draft review**.

A draft too large for one call is reviewed in parts. Its operations are split
into connected parts: operations that change the same record, refer to each
other's new statements with `@` references, or name an entity another
operation creates belong together. Each part gets its own call, with its
operations, their affected knowledge and nearest live statements, and a short
summary of the other parts. A single connected part too large for the context
is refused with a reason. Every part must agree for anything to land: a part
that rejects rejects the draft with that part's rationale, a part with a
question makes the draft wait with it, and each part's corrections are
applied together with the others'. The draft keeps one assessment, whose
`parts` lists each part's label, rationale, questions, corrections,
contradictions and operations; the Drafts screen shows them under **Reviewed in N parts**.

Before any call the reviewer estimates the tokens the review could use from
each part's context size and the output bound, and refuses a draft that could
use more than **Settings → Limits → Draft review → Most tokens to review one
draft** (300,000 by default, 0 for no cap), naming the estimate and asking for
smaller drafts.

A draft that would overwrite a record changed after the draft was created, or
one that no longer exists, is refused without a call, so an old draft never
lands over newer knowledge.
A record counts as changed when a direct edit or another applied draft
created after this one wrote it; an operation that leaves the record as it is
does not count. Of two pending drafts on the same record, whichever applies
first makes the other one refused when it is older. Two workers
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
call. The model cannot append or change those uninspected mutation families.

In `review-and-apply` a draft waits for a person only when the reviewer asks
one, or, under **Only clean approvals**, suggests corrections. Of a new statement and a live one that contradict each other, the newer
wins: the draft, unless the live statement changed after the draft was
created. The reviewer corrects the live statement and lists the
contradiction, or, when the live one is newer, drops, edits or strikes the
draft's conflicting part. Failed knowledge reads, oversized
context, API errors, refusals, and incomplete or invalid model output are
explicit failed attempts and never authorize application. In
`review-and-apply` with the application gate on, a failed attempt that recorded
no review is run once more; if that fails too, the draft is rejected, unless
the failure came from the model provider, which leaves the draft submitted. In
`review-only` or with the gate off, a failed attempt is not rerun; only the
sweep below retries it.

A sweep retries submitted drafts whose latest attempt failed without recording a
review, such as provider failures, an unusable reviewer account, and attempts
interrupted by a restart. It runs every minute while review is on and starts a
retry 5 minutes after the failure, doubling the wait each time, at most 5
retries per draft (about two and a half hours). Each retry is a fresh attempt
with the usual single rerun where that applies. A curator's **Run again** or a backlog review
starts the count over. Drafts with no attempt at all are left for the backlog
review, and so are failures older than the whole retry schedule (about two
hours and forty minutes), such as those in a restored copy of another
instance or from before a long outage: the sweep does not review, and possibly
apply, them unasked.

Earlier versions paused an attempt when the monthly AI budget was spent.
Mycelium has no budget any more (see [AI models](AI_MODELS.md#ai-usage)), so
the sweep resumes such a `paused` attempt with the attempt and retry counts it
had; it is not in the backlog meanwhile.

When the supplied knowledge cannot settle how the draft fits and a person's
answer would, such as whether a new concept is the same as a live one, the
reviewer answers `needs_context` with specific questions. With the application
gate enabled, the run records an authoritative `needs_context` review carrying
the questions, ends with outcome `needs_human`, files a knowledge gap naming the
draft and the questions, and leaves the draft submitted. A curator answers with
`POST /api/drafts/{id}/review/answer` and the draft is reviewed again with the
answer. A curation agent working in the product's code can answer instead,
through the curation queue's `question` items, with the evidence it checked
([Knowledge health](KNOWLEDGE_HEALTH.md#kinds-of-work)); the draft is reviewed
again the same way, and the reviewer gets the agent's evidence with the
answer. In the web app the questions and an answer form sit at the top of the
draft; such drafts sort first under Drafts and are counted on Home. The reviewer gets no new tools for this.

## Corrections

A correction changes exactly one thing, and everything it does not name stays
as submitted. Up to twelve per review, each with a reason:

- `edit`: a statement's new `text` or `kind` (by its `statement` index in an
  `upsert_statements` batch, or the whole `upsert_statement`,
  `patch_statement` or `replace_text` operation; `replace_text` takes only
  `text`), or an `upsert_entity`'s new `description`.
- `add_link` and `drop_link`: one link, named by `from_id`, `link_type`,
  `to_id` and, to choose between links that differ only by condition, its
  `when` tree. In a batch one end must be the batch's own statement, written
  `@N`; the link goes on that statement. In `add_links` and `remove_links` it
  is one entry of the list.
- `drop_statement`: one statement of a batch. Later statements move up and
  every `@N` and `@S:N` reference, conditions included, follows them. A
  statement another operation still names cannot be dropped.
- `strike`: a whole operation. A draft whose corrections strike every
  operation is refused; that draft is a reject.
- `append`: a new operation, written as a tool call.

Indices and `@` references always name the draft as submitted, before any
correction. The result is checked against the submitted draft: a correction
set that would change, renumber or drop a statement, link or operation it does
not name is refused, as is one that would leave an unresolved reference.
Corrections recorded before this form (`revise`, which replaced a whole
operation) stay readable but are no longer made or applied.

## Held corrections

Under **Only clean approvals**, with the application gate on, a
`changes_suggested` review ends with outcome `held` and changes nothing: no corrections, no authoritative review, no gap.
The draft stays submitted, sorts first under Drafts with the questions, and
its page shows each correction with a checkbox and, for edits, its new text,
kind or description in an editable field. **Apply N corrections and approve**
makes the ticked corrections, as edited, and approves the draft as the
curator. **Approve and apply** approves it as submitted instead.

`POST /api/drafts/{id}/review/accept` takes `run_id` and optionally
`corrections`, the list to make instead of the reviewer's. It needs a real
curator role and is refused unless that run is the draft's latest, is `held`,
and the draft has not changed since. The corrections are validated like the
reviewer's, made in one transaction, and the draft is then approved as by
**Approve**; the run ends `applied`. If approval is refused after the
corrections were made, the corrections stay and the response says so.

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

## External agent

With **Runs on** set to **External agent** (`external_agent: true`), no model
reviews drafts and no provider key, model or reviewer account is needed.
Each review run queues a `draft_review` task on the
[agent task queue](AGENT_TASKS.md) instead, and the run shows **Waiting for an
external agent** until an agent with a writer or admin token claims and
submits it. The draft's creator is never given its review.

The brief is built when the task is claimed, from the knowledge as it is then.
`instructions` and `input` are the internal reviewer's system prompt and
context: the draft and its operations, supplied evidence, affected knowledge,
the nearest live statements, the link types, curators' answers and any
earlier failure. A draft reviewed in parts has one context per part in
`input`, each headed `=== PART i OF n ===`, and `parts` says how many.
`earlier_review` holds the draft's previous review, with its suggested
corrections, `mode` and `auto_apply` say what the verdict will do, and
`alias_decisions` whether it decides the draft's alias suggestions. A draft
the server refuses before any review (unsupported operations, newer
knowledge, too large) gets an advisory rejection instead of a brief; a person
decides on it.

The agent submits `{parts: [...]}`, one assessment per part in the internal
reviewer's shape: `good` approves the draft as submitted, `changes_suggested`
approves it with corrections, `reject` rejects it with the rationale, and
`needs_context` asks a person its `questions`. A submission whose labels,
corrections or references fail the internal reviewer's checks is refused with
findings, at most twice before the attempt fails. A valid one is acted on
exactly as the internal reviewer's assessment, with the agent's principal as
the reviewer: the same exact-state checks, **Apply automatically** policy,
application gate, review records and knowledge gaps. In `review-only` it is
advisory and a person decides. A failed attempt is followed up, swept and
retried as a model's is, each time as a new task.

While an external agent reviews, drafts held with corrections are part of the
backlog: **Review N waiting drafts** queues a task for each, so another
reviewer can settle them. Under **Only clean approvals** an agent that
corrects such a draft holds it again; choose **Approvals with corrections
too** to let agents drain them. The backlog job uses no tokens, so the
offer asks for no token limit and shows no estimate. A
run waiting for an agent keeps waiting across a restart. Switching back to a
model and asking for a rerun ends a waiting run.

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

`get_draft_review_run(run_id)` retrieves an attempt. `get_draft` and both browser
interfaces expose the latest `review_assessment`, including the items below.
`GET /api/drafts` lists only each assessment's `run_id`, status, label,
application outcome and staleness, and the `list_drafts` tool none of it.

- Status (`running`, `completed`, `failed`, `paused`), assessed revision, and
  staleness.
- Selected provider/model, reviewer ID, and control/model settings revisions. Historical attempts
  retain unknown metadata; a selected model does not imply a provider was called.
- Label (`good`, `changes_suggested`, `reject`, `needs_context`), rationale,
  questions, concrete suggested corrections, resolved contradictions, and the
  attempt number (2 for the automatic rerun after a failure).
- Application outcome (`unapplied`, `applied`, `rejected`, `needs_human`,
  `held`) and
  explanatory detail.
- The sweep retry count, and curators' recorded answers to earlier questions.
- The authoritative `review_id`, when automatic mode records one.

The HTTP tool mirrors are `POST /request-draft-review` and
`POST /get-draft-review-run`, with the same named arguments as JSON fields.
Submission from `POST /api/drafts/{id}/submit` also starts review.
The browser bridge uses authenticated `GET /api/draft-review/settings` for
effective configuration, readiness, and caller permissions. Admin-only
`PATCH /api/draft-review/settings` accepts `mode`, `auto_apply`,
`application_enabled`, `alias_decisions`, `provider`, `model`, an optional `reasoning_effort`
(omitted keeps the effort saved for that provider), `reviewer_id`, the current
control `revision`, and `model_revision`; a conflicting revision returns 409. The selected model and review controls save atomically.
`POST /api/drafts/{id}/review` with no body starts an
explicit rerun. The latter returns `{review: ...}` and enforces the current
server mode and the caller's real curator role.

`POST /api/drafts/{id}/review/answer` takes `run_id`, the attempt whose
questions are answered, and `answer`, up to 6,000 characters. It requires a
real curator role and is refused unless that attempt is the draft's latest, has
outcome `needs_human`, and the draft has not changed since. The answer is stored
on the review attempt with the curator's ID and carried to every later attempt
of the draft, where the reviewer receives it as `answers_from_curators`, apart
from the creator-supplied evidence. An agent's answer through the curation
queue is stored the same way, with the agent's ID and its `evidence`. It returns `{review: ...}` for the new
attempt.

Admin-only `GET /api/draft-review/backlog` returns `{draft_ids: [...],
external_agent}`: submitted drafts the current configuration has not
reached, and whether an external agent reviews them. That is a draft with no
attempt, a failed attempt that recorded no review, an advisory assessment
made under another mode, any unapplied assessment in `review-and-apply` (for
example one held by the application gate), or a question or held corrections
whose draft has changed since. Drafts containing only alias suggestions are excluded unless the reviewer
decides alias suggestions.
It also returns `job`: the backlog review this process last started, or
`null`.

`POST /api/draft-review/backlog` starts that review and returns `{job}`. It
reviews one draft at a time, oldest first, each draft at most once per job,
until no waiting draft is left; it has no token budget, and each review is
bounded by `max_draft_tokens`. Before each draft it pauses if review can no
longer run, such as when review is switched off or loses its credentials. The
job reports `status` (`running`, `paused`, `finished`), `used_tokens`,
`reviewed`, `remaining` and a `detail` saying why it stopped. `POST /api/draft-review/backlog/pause` stops it after the draft under
review, and `POST /api/draft-review/backlog/resume` continues it. Starting
again while a job is unfinished is refused. The job lives in the server
process: a restart ends it, and starting again picks up the drafts still
waiting. Stale drafts in the backlog are refused as described above. The list
is available while review is off; starting the reviews is refused.

In `review-only`, an advisory `reject` label leaves the draft submitted. Suggested corrections are
validated without execution before they are published. Draft edits make the old
assessment visibly stale in lists and details. Existing curator controls remain
available for human decisions.

## Exact review and recovery

A run binds the submitted revision at request time. Before automatic action it
checks that the draft, supplied evidence, affected knowledge, and retrieved
supporting knowledge still match. Corrections execute together in one draft
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

A curator's **Approve** uses the same receipt. It records an `accepted` review
by that curator ("Approved by hand.") and claims the application in one drafts
transaction, then applies the draft. Unlike a reviewed application, it accepts an
open draft and does not require reviewed application to be enabled. If the
process dies after the substrate commits, approving again finalizes the recorded
result instead of applying the draft twice.

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
