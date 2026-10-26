# MCP tool manifest

Every MCP client receives every advertised tool schema before it asks its first
question. Mycelium therefore advertises 82 of its 115 registered tools over MCP. Every
registered tool keeps its HTTP route (`POST /<kebab-name>`, or `GET` when a read
tool takes no arguments) and stays available to the in-process loops (Ask, Ingest,
Documentation) and internal draft review. Removing a tool from MCP removes only
its MCP advertisement.

The list lives in `server.MCP_TOOLS`. `tests/test_mcp_surface.py` keeps this file,
that set, and the registered tools in agreement.

Role filtering still applies: `tools/list` shows a caller only the tools their role
can invoke. The minimum role is reader: a reader sees 33 tools. A drafter sees 57
because their writes are queued on a draft, but they do not see the tools that
land live and so need a real writer: `list_drafts`, `request_draft_review`,
`answer_draft_review`, the
documentation tools that start runs, edit, retry, plan, decide or deliver,
`save_writing_profile`, `edit_prompt_text`, `edit_names`, `edit_media`,
`curate_audiences`, `update_knowledge_gap`, the admin tools below, or the tools
that claim and do agent tasks. A writer sees 74 and does not see the admin-only
`delete_statement`, `merge_statements`, `merge_entities`,
`retire_writing_profile`, `restore_writing_profile`, `manage_audiences`,
`manage_draft_review_backlog` or `unblock_automation`. An admin sees all
82. While Ask is set to External agent, `ask` is listed to no one, so each
count is one lower.

A grouped tool can hold an action a stricter role takes: `edit_names` merges
and removes, `edit_media` deletes and `edit_vocabulary` deletes only for an
admin, and `get_settings` shows the setup checklist and AI usage only to an
admin, as the web app does.

## Web app parity

Every action a person can take on the knowledge base in the web app is also an
MCP tool. `mycelium.http.mcp_parity` names, for every HTTP route, the tool that
offers its action, or why it has none: the action is about operating the server
(signing in, OAuth, users and tokens, provider and model choices, limits, the
setup checklist, traces, the GitHub app connection), it is no action a person
takes (browser pages and bootstraps, rendering a preview, the reviewer's
in-process steps, CI provenance), or another branch is adding it.
`tests/test_mcp_parity.py` walks the app's routes and fails on a route with
none of these, so a new screen cannot leave agents out. The route and its tool
call the same server function, so they share role rules, validation, revision
checks and audit records; saving settings stays in the web app because it
operates the server, while `get_settings` lets an agent read them.

## Over MCP

