# MCP tool manifest

Every MCP client receives every advertised tool schema before it asks its first
question. Mycelium therefore advertises 42 of its 81 registered tools over MCP. Every
registered tool keeps its HTTP route (`POST /<kebab-name>`, or `GET` when a read
tool takes no arguments) and stays available to the in-process loops (Ask, Ingest,
Documentation) and internal draft review. Removing a tool from MCP removes only
its MCP advertisement.

The list lives in `server.MCP_TOOLS`. `tests/test_mcp_surface.py` keeps this file,
that set, and the registered tools in agreement.

Role filtering still applies: `tools/list` shows a caller only the tools their role
can invoke. An asker sees only `ask`, and a reader sees 19 tools. A drafter sees 39
because their writes are queued on a draft, but they do not see `list_drafts`,
`request_documentation` or `revise_document`. A writer sees 39 and does not see
the admin-only `delete_statement`, `merge_statements` or `merge_entities`. An admin
sees all 42.

A principal scoped to an audience is a reader whatever its role, and sees only
the read tools in `principal_audience.TOOLS`; see
[Scoped users and tokens](AUDIENCES.md#scoped-users-and-tokens).

## Over MCP

MCP covers the read path, statement and entity authoring, drafts, and the
model-backed entry points a client cannot reproduce itself. Approval, reviewed
application and the reviewer's own records stay off MCP: approval is the operator's
decision, and the rest runs in-process.

| Tool | Why it is on MCP |
| --- | --- |
| `search_statements` | Semantic retrieval with alias boost and graph expansion. `decompose` searches each part of a multi-part question and ranks statements several parts surface first. This is the main read. While the embedding provider is down it falls back to keyword matching and marks hits `retrieval: "keyword"`. |
| `get_statements` | Hydrates known ids and follows links. |
| `find_statement_connections` | Finds bounded routes between statements. It cannot be composed cheaply from other reads. |
| `grep_statements` | Literal lookup for identifiers and quoted strings that semantic search misses. |
| `list_statements` | Enumerates statements that mention an entity or have a kind, without a query. |
| `discover_facts` | Checks many candidate texts in one call before writing (`exists` / `near` / `new`). The repository's authoring and draft skills depend on it. |
| `get_entity` | Hydrates an entity's names and entity links. |
| `list_entities` | Pages entities and matches literal prefixes across aliases. |
| `search_entities` | Finds entities by semantic name or alias, or by name substring (`retrieval: "keyword"`) while the embedding provider is down. |
| `list_link_types` | Lists the statement link vocabulary and its direction rules, which writers need. |
| `list_statement_kinds` | Lists the statement kind vocabulary. |
| `list_entity_link_types` | Lists the entity link vocabulary that appears in `get_entity`. |
| `ask` | Runs the server's answer loop. It is the only tool an `asker` sees. |
| `ingest` | Turns prose into a reviewable draft, submitted at once while internal draft review is on. |
| `upsert_entity` | Creates or describes the entity a statement names. |
| `upsert_name` | Adds an alias so mentions resolve. |
| `upsert_statement` | Creates or replaces one statement. Its description holds the statement-kind definitions that the authoring skills refer to. When embedding is unavailable, the response has `embedding_pending: true` and `near_duplicates: []`. |
| `upsert_statements` | Creates one or more statements with links, including cross-references within the batch. A non-empty `embedding_pending` list identifies statements awaiting vectors. |
| `patch_statement` | Edits the text or kind of an existing statement without touching its links. A text edit can return `embedding_pending: true`. |
| `add_links` | Adds statement links. |
| `remove_links` | Removes statement links. |
| `add_entity_links` | Adds structural entity↔entity edges, as the authoring skill instructs. |
| `remove_entity_links` | Removes entity↔entity edges. |
| `merge_statements` | Consolidates a duplicate the caller found. Requires admin. |
| `merge_entities` | The same consolidation for entities. Splitting the two merges across two surfaces would trip agents up. Requires admin. |
| `delete_statement` | Removes a statement. Requires admin. |
| `submit_draft` | Submits the caller's draft and starts internal review. |
| `get_draft` | Inspects a draft and its review assessment. |
| `discard_draft_op` | Lets the author correct their open draft. |
| `list_my_drafts` | Lists the caller's own drafts. |
| `list_drafts` | Lists the review queue across creators. An AI curator lists and investigates drafts, and a person approves or rejects them in the UI. This tool is the agent's side of that split, and only real writers and admins see it. |
| `set_draft_review_evidence` | Lets the draft creator give the reviewer evidence that only the creator has. |
| `set_operation_evidence` | Lets the draft creator back one operation with what they checked in the product: code, UI or doc location, an excerpt and the claim it shows. The reviewer accepts a link a concrete code excerpt supports, and judges one without evidence more strictly. |
| `list_media` | Lists the screenshots and recordings attached to a statement or concept, with alt text, caption and the URL of the bytes, filtered by the caller's audience. An agent checks what is already illustrated before uploading. |
| `create_media_upload` | Returns a single-use upload link for a screenshot or recording an agent captured; the agent cites the resulting `media_id` as `media` evidence on a draft operation. See [Uploading media](#uploading-media). |
| `claim_curation_work` | Hands an agent working in the product's code a batch of knowledge-health work (isolated or unnamed statements, rephrase requests, open gaps) on a 30-minute lease, with each item's concepts, nearest statements and the link vocabulary. Only that agent can tell from the code whether two statements relate. See [Curation work for outside agents](KNOWLEDGE_HEALTH.md#curation-work-for-outside-agents). |
| `release_curation_work` | Records what came of claimed items (`proposed` with the draft, `no_link` with a reason, or `skipped`) in the memory the connect pass shares, so they are not offered again until they change. |
| `report_knowledge_gap` | Lets an agent report knowledge it could not find, optionally naming the statement, draft or generated document it is about. A report about a draft is resolved when that draft is applied. |
| `request_documentation` | Starts a documentation run. `anchor_entity_id`, with a guideline set and document type, names the entity the document is about, so a repeat request revises that document; without one, the run creates a document. |
| `get_documentation_run` | Polls a run that `request_documentation` or `revise_document` returns. A run the review refused lists the failed findings in `summary.review_findings`; a retry briefed with them lists them in `review_notes`. `retryable` says whether the run can be started again as it was (it wrote nothing and was not a manual edit). |
| `get_generated_document` | Reads the written document and the revision that `revise_document` needs, the state of its pull request (open, merged or closed), refreshed from GitHub at most once a minute, and `stale`: whether a statement it cites was edited, deleted or merged away since, or is no longer visible to the document's audience, with old and new text. |
| `revise_document` | Revises a generated document. `update_sources` briefs the run with the cited statements that changed. A delivered document's revision starts from GitHub edits; when both sides changed it is refused unless `start_from_destination` is passed. |

### Uploading media

An agent uploads in two steps rather than passing the file as a base64 tool
argument. `create_media_upload` takes the alt text and capture details and
returns `upload_url`, valid for 15 minutes; the agent POSTs the raw bytes there
(no sign-in: the link is the credential, and its token is stored only as a
hash) and gets back `media_id`. Base64 would carry megabytes through the
model's context and the MCP message, and the 4 MB request cap would sit below
the 20 MB video limit; a URL keeps the bytes outside the conversation, where
`curl` or the agent's HTTP client sends them. The link is used up by the
first upload the server accepts; a rejected file leaves it usable. The item is
created unlabelled and unattached. The agent then cites it on the draft
operation it illustrates with `set_operation_evidence`
(`{"kind": "media", "media_id": "med_…", "claim": "…"}`), and applying the
draft attaches it to the statements or concept that operation wrote. Set
`MYCELIUM_PUBLIC_URL` so the link is absolute; without it the link is a path on
the server the agent is connected to. See [Media](MEDIA.md).

## HTTP and in-process only

These tools are configuration, curation, review machinery, or composites that the
in-process loops need and that an MCP client can build from the tools above. They
remain registered functions. Leaving MCP is reversible: add the name back to
`MCP_TOOLS`.

| Tool | Why it is not on MCP |
| --- | --- |
| `retrieve_context` | Combines name lookup, entity reads, search, and fetch for the Ask loop's turn budget. It is a distinct primitive, but MCP clients can run the same reads. |
| `find_duplicates` | Audits the whole substrate in near-quadratic time and takes no candidate text. This is curation, not retrieval, so it does not satisfy the Ingest reconcile floor. |
| `find_entity_duplicates` | Audits entity names. This is curation; the Names & aliases workspace lists its results. |
| `connect_statements` | Curation from the Knowledge health screen: proposes links and concept mentions for statements nothing reaches, as a reviewed draft. Each call spends money under the connect action's limits, so it stays where a curator chooses the batch. Refused before collecting evidence when the connect action's provider has no credentials. |
| `get_mention_candidates` | Discovery view for the names workspace (`GET /api/mention-candidates`). |
| `replace_text` | `patch_statement(id, text=...)` covers it. The UI and draft replay use it. A failed embedding is reported as `embedding_pending: true`. |
| `move_name` | Alias curation in the names workspace. |
| `rename_name` | Alias curation in the names workspace. |
| `delete_name` | Alias curation in the names workspace. |
| `delete_entity` | Entity curation in the glossary UI. |
| `upsert_statement_kind` | Vocabulary administration. |
| `delete_statement_kind` | Vocabulary administration. |
| `upsert_link_type` | Vocabulary administration. |
| `delete_link_type` | Vocabulary administration. |
| `upsert_link_type_alias` | Vocabulary administration. |
| `delete_link_type_alias` | Vocabulary administration. |
| `list_link_type_aliases` | Vocabulary administration. |
| `upsert_entity_link_type` | Vocabulary administration. |
| `delete_entity_link_type` | Vocabulary administration. |
| `get_prompt_text` | Prompt configuration. |
| `list_prompt_texts` | Prompt configuration. |
| `retire_prompt_text` | Prompt configuration. |
| `list_documentation_models` | Provider configuration. `request_documentation` uses saved settings when the provider is omitted. |
| `list_documentation_runs` | Run history for the documentation workspace. |
| `list_generated_documents` | Document library browsing. |
| `list_document_revisions` | Document history. |
| `get_document_revision` | Document history. |
| `deliver_document` | Opens or updates a GitHub pull request and tracks it. Publishing outside the instance stays a UI decision. |
| `list_documentation_destinations` | Deployment configuration. |
| `attach_draft_source` | Records CI pull request provenance. Pipeline steps call it over HTTP. |
| `find_my_draft_by_source` | Looks up a draft by CI provenance. Pipeline steps call it over HTTP. |
| `revise_draft_operation` | Curator correction. Internal review calls it in-process. |
| `strike_draft_operation` | Curator correction. Internal review calls it in-process. |
| `request_draft_review` | Review control. The UI calls it through `POST /api/drafts/{id}/review`. |
| `get_draft_review_run` | Review internals. `get_draft` already carries the latest assessment. |
| `inspect_draft_review` | Review machinery. Internal review calls it in-process. |
| `append_draft_correction` | Review machinery. Internal review calls it in-process. |
| `record_draft_review` | Review machinery. Internal review calls it in-process. |
| `apply_reviewed_draft` | Review machinery and recovery. Internal review calls it in-process. |

Internal draft review (`draft_review_runs.py`) calls `inspect_draft_review`,
`record_draft_review`, `append_draft_correction` and `apply_reviewed_draft` as Python
functions. The Ask, Ingest and Documentation loops discover their read tools
from `server.TOOLS`; the Documentation loop is then offered only the reads its
prompts name (`docgen.tools.READ_TOOLS`). Neither path goes through MCP, so the
smaller MCP surface does not change what those loops can call.
