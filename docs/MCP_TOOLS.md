# MCP tool manifest

Every MCP client receives every advertised tool schema before it asks its first
question. Mycelium therefore advertises 37 of its 83 registered tools over MCP. Every
registered tool keeps its HTTP route (`POST /<kebab-name>`, or `GET` when the tool
takes no arguments) and stays available to the in-process loops (Ask, Ingest,
Documentation) and internal draft review. Removing a tool from MCP removes only
its MCP advertisement.

The list lives in `server.MCP_TOOLS`. `tests/test_mcp_surface.py` keeps this file,
that set, and the registered tools in agreement.

Role filtering still applies: `tools/list` shows a caller only the tools their role
can invoke. An asker sees only `ask`, and a reader sees 18 tools. A drafter sees 34
because their writes are queued on a draft, but they do not see `list_drafts`,
`request_documentation` or `revise_document`. A writer sees 34 and does not see
the admin-only `delete_statement`, `merge_statements` or `merge_entities`. An admin
sees all 37.

## Over MCP

MCP covers the read path, statement and entity authoring, drafts, and the
model-backed entry points a client cannot reproduce itself. Approval, reviewed
application and the reviewer's own records stay off MCP: approval is the operator's
decision, and the rest runs in-process.

| Tool | Why it is on MCP |
| --- | --- |
| `search_statements` | Semantic retrieval with alias boost and graph expansion. This is the main read. |
| `get_statements` | Hydrates known ids and follows links. |
| `find_statement_connections` | Finds bounded routes between statements. It cannot be composed cheaply from other reads. |
| `grep_statements` | Literal lookup for identifiers and quoted strings that semantic search misses. |
| `list_statements` | Enumerates statements that mention an entity or have a kind, without a query. |
| `discover_facts` | Checks many candidate texts in one call before writing (`exists` / `near` / `new`). The repository's authoring and draft skills depend on it. |
| `get_entity` | Hydrates an entity's names and entity links. |
| `list_entities` | Pages entities and matches literal prefixes across aliases. |
| `search_entities` | Finds entities by semantic name or alias. |
| `list_link_types` | Lists the statement link vocabulary and its direction rules, which writers need. |
| `list_statement_kinds` | Lists the statement kind vocabulary. |
| `list_entity_link_types` | Lists the entity link vocabulary that appears in `get_entity`. |
| `ask` | Runs the server's answer loop. It is the only tool an `asker` sees. |
| `ingest` | Turns prose into a reviewable draft, submitted at once while internal draft review is on. |
| `upsert_entity` | Creates or describes the entity a statement names. |
| `upsert_name` | Adds an alias so mentions resolve. |
| `upsert_statement` | Creates or replaces one statement. Its description holds the statement-kind definitions that the authoring skills refer to. |
| `upsert_statements` | Creates one or more statements with links, including cross-references within the batch. |
| `patch_statement` | Edits the text or kind of an existing statement without touching its links. |
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
| `report_knowledge_gap` | Lets an agent report knowledge it could not find, optionally naming the statement, draft or generated document it is about. A report about a draft is resolved when that draft is applied. |
| `request_documentation` | Starts a documentation run. `anchor_entity_id`, with a guideline set and document type, names the entity the document is about, so a repeat request revises that document; without one, the run creates a document. |
| `get_documentation_run` | Polls a run that `request_documentation` or `revise_document` returns. A run the review refused lists the failed findings in `summary.review_findings`. |
| `get_generated_document` | Reads the written document and the revision that `revise_document` needs, the state of its pull request (open, merged or closed), refreshed from GitHub at most once a minute, and `stale`: whether a statement it cites was edited, deleted or merged away since, with old and new text. |
| `revise_document` | Revises a generated document. `update_sources` briefs the run with the cited statements that changed. A delivered document's revision starts from GitHub edits; when both sides changed it is refused unless `start_from_destination` is passed. |

## HTTP and in-process only

These tools are configuration, curation, review machinery, or composites that the
in-process loops need and that an MCP client can build from the tools above. They
remain registered functions. Leaving MCP is reversible: add the name back to
`MCP_TOOLS`.

| Tool | Why it is not on MCP |
| --- | --- |
| `survey_statements` | Its own docstring says it is interchangeable with `search_statements`. This is the one duplicate in the read path. An MCP client can split its own question, and `ask` handles broad questions. Ask and Documentation recon use it in-process. |
| `retrieve_context` | Combines name lookup, entity reads, search, and fetch for the Ask loop's turn budget. It is a distinct primitive, but MCP clients can run the same reads. |
| `find_duplicates` | Audits the whole substrate in near-quadratic time and takes no candidate text. This is curation, not retrieval, so it does not satisfy the Ingest reconcile floor. |
| `find_entity_duplicates` | Audits entity names. This is curation; the Names & aliases workspace lists its results. |
| `get_mention_candidates` | Discovery view for the names workspace (`GET /api/mention-candidates`). |
| `replace_text` | `patch_statement(id, text=...)` covers it. The UI and draft replay use it. |
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
| `save_prompt_text` | Prompt configuration. |
| `get_prompt_text` | Prompt configuration. |
| `list_prompt_texts` | Prompt configuration. |
| `list_prompt_text_versions` | Prompt configuration history. |
| `retire_prompt_text` | Prompt configuration. |
| `restore_prompt_text` | Prompt configuration. |
| `list_documentation_profiles` | Documentation profile configuration. |
| `get_documentation_profile` | Documentation profile configuration. |
| `save_documentation_profile` | Documentation profile configuration. `audience` chooses the audience the profile writes for; omitted, it keeps the current one. Changing it on an existing profile needs an admin. |
| `retire_documentation_profile` | Documentation profile configuration. |
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
