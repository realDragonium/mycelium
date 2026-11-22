## ADDED Requirements

### Requirement: A profile can write from every statement
A profile's audience MAY be `*`. Runs, reviews, plans, freshness checks and the downloaded website of such a profile SHALL read every statement and media item, whatever its audience label. `*` SHALL NOT be listed among the audiences, and MUST NOT be accepted as an audience id, an include or a label.

#### Scenario: A statement labelled for a retired audience
- **WHEN** a statement is labelled only for an audience that has since been retired and a profile's audience is `*`
- **THEN** a run of that profile may read and cite the statement

#### Scenario: A relabel does not make the document out of date
- **WHEN** a statement a document of such a profile cites is relabelled without its text changing
- **THEN** the document stays current

#### Scenario: The value is not an audience id
- **WHEN** an administrator creates an audience with the id `*`
- **THEN** the request is refused
