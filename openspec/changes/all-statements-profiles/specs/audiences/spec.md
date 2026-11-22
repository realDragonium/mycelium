## ADDED Requirements

### Requirement: A profile can write from every statement
A profile's audience MAY be `all-statements`. Runs, reviews, plans, freshness checks and the downloaded website of such a profile SHALL read every statement and media item, whatever its audience label. `all-statements` SHALL NOT be listed among the audiences, and creating an audience with that id MUST be refused.

#### Scenario: A statement labelled for a retired audience
- **WHEN** a statement is labelled only for an audience that has since been retired and a profile's audience is `all-statements`
- **THEN** a run of that profile may read and cite the statement

#### Scenario: A relabel does not make the document out of date
- **WHEN** a statement a document of such a profile cites is relabelled without its text changing
- **THEN** the document stays current

#### Scenario: The id is reserved
- **WHEN** an administrator creates an audience named "All statements" without giving an id
- **THEN** the request is refused and names the reserved id
