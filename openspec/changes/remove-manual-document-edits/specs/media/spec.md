## MODIFIED Requirements

### Requirement: Media placement gate
The system MUST refuse a generated document that places media the run was not offered, an image with empty alt text, or a `media:` reference outside image syntax. The reviewer judges each placed image by its alt text and caption for fit and exposure.

#### Scenario: Unoffered media
- **WHEN** the writer places a media id it was never offered
- **THEN** the emit is refused and the writer is told to place only offered media

### Requirement: Media in published documents
The system SHALL commit each image a published document places beside the Markdown as `<file stem>-media/<id>-v<version>.<ext>`, and link it by that relative path; publishing MUST be refused when a placed item was deleted, or its bytes are missing, or the audience the document was written for may no longer see it.

#### Scenario: Publishing a document with a screenshot
- **WHEN** `docs/exporting-invoices.md` places media `med_0123456789ab` at `content_version` 2
- **THEN** the pull request also adds `docs/exporting-invoices-media/med_0123456789ab-v2.png`

#### Scenario: Image relabelled away
- **WHEN** a placed image is relabelled so the document's external audience may not see it
- **THEN** publishing is refused naming the media
