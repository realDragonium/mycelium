## ADDED Requirements

### Requirement: Knowledge health over MCP
The system SHALL advertise `get_knowledge_health(which?, after?, limit=50, to_connect=false)` to readers. Without `which` it SHALL return what the Knowledge health screen shows, stopped automatic work included. With `which` it SHALL return one page of `isolated`, `unmentioned` or `unlabelled` statements or `undescribed` or `unused` concepts, `limit` 1 to 200.

#### Scenario: A page of isolated statements
- **WHEN** a reader agent asks for `isolated` with `limit` 2
- **THEN** it gets the same two statements and `next_after` as the screen's list

### Requirement: Unblocking automation over MCP
The system SHALL advertise `unblock_automation(request)` to real admins only, freeing a holder's curation claims (`free_claims`) or retrying a stopped item (`retry_stopped`), as the Knowledge health screen does.

#### Scenario: Retrying stopped work
- **WHEN** an admin agent calls `unblock_automation` with `retry_stopped` for a stopped connect item
- **THEN** the item leaves `stopped` with a fresh failure count, as the screen's Retry does

#### Scenario: Writer frees claims
- **WHEN** a writer calls `unblock_automation`
- **THEN** the call is refused for want of the admin role

### Requirement: Knowledge gaps over MCP
The system SHALL advertise `list_knowledge_gaps(status)` to readers, with `status` `all` (default), `open`, `resolved` or `dismissed`, and `update_knowledge_gap(gap_id, action)` to real writers and admins, where `action` is `resolve`, `dismiss` or `reopen`, recorded as the caller's.

#### Scenario: Agent resolves a gap
- **WHEN** a writer agent resolves an open gap
- **THEN** the gap is resolved by that agent and the Gaps page shows it so

## MODIFIED Requirements

### Requirement: Connect pass tool
The system SHALL provide `connect_statements(statement_ids)`, available over HTTP as `POST /connect-statements` and advertised over MCP, requiring the writer role (a drafter also satisfies it), that runs one model loop over the given statements and produces at most one draft.

#### Scenario: Writer connects a batch
- **WHEN** a writer calls `connect_statements` with three isolated statement ids
- **THEN** one run proposes links and concept mentions for them as one draft
