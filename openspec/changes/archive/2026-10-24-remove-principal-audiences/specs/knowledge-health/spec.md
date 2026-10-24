## ADDED Requirements

### Requirement: Claiming curation work
The system SHALL provide `claim_curation_work(kind, limit=5)`, advertised over MCP, for callers with at least the drafter role, leasing up to `limit` (0 to 20) items of `kind` (`isolated`, `unnamed`, `rephrase` or `gap`) for 30 minutes and returning `kind`, `items`, `renewed`, `expires_at` and `link_types` (the link vocabulary with each type's description and direction).

#### Scenario: Agent claims isolated statements
- **WHEN** a drafter calls `claim_curation_work("isolated", limit=3)`
- **THEN** up to three isolated statements are leased to it for 30 minutes

#### Scenario: Reader tries to claim
- **WHEN** a reader calls `claim_curation_work`
- **THEN** the call is refused with a role error

## REMOVED Requirements

### Requirement: Curation claim
**Reason**: Claiming no longer depends on an audience scope.
**Migration**: See "Claiming curation work".
