## ADDED Requirements

### Requirement: Web app parity over MCP
Every action a person can take on the knowledge base through the web app's HTTP routes SHALL also be an MCP tool that applies the same role rules, real-principal rules, validation, revision checks and audit records. A route MAY have no tool only when it operates the server or is no action a person takes, and the system SHALL state that reason for each such route.

#### Scenario: Operating the server
- **WHEN** a route signs in, runs OAuth, manages users or tokens, saves provider, model or limit settings, the setup checklist or traces, or connects the GitHub app
- **THEN** it has no MCP tool and its stated reason says so

#### Scenario: Browser plumbing
- **WHEN** a route serves a page, bootstraps the browser's graph, renders a preview, runs a reviewer step in-process or records CI provenance
- **THEN** it has no MCP tool and its stated reason says so

#### Scenario: A new route without a tool
- **WHEN** a route is added that names neither an MCP tool nor a reason
- **THEN** the test suite fails naming the route

#### Scenario: Same rule on both transports
- **WHEN** a drafter resolves a knowledge gap through `PATCH /api/knowledge-gaps/{id}` and through `update_knowledge_gap`
- **THEN** both are refused for want of a real writer role

### Requirement: Not-found refusals over MCP
An MCP tool call refused because something it names does not exist SHALL return the refusal's message to the caller.

#### Scenario: Unknown plan item
- **WHEN** an agent dismisses a plan item that does not exist
- **THEN** the tool error says the plan item was not found

## MODIFIED Requirements

### Requirement: One rule for both transports
The HTTP tool routes and MCP tool calls SHALL apply the same role gate for each tool, and `tools/list` SHALL show a caller only the tools that gate lets it call. Without a principal (local stdio) the full list SHALL be shown.

#### Scenario: Listed tools per role
- **WHEN** callers of each role send `tools/list` to `/mcp`
- **THEN** a reader sees 33 tools, a drafter 57 (not the tools that land live and need a real writer, such as `list_drafts`, `request_documentation`, `edit_names` or `curate_audiences`), a writer 74 (not `delete_statement`, `merge_statements`, `merge_entities`, `retire_writing_profile`, `restore_writing_profile`, `manage_audiences`, `manage_draft_review_backlog` or `unblock_automation`) and an admin all 82 advertised tools

#### Scenario: Both MCP protocol revisions
- **WHEN** a reader lists tools once with a 2026-07-28 request and once through a 2025-era session
- **THEN** both lists are filtered identically
