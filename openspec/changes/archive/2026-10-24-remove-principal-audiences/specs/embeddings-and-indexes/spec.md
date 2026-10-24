## MODIFIED Requirements

### Requirement: Audience-restricted vector ranking
Inside a documentation run's audience boundary, statement vector searches SHALL rank only the statements that audience may see, so a top-k result is the k nearest visible statements rather than what survives filtering of a global top-k. Visibility is defined by the `audiences` capability.

#### Scenario: Hidden near neighbours
- **WHEN** the 10 statements nearest a query are hidden from an external documentation run and the run searches with `limit: 5`
- **THEN** the run receives the 5 nearest statements visible to its audience
