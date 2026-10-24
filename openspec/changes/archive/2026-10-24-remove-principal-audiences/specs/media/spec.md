## MODIFIED Requirements

### Requirement: Media label is independent of what it illustrates
The system MUST check media only against its own label wherever it reaches a documentation run or a document, so a statement visible to an audience never widens the visibility of media attached to it.

#### Scenario: Internal screenshot on an external statement
- **WHEN** an unlabelled screenshot is attached to a statement labelled for the external `customers` audience
- **THEN** a documentation run for `customers` is not offered the screenshot

## REMOVED Requirements

### Requirement: Scoped callers learn nothing about hidden media
**Reason**: Principals are no longer scoped to an audience; every reader may fetch and list media.
**Migration**: None.
