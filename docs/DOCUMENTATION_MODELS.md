# Documentation models

Open **Documentation** in the cockpit to request a document and select **Claude**
or **GPT** for that run. Optional guideline set and document type choices select
writing guidance and templates. The model can resolve omitted choices from the
configured catalogue. Readers can inspect runs; starting a run requires a real
writer or admin role.

The selection applies to document matching, knowledge retrieval, writing, and
the separate review conversation. Existing grounding, review and delivery rules
still apply. A completed generation stores a document internally; publishing it
uses the existing explicit delivery workflow.

Configure providers on the server:

| Setting | Meaning |
| --- | --- |
| `MYCELIUM_DOCGEN_PROVIDER` | Default for requests without a provider: `claude` (default) or `openai`. |
| `MYCELIUM_DOCGEN_MODEL` | Claude model ID. Falls back to `MYCELIUM_INGEST_MODEL`, then the existing packaged Claude default. |
| Anthropic credentials | Existing SDK configuration, including `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, profiles and federation. |
| `MYCELIUM_DOCGEN_OPENAI_MODEL` | Required GPT model ID with Responses API function calling support. No implicit model default. |
| `OPENAI_API_KEY` | Required OpenAI API credential. Kept on the server. |

The provider list shows configured model IDs and missing configuration, never
credentials. Availability means local configuration exists; it does not probe
provider access, quota, or model compatibility. Unknown providers and missing
GPT configuration are refused before creating a run. Provider failures never
switch to another model automatically.

`request_documentation(prompt, guideline_set=None, document_type=None,
provider=None)` exposes the same choice through MCP and its REST mirror.
`list_documentation_models()` lists the configured options. The cockpit uses
`GET /api/documentation/options` and `POST /api/documentation/runs`; run lists,
run details and document details are available beneath `/api/documentation`.
Every new run captures its provider and model at admission, including while it
waits for a model slot. Later configuration changes affect later runs. Historical
runs retain null provider/model because their exact model was not recorded.

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
