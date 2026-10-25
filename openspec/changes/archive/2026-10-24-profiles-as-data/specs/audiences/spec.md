## ADDED Requirements

### Requirement: Audience rules live in descriptions
The labeller's default instructions SHALL name no audience and no category of knowledge an audience never gets: what an audience may not get SHALL come from its description. The seeded `external-non-technical` description SHALL name technical internals, infrastructure, integration mechanics, internal processes, unreleased work and the roadmap, security internals, commercial terms and other customers as what it must not get.

#### Scenario: Labelling for an edited description
- **WHEN** an administrator adds a category to an external audience's description
- **THEN** the next labelling batch is briefed with that description and no other rule about that audience
