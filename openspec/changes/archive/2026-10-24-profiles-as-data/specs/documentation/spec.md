## REMOVED Requirements

### Requirement: Starter profile seeding
**Reason**: Profiles are instance data; the package seeds none.
**Migration**: A profile seeded by an earlier build stays as saved data. Start a new profile from `docs/profile-examples/`.

### Requirement: Starter profiles
**Reason**: The package ships no profile content.
**Migration**: The same texts are plain-text examples in `docs/profile-examples/`.

### Requirement: Using a starter
**Reason**: `GET /api/documentation/starters` and the editor's starter actions are removed with the starters.
**Migration**: Create a profile in Settings → Documentation or with `save_writing_profile`, pasting an example's texts.

## ADDED Requirements

### Requirement: No packaged profiles
The system SHALL ship no writing profile and no profile text: a fresh instance SHALL have no profile until one is saved, and SHALL leave every stored profile, including one seeded by an earlier build, unchanged on start.

#### Scenario: Fresh instance
- **WHEN** the server starts on a data directory with no prompt texts
- **THEN** `list_writing_profiles` returns no profiles

### Requirement: Default profile name without a profile
The system SHALL accept a documentation settings save that keeps the stored default profile name when no profile has that name, and MUST refuse one that changes it to a name no live profile has.

#### Scenario: Destinations before any profile
- **WHEN** an admin on a fresh instance saves a destination and keeps the default `kb-authoring`
- **THEN** the settings are saved

### Requirement: Writing profiles over MCP
The system SHALL advertise `list_writing_profiles`, `get_writing_profile`, `save_writing_profile`, `retire_writing_profile` and `restore_writing_profile` over MCP. Saves, retirements and restores SHALL go through the profile editor's validation, role rules and revision check, and MUST need a real role: writer to save, admin to retire or restore.

#### Scenario: Stale save over MCP
- **WHEN** a writer calls `save_writing_profile` with a `revision` older than the stored profile's
- **THEN** the save is refused as a conflict and nothing is written

#### Scenario: Writer changes the audience over MCP
- **WHEN** a writer calls `save_writing_profile` for an existing profile with a different `audience`
- **THEN** the save is refused for lacking the admin role

### Requirement: Restoring a retired profile
The system SHALL restore a retired profile, given its current `revision`, to the texts each slot held when the profile was retired, leaving retired the slots removed before then, and MUST refuse a profile that is not retired.

#### Scenario: Template removed before retirement
- **WHEN** an admin removes the `reference` template of profile `help`, retires `help` and then restores it
- **THEN** `help` has its other templates back and `reference` stays retired
