# Documentation models

Open **Documents** in the web app to create a document, read saved documents,
inspect revision history, or publish an update to GitHub. **Settings →
Documentation** edits writing profiles and configures the default profile and
repository destinations; the generation model is under **Settings → Models**
and its limits under **Settings → Limits**. These settings persist in
the instance and do not require editing files or redeploying.

Each generation form can choose Claude or GPT independently of the saved default.
The configured model handles retrieval, writing, and a separate review conversation.
Credentials stay on the server process's environment: `ANTHROPIC_API_KEY` (or
another Anthropic SDK credential) for Claude, `OPENAI_API_KEY` for GPT. Model
IDs and provider defaults are saved through the settings UI. The provider list reports local configuration, not a live check
of model access, quota, or compatibility. Failures never silently switch providers.

A document takes several minutes and many model turns. Claude runs cache the
system prompt, tools and conversation between turns, so each turn pays full
price only for what it added. Every run records a summary: what it is doing
while it runs, then turns, duration, input, cached and output tokens, the
statements it retrieved and cited and the gaps it filed. The workspace shows it on the run and in
the generation history. Set `MYCELIUM_DOCGEN_TRACE_LOG` to a file path to also
append one JSON line per run with its turns, tool calls and per-turn usage,
keyed by the run id.

A run writes for its profile's audience and reads only what that audience
may see; see [Audiences](AUDIENCES.md). To decide which documents a profile
needs, see [Documentation planning](DOCUMENTATION_PLANNING.md).

A document about a concept starts from that concept: before the first writing
turn the run reads the concept's names and the statements that mention it and
hands them to the writer as already retrieved.

A new generation creates a document. Naming the concept it is about, with a
writing profile and template, gives it a stable identity: a later request for
the same concept, profile and template revises that document instead of
creating another (`anchor_entity_id` over MCP). The form says which will
happen before you submit, and links the document a request would revise. The
model never decides which document a request updates.
Merging concepts moves the identity to the surviving concept. If that concept
already has a document for the same profile and template, it keeps that
identity, and the merged-away concept's document stays as an ordinary document
without one. Deleting a concept leaves its documents as ordinary documents.
Both report how many documents lost their identity (`documents_unanchored`).
A generation still running when its concept is merged or deleted writes under
the identity the concept's document would have by then.

Each revision remembers the text of the statements it cites as they were when
it was reviewed. When one of them is later edited, deleted or merged into
another, or relabelled so the document's audience may no longer see it, the document is marked **Out of date** in the library, and the
document shows what changed, old wording beside new. **Revise** starts a
revision briefed with exactly those changes; once it is saved, the document is
current again. Revisions saved before this was recorded show no status.

Publishing opens or updates a GitHub pull request, and the document shows
whether it is open, merged or closed. Mycelium asks GitHub when the document is
opened, at most once a minute, and keeps the last known state when GitHub
cannot be reached.

To improve an existing document, open it from **Documents** and describe the
change under **Create revision**. This targets the
exact internal version on screen, preserving its identity and earlier revisions.
If another run changes the document first, reload its current revision before
retrying. Old revisions remain readable and downloadable as Markdown.

A published document can be edited on GitHub, on its pull request branch or on
the base branch after merge. A revision therefore reads the published copy
first. Mycelium recognises every text it published itself. Any other text there
is someone's edit, and the revision starts from it, telling the writer to keep
it. The run records this as `revision_base: destination`. If the document also
has a revision here that was never published, Mycelium refuses rather than
merging the two. To keep the GitHub edits, choose **Start from the published
copy on GitHub** (`start_from_destination` over MCP): the revision starts from
the GitHub text and the unpublished revision stays in the history. To continue
from the revision here instead, undo the GitHub edits or close the pull request
without merging. A deleted file in an open pull request
is refused the same way. If the published copy cannot be read, the revision is
refused until the connection or credential binding is restored. A manual edit
does not read GitHub, so publishing it is refused over GitHub edits it did not
see.

Generation records the model and a consistent snapshot of the available writing
profiles at admission. The selected guidance, exposure rules, template, and their
versions are retained with the run. Changing settings while a run is queued does
not change that run's instructions.

### Images

