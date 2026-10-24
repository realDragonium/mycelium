## MODIFIED Requirements

### Requirement: Usage report
The system SHALL serve an admin-only `GET /api/ai-usage?days=N`, with `days` from 1 to 366 and default 30, returning the totals (calls, failed calls, and input, cached, output and total tokens), tokens per UTC day, the same token counts per action and per model, and the ten runs or drafts that used the most tokens. Mycelium SHALL keep no budget of its own: spend and spend limits are on each provider's billing dashboard.

#### Scenario: Out-of-range window
- **WHEN** an admin requests `GET /api/ai-usage?days=400`
- **THEN** the request is rejected as invalid

#### Scenario: Non-admin
- **WHEN** a reader requests `GET /api/ai-usage`
- **THEN** the request is refused with 403

### Requirement: Upgrade replaces dollar limits
The system SHALL, on start and on restoring an archive, replace a saved dollar limit by its token field: `max_cost_usd` by `max_draft_tokens` for draft review and by `max_run_tokens` for connect. A value still at its shipped default ($1 and $0.50) SHALL take the token default; any other value SHALL become 0, meaning no limit, with a log warning naming the old amount. A saved monthly dollar budget SHALL be dropped with the AI budget.

#### Scenario: A set monthly budget
- **WHEN** an instance with `monthly_limit_usd` 50 upgrades
- **THEN** no `ai_budget` section remains and the log says the $50 budget was removed

#### Scenario: A default review cap
- **WHEN** an instance with draft review `max_cost_usd` 1.0 upgrades
- **THEN** `max_draft_tokens` is 300,000

## ADDED Requirements

### Requirement: Upgrade drops the AI budget
The system SHALL, on start and on restoring an archive, drop a saved `ai_budget` settings section and a dismissed `budget` setup step, logging a warning that names the removed monthly limit when one was set, in tokens or in dollars.

#### Scenario: A set monthly budget
- **WHEN** an instance with `monthly_limit_tokens` 5,000,000 upgrades
- **THEN** no `ai_budget` section remains and the log says the budget of 5,000,000 tokens was removed

#### Scenario: An older archive
- **WHEN** an admin restores an archive with an `ai_budget` section and the `budget` setup step dismissed
- **THEN** the restore succeeds without the section, and the other dismissed steps stay dismissed

## REMOVED Requirements

### Requirement: Monthly AI budget
**Reason**: Mycelium sets no AI budget; spend limits are set in dollars in each provider's console.
**Migration**: Set a spend limit on the provider's billing dashboard. The saved section is dropped on upgrade.

### Requirement: Budget pauses only background actions
**Reason**: Without a budget nothing pauses model calls; per-run token caps still stop a runaway run.
**Migration**: None.
