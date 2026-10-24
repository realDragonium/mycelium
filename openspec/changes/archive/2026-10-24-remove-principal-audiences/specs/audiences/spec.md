## MODIFIED Requirements

### Requirement: Only administrators configure audiences
The system SHALL let only an administrator create (`POST /api/audiences`), edit or restore (`PUT /api/audiences/{audience_id}`) and retire (`POST /api/audiences/{audience_id}/retire`) audiences, and SHALL refuse anyone else with 403. Any signed-in caller MAY read `GET /api/audiences`, whose `can_configure` is true only for an administrator.

#### Scenario: Writer tries to create an audience
- **WHEN** a writer posts to `/api/audiences`
- **THEN** the response is 403

### Requirement: Unlabelled statements are internal only
A statement without a label SHALL be visible to every internal audience and to no external audience.

#### Scenario: New statement before labelling
- **WHEN** a statement has just been written and has no label yet
- **THEN** an external documentation run cannot see it
- **AND** an internal one can

### Requirement: Confirming external grants
While **Confirm external grants** is on (`confirm_external_grants`, default on), an AI grant that would make a statement visible to an external audience that could not see it before SHALL be stored as waiting (`pending`) rather than granted. Grants to internal audiences, and external grants the statement could already see, SHALL apply at once, and an external audience the AI no longer grants SHALL be withdrawn at once.

#### Scenario: New external grant waits
- **WHEN** the AI labels a new statement about SSO setup for `external-technical`
- **THEN** the label lists `external-technical` under `pending`
- **AND** an `external-technical` documentation run cannot see the statement

## ADDED Requirements

### Requirement: Media audience labels bound documentation
Media items SHALL carry their own curator-decided audience label under the same visibility rules (unlabelled media is internal only, inclusion applies), and a media item SHALL be offered to a documentation run only when its own label allows the run's audience, whatever the label of the statement it is attached to; see the `media` capability.

#### Scenario: Unlabelled media and an external run
- **WHEN** an external documentation run writes about a statement with unlabelled media attached
- **THEN** the run is not offered the media

### Requirement: Audiences do not scope principals
Users, tokens and OAuth grants SHALL carry no audience: every principal reads what its role allows, and audiences bound only documentation runs, plans and documents.

#### Scenario: Reader and internal-only knowledge
- **WHEN** a reader token searches for a statement visible only to internal audiences
- **THEN** the statement is returned

## REMOVED Requirements

### Requirement: Media audience labels
**Reason**: Media labels no longer limit what a principal reads.
**Migration**: See "Media audience labels bound documentation".

### Requirement: Audience-scoped principals
**Reason**: Audiences are a documentation concept only; principals are no longer scoped.
**Migration**: The auth store drops the audience from users, tokens and OAuth codes at startup; a scoped principal becomes unscoped and is logged. Restrict reading by role.

### Requirement: Scoped principals are read-only
**Reason**: There are no scoped principals.
**Migration**: Give a principal the reader role to keep it read-only.

### Requirement: Scoped principal tool allowlist
**Reason**: There are no scoped principals.
**Migration**: None; tools are gated by role.

### Requirement: Other tools refused to scoped principals
**Reason**: There are no scoped principals.
**Migration**: None; tools are gated by role.

### Requirement: Scoped principal route allowlist
**Reason**: There are no scoped principals.
**Migration**: None; routes are gated by role.

### Requirement: Scoped reads run inside the boundary
**Reason**: Only documentation runs read inside an audience's boundary.
**Migration**: See "Audience boundary".

### Requirement: Generated documents for scoped principals
**Reason**: Every principal reads every generated document its role allows.
**Migration**: None.

### Requirement: History for scoped principals
**Reason**: Every principal reads the full activity feed.
**Migration**: None.

### Requirement: Retired audience on a principal
**Reason**: Principals carry no audience.
**Migration**: None.
