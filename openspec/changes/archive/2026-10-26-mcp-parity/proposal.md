## Why

Agents could read and write statements, drafts, documents and writing
profiles over MCP, but much of what a person does in the web app had no tool:
knowledge health, gaps, names and the glossary, audience labels, media edits,
the documentation workspace and its plans, the activity feed and settings. An
agent working as a curator had to stop where a person would carry on, and
nothing stopped the next screen from adding another gap.

## What Changes

- Every web-app action on the knowledge base gets an MCP tool with the same
  role rules, validation, revision checks and audit, because the route and the
  tool call the same server function. Related actions are grouped into one
  tool with an `action` (writes) or `view`/`kind` (reads).
- New tools: `get_knowledge_health`, `unblock_automation`,
  `list_knowledge_gaps`, `update_knowledge_gap`, `get_history`,
  `get_names_workspace`, `edit_names`, `edit_vocabulary`, `get_audiences`,
  `manage_audiences`, `curate_audiences`, `edit_media`, `list_documentation`,
  `get_document_history`, `edit_document`, `retry_documentation`,
  `decide_documentation_plan`, `withdraw_draft`,
  `manage_draft_review_backlog`, `get_settings` and `edit_prompt_text`.
  `connect_statements`, `get_mention_candidates`, `find_entity_duplicates`,
  `request_draft_review` and `list_link_type_aliases` are now advertised.
- `list_media` also reads one item or the media library; `edit_media` can hand
  out an upload link that replaces an item's content.
- Saving settings, signing in, OAuth, users and tokens, traces and the GitHub
  app connection stay in the web app: they operate the server. Draft decisions
  are another change's.
- A test walks every HTTP route and fails on one with neither a tool nor a
  stated reason.
- A refusal for something that does not exist reaches an MCP caller as its
  message instead of an opaque error.

## Impact

- Specs: access-control, knowledge-health, knowledge-model, media,
  drafts-and-review, audiences, documentation, ai-providers.
- Code: the server's tool modules, the HTTP routes that now call them, the
  route parity table and its test, the MCP manifest and the skills.
