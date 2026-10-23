# Documentation models

Open **Documents** in the web app to create a document, read saved documents,
inspect revision history, or publish an update to GitHub. **Settings →
Documentation** edits writing profiles and configures the default profile and
repository destinations; the generation model is under **Settings → Models**
and its limits under **Settings → Limits**. These settings persist in
the instance and do not require editing files or redeploying.

Each generation form can choose Claude or GPT independently of the saved default.
The configured model handles retrieval, writing, and a separate review conversation.
Credentials stay on the server: Anthropic uses its existing SDK credentials;
OpenAI uses `OPENAI_API_KEY`. Model IDs and provider defaults are saved through
the settings UI. The provider list reports local configuration, not a live check
of model access, quota, or compatibility. Failures never silently switch providers.

A new UI generation creates a document. Naming the concept it is about, with a
writing profile and template, gives it a stable identity: a later request for
the same concept, profile and template revises that document instead of
creating another (`anchor_entity_id` over MCP).

Publishing opens or updates a GitHub pull request, and the document shows
whether it is open, merged or closed. Mycelium asks GitHub when the document is
opened, at most once a minute, and keeps the last known state when GitHub
cannot be reached.

 To improve an existing one, open it from
**Documents** and describe the change under **Create revision**. This targets the
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

Open a document, select its destination, and choose **Create / update GitHub PR**.
Publication is explicit. Failures leave the internal document saved and can be
retried without another AI run. Later updates preserve the recorded repository,
branch, credential binding and path, even if its destination settings change.
A binding removed from the deployment must be restored before publishing there.

The document shows which revision was published and whether a newer internal
revision awaits publication. A publication completing during a concurrent local
edit still records the exact revision sent. Existing remote-change checks remain
in place. Merging and deployment happen in GitHub; Mycelium does not perform them.

### Storage and automation

Documents, immutable revisions, generation runs, and publication receipts live
in `mycelium-drafts.db`. Instance exports include those tables in
`documentation.json`, alongside prompt history and configuration. Unrelated draft
operations and credentials are excluded. Older installations receive a snapshot
of their current document body; overwritten bodies cannot be reconstructed.
Legacy publication timestamps remain unknown rather than inferred from edit times.
Archives predating document backups contain no document library to restore.

REST exposes `request_documentation`, `list_generated_documents`,
`get_generated_document`, `list_document_revisions`, `get_document_revision`,
`revise_document`, and `deliver_document`. MCP exposes `request_documentation`,
`get_documentation_run`, `get_generated_document`, and `revise_document`. Publishing
stays in the UI; see [the MCP tool manifest](MCP_TOOLS.md).
`revise_document` requires `document_id`, `expected_revision`, and instructions.
The UI always supplies the current revision when publishing. With
`request_documentation`'s default `match_existing=True`, a request that looks
like an update to an existing document writes nothing. Its run names that
document in `matched_document_id` and `error`, and the caller decides whether
to revise it. The model never chooses which document is overwritten. The UI
creation endpoint disables matching.

Readers can inspect documents and runs. Generation and publication require a real
writer or admin role. Writing profiles describe an audience, not access controls.

GPT uses the OpenAI Responses API with `store: false`. The adapter preserves
response items, encrypted reasoning, and function-call IDs across tool results.
It requests one tool call per turn and retains the loop's forced-tool choices.
Schemas keep their existing optional fields with `strict: false`; the existing
tool dispatch and document/review parsers validate arguments. Incomplete,
malformed, parallel-call and HTTP error responses cannot bypass the gates.
The fresh review conversation receives the candidate document and review rules,
not the writer's conversation history.

Existing tool-operation, turn, wall-clock and request-timeout limits apply. The
Anthropic retry setting remains specific to the Claude SDK; the GPT transport
does not retry HTTP requests automatically. The loop retains its bounded final
attempt when a model call fails. GPT trace cost is null because a Claude price
estimate would be misleading; token usage is still recorded.

Transport and workflow tests use local fake Responses payloads and isolated
stores. They establish routing and gates, not the prose quality or account
availability of a live model.

[OpenAI function calling documentation](https://developers.openai.com/api/docs/guides/function-calling)
