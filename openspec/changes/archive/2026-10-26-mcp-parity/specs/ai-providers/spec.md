## ADDED Requirements

### Requirement: Settings over MCP
The system SHALL advertise `get_settings(kind, ...)` to readers, returning the product settings, the model chosen per AI action, the draft review settings, the AI instructions (all, one action's editor view, or a preview of a text) and the saved versions of one writing profile slot or AI instruction, and to admins only the setup checklist and AI usage over 1 to 366 days. Saving settings SHALL stay in the web app.

#### Scenario: Writer reads AI usage
- **WHEN** a writer asks `get_settings` for `ai_usage`
- **THEN** the call is refused for want of the admin role

### Requirement: AI texts over MCP
The system SHALL advertise `edit_prompt_text(request)` to real writers and admins, saving or restoring one writing profile slot or AI instruction at its current revision as Settings does; a stale revision is refused and an audience or destinations slot needs an admin.

#### Scenario: Restoring an instruction
- **WHEN** a writer agent restores an earlier version of an AI action's instructions at the current revision
- **THEN** that text becomes the current version, recorded as the agent's
