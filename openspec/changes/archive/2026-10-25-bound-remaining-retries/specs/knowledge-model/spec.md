## ADDED Requirements

### Requirement: Failing mention recomputes
The system SHALL redo a failing chunk of queued mention recomputes one at a time, so the rest complete, and SHALL pass over a queued recompute that failed more often than `mention_retries` (Automation limits, default 2), listing it as stopped until an admin retries it.

#### Scenario: One recompute keeps failing
- **WHEN** one queued recompute fails every time and others are queued behind it
- **THEN** the others complete, and the failing one is listed as stopped once past its limit
