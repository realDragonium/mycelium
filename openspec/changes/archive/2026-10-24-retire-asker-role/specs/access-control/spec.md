## MODIFIED Requirements

### Requirement: Roles
The system SHALL recognise the roles `reader`, `drafter`, `writer` and `admin`, ranked in that order, with `reader` the minimum: every account reads every statement. A tool's required role SHALL follow its name unless the tool declares one: names starting `delete_` or `merge_` require admin, names starting `list_`, `get_`, `search_`, `grep_`, `discover_` or `find_` require reader, and every other tool requires writer. `ask` and `report_knowledge_gap` SHALL require only reader.

#### Scenario: Reader calls a write tool
- **WHEN** a reader calls `upsert_statement`
- **THEN** the call is refused with 403 naming the writer role

#### Scenario: Writer calls an admin tool
- **WHEN** a writer calls `delete_statement`
- **THEN** the call is refused with 403

#### Scenario: Reader opens the web app
- **WHEN** a reader requests `GET /api/data` or `GET /api/history`
- **THEN** the response is 200

### Requirement: One rule for both transports
The HTTP tool routes and MCP tool calls SHALL apply the same role gate for each tool, and `tools/list` SHALL show a caller only the tools that gate lets it call. Without a principal (local stdio) the full list SHALL be shown.

#### Scenario: Listed tools per role
- **WHEN** callers of each role send `tools/list` to `/mcp`
- **THEN** a reader sees 19 tools, a drafter 39 (not `list_drafts`, `request_documentation` or `revise_document`), a writer 39 (not `delete_statement`, `merge_statements` or `merge_entities`) and an admin all 42 advertised tools

#### Scenario: Both MCP protocol revisions
- **WHEN** a reader lists tools once with a 2026-07-28 request and once through a 2025-era session
- **THEN** both lists are filtered identically

### Requirement: Just-in-time provisioning
When a login's verified email domain is listed in `MYCELIUM_JIT_DOMAINS` (comma-separated, case-insensitive, a leading `@` tolerated) and no bootstrap or invite matches, the system SHALL create the user with `MYCELIUM_JIT_DEFAULT_ROLE` (default `reader`). The retired role `asker` SHALL be read as `reader` with a deprecation warning; any other unknown role name SHALL disable JIT provisioning rather than guess.

#### Scenario: Unknown default role
- **WHEN** `MYCELIUM_JIT_DEFAULT_ROLE=superuser` and a login comes from a JIT domain
- **THEN** no user is created and the login is refused with 403

#### Scenario: Retired default role
- **WHEN** `MYCELIUM_JIT_DEFAULT_ROLE=asker` and a login comes from a JIT domain
- **THEN** the user is created as a reader and a deprecation warning is logged

## ADDED Requirements

### Requirement: Retired asker role
The auth store SHALL turn the retired `asker` role into `reader` on users, tokens (OAuth grants included) and invites when it starts, logging how many rows of each changed, and a restored backup SHALL read `asker` as `reader`, logging a deprecation warning.

#### Scenario: Upgrading an instance with an asker token
- **WHEN** an instance holding a token with scope `asker` starts on this build
- **THEN** the token has scope `reader` and reads every statement

## REMOVED Requirements

### Requirement: Asker role
**Reason**: Every account must be able to read all statements; `reader` is the minimum role.
**Migration**: Askers become readers at startup; see "Retired asker role".
