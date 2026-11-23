## ADDED Requirements

### Requirement: Upgrades convert removed annotations
The system SHALL, when upgrading a database that still holds annotations from the removed annotation feature, turn each annotation into a `rule` statement that every statement it annotated is `governed-by`, with the system those statements share. An entity annotation keeps its entity only when its text yields a mention of it; each lost association SHALL be logged. The annotation records SHALL then be dropped, so what carried them can be deleted and merged.

#### Scenario: Annotated statement after upgrade
- **WHEN** an instance holds the statement "An invoice is sent." annotated with "Invoice links do not expire." and starts on the current build
- **THEN** "Invoice links do not expire." is a `rule` statement, "An invoice is sent." is `governed-by` it, and deleting "An invoice is sent." succeeds

#### Scenario: Annotation across systems
- **WHEN** an annotation annotated one statement of the Billing system and one of the Identity system
- **THEN** its rule has no system

#### Scenario: Entity annotation that does not name its entity
- **WHEN** the Workspace entity carried the annotation "Members are invited by email."
- **THEN** that text becomes a rule that does not mention Workspace, and the upgrade logs the lost association
