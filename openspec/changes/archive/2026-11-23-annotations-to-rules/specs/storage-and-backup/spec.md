## ADDED Requirements

### Requirement: Upgrades convert removed annotations
The system SHALL, when upgrading a database that still holds annotations from the removed annotation feature, turn each annotation into a `rule` statement with the annotation's text, link every statement it annotated to that rule with `governed-by`, and give the rule the system those statements share, or none when they differ. It SHALL then drop the annotation records, so statements, entities and names that carried them can be deleted and merged.

#### Scenario: Annotated statement after upgrade
- **WHEN** an instance holds the statement "An invoice is sent." annotated with "Invoice links do not expire." and starts on the current build
- **THEN** "Invoice links do not expire." is a `rule` statement, "An invoice is sent." is `governed-by` it, and deleting "An invoice is sent." succeeds

#### Scenario: Annotation across systems
- **WHEN** an annotation annotated one statement of the Billing system and one of the Identity system
- **THEN** its rule has no system