MCP covers the read path, statement and entity authoring, names and the
glossary, drafts and deciding them, knowledge health and gaps, audiences, media, documentation
and its plans, writing profiles and the texts that steer the AI, and the
model-backed entry points a client cannot reproduce itself. The reviewer's own
records stay off MCP: they run in-process.

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
| `list_link_type_aliases` | Lists the phrasings each link type accepts, as the Glossary shows them. |
| `get_history` | Reads the Activity feed: who created, edited, linked or deleted what, with before and after snapshots, filtered by operation, kind or id. |
| `ask` | Runs the server's answer loop. Hidden while Ask is set to External agent. |
| `ingest` | Turns prose into a reviewable draft, submitted at once while internal draft review is on. While Ingest is set to External agent it queues the work for an outside agent instead. |
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
| `edit_vocabulary` | Edits the Glossary: saves or deletes a statement kind, link type, link-type alias or entity link type. A drafter's edit is queued on their draft; deleting needs an admin. |
| `get_mention_candidates` | Finds text matches across a concept's aliases (derived, approved or possible), as the names workspace shows them. |
| `find_entity_duplicates` | Lists concepts that may be duplicates, as the names workspace does. |
| `get_names_workspace` | Reads the Names & aliases workspace: the catalogue, one concept with the `revision` an edit needs, dismissed duplicate pairs, and the AI's alias suggestions. |
| `edit_names` | Edits names as the workspace does, landing live: preview and apply an add, correct, prefer, move, split, merge or remove (merge and remove need an admin), dismiss or restore a duplicate pair, ask the AI for alias suggestions, and review one (a human writer). Real writers and admins only. |
| `submit_draft` | Submits the caller's draft and starts internal review. |
| `get_draft` | Inspects a draft and its review assessment. |
| `discard_draft_op` | Lets the author correct their open draft. |
| `list_my_drafts` | Lists the caller's own drafts. |
| `list_drafts` | Lists the review queue across creators, with each draft's latest review summary, filtered by status, creator, review label or what the review did (for example the drafts the automatic reviewer rejected, or the corrections it held for a curator). An agent finds the drafts it will check against the code here. Only real writers and admins see it. |
| `review_draft` | Decides a submitted draft another principal created, as a curator does in the UI: approve, approve with corrections in the reviewer's precise shape, reject with a reason, or ask a person a question. An agent with the product's code can check each operation, which the server's reviewer cannot, so it needs to decide on what it found under any review setting. Real writers and admins only; see [Deciding drafts](DRAFT_REVIEW.md#deciding-drafts). |
| `reopen_draft` | Returns a rejected draft, the automatic reviewer's rejections included, to submitted so it can be decided again. Without it a wrong rejection is final. Real writers and admins only. |
| `set_draft_review_evidence` | Lets the draft creator give the reviewer evidence that only the creator has. |
| `withdraw_draft` | Withdraws an open or submitted draft, as its creator or a real writer may on the Drafts screen. |
| `answer_draft_review` | Answers the internal reviewer's questions on a draft, as a curator does in the draft view, and has it reviewed again. Real writers and admins only; an agent answering with code evidence uses the curation queue's `question` items. |
| `request_draft_review` | Runs the internal reviewer on a draft again, as **Review again** does. Real writers and admins only. |
| `manage_draft_review_backlog` | Lists, starts, pauses or resumes the review of submitted drafts the reviewer has not reached. Real admins only. |
| `set_operation_evidence` | Lets the draft creator back one operation with what they checked in the product: code, UI or doc location, an excerpt and the claim it shows. The reviewer accepts a link a concrete code excerpt supports, and judges one without evidence more strictly. |
| `get_knowledge_health` | Reads the Knowledge health screen: the counts, how much knowledge there is, whether the connect pass can run, curation claims, uncovered statements per profile and `stopped` automatic work; with `which`, one page of isolated, unmentioned or unlabelled statements or undescribed or unused concepts. |
| `unblock_automation` | Frees an abandoned agent's curation claims, or retries automatic work that stopped after too many failures. Real admins only. |
| `connect_statements` | Runs the AI connect pass over chosen statements as a reviewed draft, as **Connect** on the Knowledge health screen does. Uses model tokens under the connect action's limits; refused when the connect action has no model or credentials. |
| `list_knowledge_gaps` | Lists gap reports as the Gaps page does, by status. |
| `update_knowledge_gap` | Resolves, dismisses or reopens a gap. Real writers and admins only. |
| `get_audiences` | Reads audiences and labels: each audience with its counts and the backfill's progress, one statement's label, statements by label state or visibility, an audience's pending external grants or a sample of them, and spot checks. |
| `manage_audiences` | Creates, saves, retires an audience or runs the labelling backfill, as Settings → Audiences does. Real admins only. |
| `curate_audiences` | A curator's label decisions: set, confirm or clear a statement's label, decide a spot check, confirm or reject pending external grants, or accept the rest after a sample. Real writers and admins only. |
| `list_media` | Lists the screenshots and recordings attached to a statement or concept, one item, or the media library by filter, with alt text, caption and the URL of the bytes. An agent checks what is already illustrated before uploading. |
| `create_media_upload` | Returns a single-use upload link for a screenshot or recording an agent captured; the agent cites the resulting `media_id` as `media` evidence on a draft operation. See [Uploading media](#uploading-media). |
| `edit_media` | Changes a media item as the library does: details, label, confirm a label, attach or detach, an upload link for new content, or delete (an admin). Real writers and admins only. |
| `claim_curation_work` | Hands an agent working in the product's code a batch of knowledge-health work (isolated or unnamed statements, rephrase requests, open gaps, the draft reviewer's questions for a person, duplicate statement or concept pairs, concepts without a description or without statements) on a 30-minute lease, with each item's concepts, nearest statements and the link vocabulary. Only that agent can tell from the code whether two statements relate. See [Curation work for outside agents](KNOWLEDGE_HEALTH.md#curation-work-for-outside-agents). |
| `release_curation_work` | Records what came of claimed items (`proposed` with the draft, `no_link` with a reason, or `skipped`) in the memory the connect pass shares, so they are not offered again until they change; a skipped item is offered again until it was skipped, or its claim ran out, more often than its limit. Closes a gap as `resolved` by an applied draft or `not_applicable` with a reason, and answers a reviewer's question as `answered` with evidence, which starts the draft's fresh review. |
| `report_knowledge_gap` | Lets an agent report knowledge it could not find, optionally naming the statement, draft or generated document it is about. A report about a draft is resolved when that draft is applied. |
| `request_documentation` | Starts a documentation run. `anchor_entity_id`, with a guideline set and document type, names the entity the document is about, so a repeat request revises that document; without one, the run creates a document. |
| `get_documentation_run` | Polls a run that `request_documentation` or `revise_document` returns. A run the review refused lists the failed findings in `summary.review_findings`; a retry briefed with them lists them in `review_notes`. `retryable` says whether the run can be started again as it was (it wrote nothing and was not a manual edit). |
| `get_generated_document` | Reads the written document and the revision that `revise_document` needs, the state of its pull request (open, merged or closed), refreshed from GitHub at most once a minute, and `stale`: whether a statement it cites was edited, deleted or merged away since, or is no longer visible to the document's audience, with old and new text. |
| `claim_agent_task` | Leases work an action set to External agent would otherwise give a server model (writing, reviewing or planning documentation, reviewing a plan's items, labelling audiences or reviewing waiting external grants, ingest, the connect pass, alias discovery, draft review) for 30 minutes, with a brief holding the model's instructions, input and result schema; a documentation task's brief also carries the whole writing profile it is for (`profile`). Writers and admins only; a draft's creator is never given its review, nor a labeller the review of its grants, and `note` says when such tasks were withheld. See [Agent tasks](AGENT_TASKS.md). |
| `read_for_agent_task` | Runs one of a task's read tools for it and records the read; a documentation task's reads run inside the audience boundary it writes for. |
| `submit_agent_task` | Hands in a claimed task's result, which passes the checks a server model's output would; a refusal returns findings and the retries left. |
| `release_agent_task` | Gives a claimed task back to the queue with a reason, which the next claimant sees. Give-backs and leases that ran out count toward the task's limit; past it the task fails with the reason. |
| `get_agent_task` | Follows work the caller queued for an outside agent, such as an `ingest` that returned `waiting_for_agent`: status, findings and the draft it made. |
| `revise_document` | Revises a generated document. `update_sources` briefs the run with the cited statements that changed. A delivered document's revision starts from GitHub edits; when both sides changed it is refused unless `start_from_destination` is passed. |
| `request_documentation_plan` | Starts the same plan as **Documents → Plan** for a writing profile, on the server's model or as a `documentation_planning` agent task. An agent keeping documentation current needs to ask which documents are missing, not only write the ones it already knows. Writers and admins only. See [Documentation planning](DOCUMENTATION_PLANNING.md). |
| `get_documentation_plan` | Reads a writing profile's plan as **Documents → Plan** shows it: the items with their state, the AI reviewer's decisions and reasons, the runs approved items started and why one could not start, out-of-date documents, coverage gaps and the uncovered and dismissed statements. An agent keeping documentation current needs to see what was proposed and decided before it plans again or follows the runs. |
| `deliver_document` | Opens or updates the document's GitHub pull request, as **Create / update GitHub PR** does. Refused unless the document's writing profile lets agents deliver (`agents`, or `auto`, where the server also publishes each reviewed revision itself; off by default), so publishing outside the instance stays a person's decision until a writer hands it to agents for that profile, and refused for a destination the profile does not publish to. Merging stays with the destination repository. Writers and admins only. |
| `list_documentation` | Lists what the Documents workspace shows: documents, runs, destinations, the options a run may use, and the maintenance feed. |
| `get_document_history` | Reads a document's revisions, one revision, or its diff against the one before. |
| `edit_document` | Saves a person's own edit of a saved document or an unsaved run's result, reviewed as a run. Real writers and admins only. |
| `retry_documentation` | Starts a run or a plan item's run that wrote nothing again, optionally briefed with the review's findings. Real writers and admins only. |
| `decide_documentation_plan` | Approves or dismisses plan items, dismisses or restores an uncovered statement, and dismisses an out-of-date document, as Documents → Plan does. Real writers and admins only. |
| `list_writing_profiles` | Lists the writing profiles with their audience, policies, destinations, template names, readiness and `revision`. A writer or admin agent managing documentation needs to see what profiles exist before it plans or writes. |
| `get_writing_profile` | Reads one profile in full (guidance, disclosure rules, every template, policies, destinations, `revision`) and the description of the audience it writes for. An agent reads the profile it writes for here, and an editor reads the `revision` a save needs. |
| `save_writing_profile` | Creates or updates a profile with its whole content, through the same validation, role rules and revision check as **Settings → Documentation**: a stale `revision` is refused, and removing a template or changing an existing profile's audience or destinations needs an admin. Real writers and admins only; it lands live and never queues on a draft. |
| `retire_writing_profile` | Retires a profile, keeping its history and documents, as **Retire profile** does. The default profile cannot be retired. Real admins only. |
| `restore_writing_profile` | Brings a retired profile back with the texts it held when it was retired. Real admins only. |
| `get_settings` | Reads a Settings screen: product limits, the model per AI action, draft review, the setup checklist and AI usage (admins), the AI instructions with a preview, and a text's saved versions. Saving settings stays in the web app. |
| `edit_prompt_text` | Saves or restores one writing profile slot or AI instruction text at its revision, as Settings does. Real writers and admins only. |

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

These tools are covered by a tool above, are review machinery, or are composites
the in-process loops need. They remain registered functions, and
`mycelium.http.mcp_parity` names the tool that covers each one's route or why
none does. Leaving MCP is reversible: add the name back to `MCP_TOOLS`.

| Tool | Why it is not on MCP |
| --- | --- |
| `retrieve_context` | Combines name lookup, entity reads, search, and fetch for the Ask loop's turn budget. It is a distinct primitive, but MCP clients can run the same reads. |
| `find_duplicates` | Audits the whole substrate in near-quadratic time and takes no candidate text. This is curation, not retrieval, so it does not satisfy the Ingest reconcile floor. |
| `replace_text` | `patch_statement(id, text=...)` covers it. The UI and draft replay use it. A failed embedding is reported as `embedding_pending: true`. |
| `move_name` | `edit_names` moves an alias through the workspace's checks. |
| `rename_name` | `edit_names` corrects an alias through the workspace's checks. |
| `delete_name` | `edit_names` removes an alias through the workspace's checks. |
| `delete_entity` | No screen deletes a concept outright; drafts replay it, and `merge_entities` and `edit_names` consolidate concepts. |
| `upsert_statement_kind` | `edit_vocabulary` saves a statement kind. |
| `delete_statement_kind` | `edit_vocabulary` deletes a statement kind. |
| `upsert_link_type` | `edit_vocabulary` saves a link type. |
| `delete_link_type` | `edit_vocabulary` deletes a link type. |
| `upsert_link_type_alias` | `edit_vocabulary` saves a link-type alias. |
| `delete_link_type_alias` | `edit_vocabulary` deletes a link-type alias. |
| `upsert_entity_link_type` | `edit_vocabulary` saves an entity link type. |
| `delete_entity_link_type` | `edit_vocabulary` deletes an entity link type. |
| `get_prompt_text` | Raw prompt-store rows; `get_writing_profile` and `get_settings` read the texts Settings edits. |
| `list_prompt_texts` | Raw prompt-store rows; `get_writing_profile` and `get_settings` read the texts Settings edits. |
| `retire_prompt_text` | Raw prompt-store rows; `retire_writing_profile` retires a profile. |
| `list_documentation_models` | `list_documentation` returns it as part of `options`. |
| `list_documentation_runs` | `list_documentation` lists runs. |
| `list_generated_documents` | `list_documentation` lists documents. |
| `list_document_revisions` | `get_document_history` lists revisions. |
| `get_document_revision` | `get_document_history` reads one revision. |
| `list_documentation_destinations` | `list_documentation` lists destinations. |
| `attach_draft_source` | Records CI pull request provenance. Pipeline steps call it over HTTP. |
| `find_my_draft_by_source` | Looks up a draft by CI provenance. Pipeline steps call it over HTTP. |
| `revise_draft_operation` | Curator correction. Internal review calls it in-process; over MCP, `review_draft` corrections change operations. |
| `strike_draft_operation` | Curator correction. Internal review calls it in-process; over MCP, a `strike` correction in `review_draft` removes one. |
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
