## ADDED Requirements

### Requirement: Uncovered statements per profile
The system SHALL report in `GET /api/knowledge-health` an `uncovered_by_profile` map holding, for each writing profile that can be planned for, how many statements are uncovered for it (its audience may see them, none of its documents cites them and they were not dismissed for it), computed from current data on every request.

#### Scenario: Profile with undocumented statements
- **WHEN** the `public` profile's audience may see 12 statements no `public` document cites
- **THEN** `uncovered_by_profile` reports 12 for `public`
