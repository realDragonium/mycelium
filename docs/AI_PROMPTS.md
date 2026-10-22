# AI prompts

Open **AI settings → Prompts** in either UI. Choose Questions, Ingestion,
Research, Document generation, Document review, Draft review, or Alias discovery.
Writers and administrators can edit instructions; readers can inspect them.
Claude and OpenAI use the same saved behavioral instructions for each action.

Edit the text and select **Save instructions**. No restart or redeploy is needed.
Each save retains the previous version and records its author. If another user
changed the text, saving fails with a conflict; reload before saving again.

**Version history** shows previous texts and can restore one as a new version.
**Use shipped default** fills the editor with the current release's default;
save to apply it. Existing saved customizations survive deployments.

**Preview combined prompt** uses the same builders as the AI action. It combines
editable behavior with the fixed system instructions. Request text, retrieved
evidence, tool definitions, and messages exchanged during the loop are supplied
separately. Documentation previews use placeholders for profile-specific content.
Writing guidance, disclosure rules, and templates remain in Documentation profiles.
Document review has separate instructions from the writer.

Tool schemas, response validation, permissions, draft revision checks, and
application safeguards remain controlled by code. Editing instructions does not
grant an AI new tools or permission to apply a draft.

Each run captures instructions once. Background research, documentation, and
draft reviews capture them before waiting for a model slot. Later saves affect
new runs. Ask, ingestion, research, and documentation traces include a `prompts`
list; draft-review records and alias scan results include a `prompt` reference.
Each reference records the action, version, source, and text digest. Saved alias
suggestions retain the scan's reference. Historical records may lack this field.

Texts use the existing versioned `doctrine` rows in `mycelium-prompts.db`, including
the original `ingest`, `research`, and `docgen` rows. Existing MCP prompt-text tools
and backups continue to work. A missing or retired override uses the default;
legacy doctrine file configuration remains the fallback for those three actions.
If the prompt store is unavailable, runs record a diagnostic and use defaults,
matching the existing loop fallback. The editor reports read errors rather than
offering an apparently current version to overwrite.

## When a release changes a default

Ingestion, Research and Document generation start from a seeded version
authored by `seed`; the other actions use the shipped default until someone
saves. On each start the server compares every action with the default the
running build ships:

- If the newest version is still authored by `seed`, the new default is saved
  as another `seed` version. Version history shows it, and can restore the
  previous text.
- If a person saved the newest version, it is never changed. When the shipped
  default first appeared on this instance after that save, the server logs a
  warning (`saved <action> instructions predate the default this build
  ships`) and the editor API reports `newer_default_since`. Compare with
  **Use shipped default**; saving any version clears the report.

Saving the shipped default yourself makes the text yours: later releases
report a newer default rather than replacing it. The instance records when it
first saw each default in `shipped_prompt_texts` in `mycelium-prompts.db`;
backups carry it. Documentation profile templates are not updated this way —
see [Guideline sets](GUIDELINE_SETS.md).
