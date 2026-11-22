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

A document is also out of date when the step links leaving the statements of
a flow it places, or their conditions, changed since the flow was drawn
(`stale.flow_changes`: a step added, a step removed or a condition changed).
The revision is then told to preview the flow and submit it again.

A writer that revises a document is given its current text, its flows with
what they draw, and the ids of the statements it cites. A retry briefed with
the review's notes gets the refused draft and its flows the same way.

Publishing opens or updates a GitHub pull request, and the document shows
whether it is open, merged or closed. Mycelium asks GitHub when the document is
opened, at most once a minute, and keeps the last known state when GitHub
cannot be reached.

To improve an existing document, open it from **Documents** and describe the
change under **Create revision**. This targets the
exact internal version on screen, preserving its identity and earlier revisions.
If another run changes the document first, reload its current revision before
retrying. Old revisions remain readable and downloadable as Markdown.

Publishing to GitHub is one-way. Mycelium's text is the only source: a revision
always starts from the revision here, and nothing is read back from GitHub into
a document. A publish overwrites the file, on the open pull request branch or
in a new pull request from the base branch, including changes someone made to
it on GitHub by hand. To change a published document, change the statements or
ask for a revision, then publish again. The one refusal: a file someone deleted
in the open pull request is not put back; restore it there or close the pull
request.

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

A writer can also mark where a picture would help and none was offered, as
`![what the picture should show](image-wanted)`. It is not media and needs no
id; the description must have at least three words. The page shows it as a
note, and the [website](#download-as-a-website) lists every one in
`images-wanted.html`.

### Concept links and flows

A body is Markdown with two additions, both optional.

- **Concept links.** `[[Invoice]]`, or `[[Invoice|invoices]]` where the
  sentence needs other words, links a concept. The name is matched, ignoring
  case, against the names and aliases of concepts the document's audience may
  see, and the match is stored with the revision. In the document view the
  link opens the profile's document about that concept. A name that matches
  no concept, or more than one, is not refused: it reads as its text, and the
  run's summary lists it (`unmatched_concept_links`).
- **Flows.** A flow shows something that happens in steps. The writer names a
  start statement; the server draws the steps from the stored links, so a
  document cannot show a step or a condition that is not stored. The writer
  sees the drawing first with the `preview_flow` read, submits the flow
  beside the body as `{name, title, start, stop}`, and places it with a
  fenced block whose info string is `flow` and whose only content is the
  name:

  ````markdown
  ```flow
  export-request-to-download
  ```
  ````

What a flow draws from each link:

| Link | Drawn as |
|---|---|
| `proceeds`, `next` | the next step |
| `contains`, from an event to an event or a procedure to an action | a step that is part of its parent |
| `triggers` | a step that starts a separate process |
| `on-success`, `on-failure` | a branch named so |
| `fallback-to` | an alternative, "otherwise" |
| `establishes` | a result at the side of its step |

A condition is written on its arrow in words. A statement reached twice is
drawn once and the later arrow joins it, which also ends a loop. The walk does
not continue past a `stop` statement. A drawing holds at most 12 steps and 4
side outcomes per step, and the walk visits at most 60 statements; where a
limit cuts it short, the flow says it continues and `preview_flow` reports
`truncated`, so the writer can pick a later start or add a stop.

One refusal names every problem with a submission's flows: a placement naming
no submitted flow, a flow never placed, a name that is not lowercase letters,
digits and hyphens or is used twice, a `start` or `stop` that does not exist
or the audience may not see, and a drawing of fewer than three statements.

The drawing is stored with the revision and its statements are cited with the
ones the writer listed. The reviewer is told what each placed flow shows. A
revising writer submits `flows` again; what it submits replaces the stored
set.

A document about one concept starts from a brief that also lists where flows
start among the concept's statements, its related and more specific concepts,
the concepts most often named with it, and the pages the profile already has
about those, so the writer links to a page instead of repeating it.

The [developer reference](profile-examples/developer-reference.md) example
profile writes one such page per concept.

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

A document whose body holds a concept link or a flow placement is not
delivered to GitHub: only Mycelium renders them. Read it in Mycelium or as a
[website](#download-as-a-website).

The document shows which revision was published and whether a newer internal
revision awaits publication. A publication completing during a concurrent
revision still records the exact revision sent. Merging and deployment happen
in GitHub; Mycelium does not perform them.

### Download as a website

A writing profile's current documents can be written as a static site: a home
page, one page per document, links between concepts, flows and search. It
loads nothing from elsewhere and opens from `file://`.

- **In the web app:** an administrator opens the profile under **Settings →
  Documentation** and chooses **Download as a website**, with an optional
  site name and feedback address. The zip is built on request and not kept.
- **Over HTTP:** `GET /api/documentation/sites/<profile>?title=…&feedback_url=…`
  returns the same zip. Real admins only, because the site holds everything
  the profile's audience may see, whoever asks. A refusal answers 400 with
  the reason.
- **On the machine holding the data directory:**

  ```bash
  mycelium docs-site --profile developer-reference --out site \
    --title "Product reference" \
    --feedback-url "mailto:docs@example.com?subject={title}"
  ```

  `--out` must be missing or empty, so no page of an earlier export is left
  behind. The command reads the databases as they are and prints what the
  export revealed.

What is written:

| File | Holds |
|---|---|
| `index.html` | The written pages as a tree under their parent concepts, each with the first sentence of its lead, then the pages not written yet |
| `<template>/<slug>.html` | One page per document: breadcrumb, title, "Also called", lead, contents list, the concept's direct relations (at most 12), sections, cited statements folded as sources, and when the revision was written |
| `concept/<slug>.html` | A generated page for each concept a page links to that has no written page: names, description, relations, the statements naming it and the pages linking to it, marked as not written yet |
| `media/` | The images the pages place |
| `search-index.js`, `site.js`, `site.css` | Search over titles, other names, headings and text, run in the browser; the script and the stylesheet |
| `images-wanted.html` | Every image placeholder with its page, section and description |
| `site-report.html` | Linked concepts without a written page, images wanted, documents left out and why, flows a limit cut short, and concept links that matched no concept |

Every page carries the same tree as a sidebar and a search box. Concept names
are linked without the writer marking them: the names and aliases of concepts
named by the statements a page cites, once in the lead and once per section,
never inside code, headings, links or flows.

The feedback address must start with `http:`, `https:` or `mailto:`. It puts a
"Report a problem with this page" link on every page; `{title}` and `{page}`
are replaced, URL-encoded, by the page's title and its path within the site.

Everything is read through the audience the profile writes for. A document is
left out, and named in the report, when it cites a statement, draws a flow
statement or places media that audience can no longer see. An external
audience, which may not see concept relations, gets a flat home page and no
relations on its pages. No site is written when the profile does not exist,
its audience was retired, or a document's template name or slug is not a safe
file name.

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
