# Documentation models

Open **Documentation** in either UI to create a document, read saved documents,
inspect revision history, or publish an update to GitHub. **Profiles & templates**
edits writing guidance; **Models & GitHub** configures the generation model,
limits, default profile, and repository destinations. These settings persist in
the instance and do not require editing files or redeploying.

Each generation form can choose Claude or GPT independently of the saved default.
The configured model handles retrieval, writing, and a separate review conversation.
Credentials stay on the server: Anthropic uses its existing SDK credentials;
OpenAI uses `OPENAI_API_KEY`. Model IDs and provider defaults are saved through
the settings UI. The provider list reports local configuration, not a live check
of model access, quota, or compatibility. Failures never silently switch providers.

A new UI generation creates a document. To improve an existing one, open it from
**Documents** and describe the change under **Create revision**. This targets the
exact internal version on screen, preserving its identity and earlier revisions.
It does not ask the model to select a different document or substitute GitHub's
content. If another run changes the document first, reload its current revision
before retrying. Old revisions remain readable and downloadable as Markdown.

Generation records the model and a consistent snapshot of the available writing
profiles at admission. The selected guidance, exposure rules, template, and their
versions are retained with the run. Changing settings while a run is queued does
not change that run's instructions.

### GitHub publication

Connect GitHub in **Models & GitHub → Documentation delivery** and choose a
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

MCP and REST use the same operations: `request_documentation`,
`list_generated_documents`, `get_generated_document`, `list_document_revisions`,
`get_document_revision`, `revise_document`, and `deliver_document`.
`revise_document` requires `document_id`, `expected_revision`, and instructions.
The UI always supplies the current revision when publishing. Existing automation
may retain automatic document matching through `request_documentation`'s default
`match_existing=True`; the UI creation endpoint disables that matching.

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
