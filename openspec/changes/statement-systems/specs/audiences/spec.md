## ADDED Requirements

### Requirement: Scoped reads leave out systems
Statements read as an audience SHALL come without their `system` field, and reads as an audience SHALL NOT accept a `system` filter, so documentation runs and agent tasks read statements as before. Tools offered to a scoped reader SHALL omit the `system` parameter and say in their description that the `system` filter and field are not available.

#### Scenario: Documentation run over an integration step
- **WHEN** a documentation run for the internal technical audience reads a statement whose system is Paylark
- **THEN** the statement has no `system` field
