## ADDED Requirements

### Requirement: History feed
`GET /api/history` SHALL return `{events, total, limit, offset}` newest first, each event `{event_id, at, actor, op, target_kind, target_id, before, after, context}`, with statement-link events addressed as `from|to|link_type`. `limit` MUST be clamped to 1..500 (default 50). Optional filters are comma-separated `op` and `target_kind` and a case-insensitive literal substring `q` on `target_id`.

#### Scenario: Filter deletes
- **WHEN** a reader requests `/api/history?op=delete&target_kind=statement`
- **THEN** only statement delete events are returned, newest first

#### Scenario: Reader sees earlier versions
- **WHEN** a reader reads the feed for a statement whose text was edited
- **THEN** the edit event carries its `before` and `after` values

## REMOVED Requirements

### Requirement: Activity feed
**Reason**: The feed is no longer filtered for audience-scoped callers.
**Migration**: See "History feed".