A run is offered the screenshots and recordings attached to what it reads that
its audience may see, and places them as `![alt text](media:<id>)`. The
reviewer checks each image's alt text, relevance and exposure, and a template
may mark image slots. A document is out of date when an image it places was
replaced, deleted or relabelled away from its audience. See
[Media](MEDIA.md#in-documents).

### Keeping documents up to date

Each writing profile has a maintenance policy, set in its editor under
**Settings → Documentation**:

- `manual` (the default): an out-of-date document waits for someone to revise
  it, or for the profile's [AI plan reviewer](DOCUMENTATION_PLANNING.md#reviewing-by-ai).
- `propose`: the document gets an update item in the profile's plan, briefed
  with the changed statements ([Documentation planning](DOCUMENTATION_PLANNING.md)).
- `auto-revise`: Mycelium starts the revision itself. It goes through the
  same review as any run. A document that was published is then published
  again to the same destination: that updates its open pull request, or opens a
  new one, and a person still merges it on GitHub. A document never published
  stays internal, unless the profile delivers automatically
  ([Delivery](#delivery)).

Automatic revisions wait until the document's changed statements have been
quiet for a while, so a burst of edits causes one revision, and each profile
starts at most so many per day. Both are under **Settings → Limits →
Documentation maintenance** (30 minutes and 5 by default). Neither policy acts
while an edited statement waits for its new audience label, or for a curator
to [confirm](AUDIENCES.md#confirming-external-grants) its grant to the
document's audience: until then the edit would read as the statement being
hidden from the audience. A background sweep
checks every minute and keeps its decisions in `mycelium-drafts.db`, so a
restart neither repeats nor forgets them: each out-of-date revision is acted
on once. A revision the review refused, a run that failed, or one a restart
cut off before its run was admitted is reported rather than retried; the document stays out of date for
someone to revise. A profile that retries failed AI work retries each of these
within bounded attempts first ([When AI work fails](DOCUMENTATION_PLANNING.md#when-ai-work-fails)). Dismissing the document in the plan also stops automatic
revision until its next revision.

A profile also has a planning policy, beside its maintenance policy, for
statements its audience may see that none of its documents cites
([Uncovered statements](DOCUMENTATION_PLANNING.md#uncovered-statements)):

- `off` (the default, also for profiles saved before this existed): someone
  plans from **Documents → Plan**.
- `propose`: the same sweep plans by itself once enough uncovered statements
  were offered to no plan; the items wait for approval.
- `write`: as `propose`, and the sweep then approves the automatic plan's
  items itself, within the batch and active-run limits. Each run goes through
  the same review as any run.

**Documents → Updates** lists what this did: documents revised automatically,
with what changed and the new revision's diff against the one it replaced, and
those waiting on someone (a proposal to approve, a pull request to merge, a
document still out of date). The Documents badge counts entries new since you
last opened Updates in this browser, plus those waiting.

### GitHub publication

Connect GitHub in **Settings → Documentation → Documentation delivery** and choose a
repository and base branch. Then save the documentation delivery settings.
See [GitHub App setup](GITHUB_APP.md) for one-time operator configuration,
reconnection, and access requirements.

Alternatively, add a destination using existing server credentials: name,
repository owner and name, base branch, path template, and approved credential
binding. Use `{slug}` in the path template, for example `docs/{slug}.md`.
Server administrators provide bindings through `MYCELIUM_GITHUB_CREDENTIALS`;
no credential values are stored by the browser.

A writing profile can name the destinations its documents publish to
(**Publish only to** in its editor; only an administrator changes it on an
existing profile). Its documents can then be published only there, by
people, agents and automatic revisions alike, and the document offers only
those; a profile that names none publishes anywhere, as profiles saved
before the setting existed do. This keeps an internal guide out of a public
help site's repository. A destination's path template can lay profiles out
side by side with `{guideline_set}`, for example `docs/{guideline_set}/{slug}.md`.

Open a document, select its destination, and choose **Create / update GitHub PR**.
Publication is explicit unless the profile delivers automatically ([Delivery](#delivery)). Failures leave the internal document saved and can be
retried without another AI run. Later updates preserve the recorded repository,
branch, credential binding and path, even if its destination settings change.
A binding removed from the deployment must be restored before publishing there.

Images the document places are committed beside the Markdown, as
`<file stem>-media/<id>-v<version>.<ext>`, and linked by that relative path; a
replaced image gets a new file name, so its document changes too. Publishing
refuses a document placing media that was deleted or that its audience may no
longer see.

The document shows which revision was published and whether a newer internal
revision awaits publication. A publication completing during a concurrent local
edit still records the exact revision sent. Existing remote-change checks remain
in place. Merging and deployment happen in GitHub; Mycelium does not perform them.

### Storage and automation

Documents, immutable revisions, generation runs, publication receipts, plans and
maintenance decisions live in `mycelium-drafts.db`. Instance exports carry those
tables in their own archive member, `documentation.json`, beside the drafts,
prompt history and configuration the rest of the archive holds. Older installations receive a snapshot
of their current document body; overwritten bodies cannot be reconstructed.
Legacy publication timestamps remain unknown rather than inferred from edit times.
Archives predating document backups contain no document library to restore.

REST exposes `request_documentation`, `list_generated_documents`,
`get_generated_document`, `list_document_revisions`, `get_document_revision`,
`revise_document`, and `deliver_document`. MCP exposes `request_documentation`,
`get_documentation_run`, `get_generated_document`, `revise_document`,
`request_documentation_plan`, `get_documentation_plan` and `deliver_document`; see
[the MCP tool manifest](MCP_TOOLS.md).

#### Delivery

A writing profile's **Who delivers documents** setting (its editor under
**Settings → Documentation**) is `people` by default, also for profiles saved
before it existed:

- `people`: people publish from the document in the web app.
- `agents`: also writer and admin agents, with `deliver_document` (over MCP or
  `POST /deliver-document`), which is refused under `people`. It opens or
  updates the pull request as **Create / update GitHub PR** does.
- `auto`: also the maintenance sweep, which publishes every revision of the
  profile that passed review, while it is still its document's current one:
  plan-item documents, requests, retries and automatic revisions alike. A
  document published before goes to its recorded destination; one never
  published goes to the profile's **Repository for documents not published
  before**, or stays internal when none is chosen. A publication that fails is
  shown on the run, and retried when the profile retries failed AI work.

People publish from the document whatever the setting. Merging stays with the
destination repository; the document follows the pull request's state as
before. Revisions finished before an upgrade to this version are not
published by it.
`revise_document` requires `document_id`, `expected_revision`, and either
instructions or `update_sources=true`, which briefs the run with the cited
statements that changed (`stale.changes` on `get_generated_document` and
`list_generated_documents`). The UI always supplies the current revision when
publishing. `request_documentation` without an anchor always creates a
document; to change one, revise it.

Readers can inspect documents and runs. Generation and publication require a real
writer or admin role. Writing profiles describe an audience, not access controls.

GPT uses the OpenAI Responses API with `store: false`. The adapter preserves
response items, encrypted reasoning, and function-call IDs across tool results.
It requests one tool call per turn and retains the loop's forced-tool choices.
Schemas keep their existing optional fields with `strict: false`; the existing
tool dispatch and document/review parsers validate arguments. Incomplete,
malformed, parallel-call and HTTP error responses cannot bypass the gates.
The fresh review conversation receives the candidate document and review rules,
not the writer's conversation history. Of the cited statements it sees only id,
kind and text, not who changed them or when. It judges exposure on the
document's title and body, and does not fail conformance for a section, table
column or field the writer left out or marked unverified because no cited
statement supports it; the templates tell the writer to do that and file a
knowledge gap.

A run the review refused shows the failed findings, grouped by check. A writer
can start **Retry with these notes**: a new run with the same request, profile,
type and concept (or a revision of the same document), whose writer is briefed
with the findings. The notes go to the writer only; the next review reads the
unchanged request, so a mistaken finding cannot become a requirement. The new
run lists the notes it was briefed with (`review_notes`).

Existing tool-operation, turn, wall-clock and request-timeout limits apply. The
Anthropic retry setting remains specific to the Claude SDK; the GPT transport
does not retry HTTP requests automatically. The loop retains its bounded final
attempt when a model call fails. Token usage is recorded as for Claude.

Transport and workflow tests use local fake Responses payloads and isolated
stores. They establish routing and gates, not the prose quality or account
availability of a live model.

[OpenAI function calling documentation](https://developers.openai.com/api/docs/guides/function-calling)
