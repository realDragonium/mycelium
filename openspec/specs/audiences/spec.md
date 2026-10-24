# audiences Specification

## Purpose
Audiences say which knowledge documentation may draw on: each statement carries an audience label decided by an AI labeller or a curator, external grants can wait for curator confirmation, and documentation runs read only what their audience may see. Audiences do not limit what users or tokens read.

## Requirements

### Requirement: Seeded audiences
The system SHALL seed four audiences once, on an instance that has never had an audience: `internal-technical`, `internal-non-technical` (both internal), `external-technical` and `external-non-technical` (both external). Seeding SHALL NOT run again once any audience history exists, so a retired seeded audience is never recreated.

#### Scenario: Fresh instance
- **WHEN** the server starts on a data directory with no audience history
- **THEN** `GET /api/audiences` lists the four seeded audiences
- **AND** `internal-technical` includes the other three, and `internal-non-technical` and `external-technical` each include `external-non-technical`

#### Scenario: Retired seeded audience stays retired
- **WHEN** an administrator retires `external-technical` and the server restarts
- **THEN** `external-technical` is still retired

### Requirement: Seeded includes backfilled once
The system SHALL, on startup, give each live seeded audience whose current saved text has no includes field the seeded includes (restricted to audiences that are live), once.

#### Scenario: Instance seeded before includes existed
- **WHEN** an instance whose seeded audiences were saved without an includes field starts
- **THEN** each of them gains its seeded includes as a new version
- **AND** a later restart does not change them again

### Requirement: Audience fields and limits
An audience SHALL have an immutable id, a name of 1 to 100 characters, a scope of `internal` or `external`, a description of 1 to 4000 characters and at most 50 included audience ids. A created audience's id SHALL be the supplied id, which MUST match lowercase letters and digits separated by single dashes and be at most 64 characters, or else a slug of its name.

#### Scenario: Id derived from the name
- **WHEN** an administrator creates an audience named "Billing partners" without an id
- **THEN** its id is `billing-partners`

#### Scenario: Invalid id
- **WHEN** an administrator creates an audience with id `Billing_Partners`
- **THEN** the request is refused as invalid

### Requirement: Only administrators configure audiences
The system SHALL let only an administrator create (`POST /api/audiences`), edit or restore (`PUT /api/audiences/{audience_id}`) and retire (`POST /api/audiences/{audience_id}/retire`) audiences, and SHALL refuse anyone else with 403. Any signed-in caller MAY read `GET /api/audiences`, whose `can_configure` is true only for an administrator.

#### Scenario: Writer tries to create an audience
- **WHEN** a writer posts to `/api/audiences`
- **THEN** the response is 403

### Requirement: Audience edits keep history and use revisions
Every create, edit, retirement and restore SHALL append a new version of the audience and keep earlier versions. An edit or retirement MUST carry the audience's current `revision`; a stale revision SHALL be refused with 409. An edit that changes nothing SHALL NOT add a version.

#### Scenario: Concurrent edit
- **WHEN** two administrators load audience version 3 and both save
- **THEN** the first save creates version 4
- **AND** the second is refused with 409 "This audience changed. Reload before saving."

### Requirement: Audience ids and names are unique
Creating an audience whose id exists or ever existed SHALL be refused with 409, and creating or renaming an audience to a name another live audience already has, compared case-insensitively, SHALL be refused with 409.

#### Scenario: Reusing a retired id
- **WHEN** an administrator creates an audience with the id of a retired audience
- **THEN** the request is refused with 409 and the message suggests restoring it

### Requirement: Retired audiences can be restored
Saving a retired audience at its id SHALL restore it as live with the saved text. `GET /api/audiences` SHALL list retired audiences with `retired: true` and their last live name, scope, description and includes.

#### Scenario: Restore
- **WHEN** an administrator saves a retired audience with its current revision
- **THEN** the audience is live again under the same id

### Requirement: Retirement guards
The system SHALL refuse to retire an audience that a documentation profile explicitly writes for, naming those profiles, and SHALL refuse to retire the last live internal audience or change it to external.

#### Scenario: Profile still writes for the audience
- **WHEN** an administrator retires `external-technical` while the profile "Integrator guides" chose it
- **THEN** the request is refused with 400 naming "Integrator guides"

#### Scenario: Last internal audience
- **WHEN** only one internal audience is live and an administrator changes its scope to external
- **THEN** the request is refused with 400

### Requirement: Includes rules
An audience's includes SHALL name only other live audiences. An external audience MUST NOT include an internal audience, and no audience may include itself directly or through others. Violations SHALL be refused with 400.

#### Scenario: External including internal
- **WHEN** an administrator sets `external-technical` to include `internal-non-technical`
- **THEN** the request is refused with 400

#### Scenario: Cycle
- **WHEN** `external-technical` includes `external-non-technical` and an administrator sets `external-non-technical` to include `external-technical`
- **THEN** the request is refused with 400

### Requirement: Inclusion is transitive visibility
An audience SHALL see every statement its label grants to the audience itself or to any live audience it includes, directly or through other included audiences.

#### Scenario: Grant to the narrowest audience
- **WHEN** a statement about exporting invoices is labelled for `external-non-technical` only
- **THEN** all four seeded audiences can see it

### Requirement: Unlabelled statements are internal only
A statement without a label SHALL be visible to every internal audience and to no external audience.

#### Scenario: New statement before labelling
- **WHEN** a statement has just been written and has no label yet
- **THEN** an external documentation run cannot see it
- **AND** an internal one can

### Requirement: Default audience
The default audience SHALL be `internal-technical` while it is live, otherwise the first live internal audience. A documentation profile without a chosen audience SHALL write for the default; a profile whose chosen audience is retired SHALL resolve to no audience, so its runs refuse rather than widen (see the `documentation` capability).

#### Scenario: Default retired
- **WHEN** `internal-technical` is retired and `internal-non-technical` is live
- **THEN** `GET /api/audiences` marks `internal-non-technical` as `default: true`

### Requirement: Audience overview counts
`GET /api/audiences` SHALL report per audience `visible_statements` (statements it may see now), `unlabelled_statements`, `pending_statements` (grants waiting for confirmation), the profiles writing for it and whether it is the default, plus totals `statements`, `unlabelled` and `pending`, and the labelling status.

#### Scenario: Waiting grants counted
- **WHEN** three statements have a grant to `external-technical` waiting for confirmation
- **THEN** that audience's `pending_statements` is 3 and they are not counted in its `visible_statements`

### Requirement: Statement labels
Every statement label SHALL record the granted audiences, its source (`ai` or `curator`), a reason, the model for AI labels, when and by whom it was decided, and when relevant its waiting grants (`pending`), `text_changed_at`, `narrowed` and `spot_check`. `GET /api/statements/{statement_id}/audiences` SHALL return the label, whether the statement is queued, and per live audience whether it is visible and whether a grant to it is pending.

#### Scenario: Reading a label
- **WHEN** a writer opens `GET /api/statements/st_1/audiences` for a statement labelled by the AI
- **THEN** the response has `label.source: "ai"`, the reason, the model and `can_curate: true`

### Requirement: New statements are queued for labelling
Writing a new statement SHALL queue it for audience labelling. While automatic labelling is on (the `automatic` setting of the audience labelling limits, default on), a background worker SHALL label queued statements in batches, up to three at once outside the shared model concurrency, polling every 30 seconds and waking on demand. `MYCELIUM_DISABLE_AUDIENCE_WORKER=1` SHALL stop the worker.

#### Scenario: Automatic labelling
- **WHEN** a statement is created while automatic labelling is on and the labelling model has credentials
- **THEN** it is labelled by the worker without anyone starting a backfill

#### Scenario: Automatic labelling off
- **WHEN** automatic labelling is off
- **THEN** new statements stay queued and unlabelled until a backfill runs

### Requirement: Labelling batch contract
The labeller SHALL send each batch (`batch_size`, default 25, at most 100) with each statement's kind, text, mentioned concepts and their descriptions, and for an edit its previous text and audiences, plus every live audience's id, name, scope, description and includes. Audience ids that are not live SHALL grant nothing. A statement whose text changed during the call SHALL stay queued, and one the model returned no label for SHALL count as a failed attempt.

#### Scenario: Invented audience id
- **WHEN** the model labels a statement with `partners-only`, which is not a live audience, and `external-technical`
- **THEN** the stored label grants only `external-technical`

### Requirement: Labelling failures back off
A failed batch SHALL leave its statements unlabelled and retry each with exponential backoff starting at one minute; after 5 failed attempts a statement SHALL wait for the next backfill or edit. Without provider credentials for the labelling action the worker SHALL not attempt anything and SHALL leave the queue untouched; a spent budget SHALL leave the batch due without counting a failure.

#### Scenario: Provider error
- **WHEN** a labelling call fails
- **THEN** the batch's statements stay unlabelled with one attempt recorded and are retried no earlier than a minute later
- **AND** `GET /api/audiences/labelling` reports the last error

### Requirement: Backfill
`POST /api/audiences/labelling/backfill` SHALL require a real administrator, queue every unlabelled statement (and, with `relabel_ai: true`, every AI-labelled statement), never queue curator-labelled statements, and drain the queue even while automatic labelling is off until no statement it queued has attempts left, also after a server restart. It SHALL return `started_at` and `queued`.

#### Scenario: Relabel AI labels
- **WHEN** an administrator starts a backfill with `relabel_ai: true`
- **THEN** unlabelled and AI-labelled statements are queued
- **AND** curator-labelled statements are not

#### Scenario: Restart with automatic labelling off
- **WHEN** the server restarts while a backfill started with automatic labelling off still has queued statements
- **THEN** the worker keeps labelling them, and stops draining once none it queued has attempts left

### Requirement: Labelling status survives restarts
`GET /api/audiences/labelling` SHALL report statement, AI-label, curator-label, unlabelled, queued and failed counts, the last error, total label cost, `automatic`, `confirm_external_grants`, and the labelling provider and model. While a queued statement has attempts left it SHALL include `backfill` (`started_at`, `queued`, `labelled`, `cost_usd`), counted from the oldest waiting statement's queueing and read from the queue, so it survives restarts.

#### Scenario: Restart mid-backfill
- **WHEN** the server restarts while a backfill has 40 statements left
- **THEN** `GET /api/audiences/labelling` still shows the backfill with its labelled count and cost

### Requirement: Curator labels
A real writer or administrator SHALL be able to set a curator label with `PUT /api/statements/{statement_id}/audiences` (at most 50 live audience ids, reason up to 500 characters; unknown audiences refused with 400). The AI labeller SHALL never replace a curator label. `DELETE /api/statements/{statement_id}/audiences` ("Hand back to AI") SHALL remove the label and queue the statement. Drafters and readers SHALL be refused with 403.

#### Scenario: AI does not overwrite a curator
- **WHEN** a curator labels a statement for internal audiences only and a relabel backfill runs
- **THEN** the curator label is unchanged

### Requirement: Text edits and labels
Changing a statement's text SHALL drop its AI label, withdraw its waiting grants, and queue it again carrying the previous text, the previous label's audiences (waiting grants included) and its confirmed grants. Several edits before the relabel SHALL keep the label from before the first edit. A curator label SHALL be kept but flagged as text changed until a curator confirms it (`POST /api/statements/{statement_id}/audiences/confirm`) or hands it back to the AI.

#### Scenario: Editing an AI-labelled statement
- **WHEN** the text of a statement labelled for `external-technical` is edited
- **THEN** the statement is visible to internal audiences only until it is relabelled

#### Scenario: Editing a curator-labelled statement
- **WHEN** the text of a curator-labelled statement is edited
- **THEN** the label still applies and shows `text_changed_at`
- **AND** confirming it clears the flag and records the confirming curator

### Requirement: Relabels after edits keep audiences unless narrowing is explained
When an edited statement's relabel would take it away from an audience that could see the previous label, the system SHALL apply the narrower label only if the model gave a narrowing reason, and SHALL then record the previous audiences, the audiences that lost the statement and the reason in `narrowed`. Without a narrowing reason it SHALL keep the previous audiences and say so in the label's reason.

#### Scenario: Narrowing without a reason
- **WHEN** a statement visible to `external-non-technical` is edited and the relabel grants only `internal-technical` with an empty narrowing reason
- **THEN** the stored label keeps `external-non-technical`
- **AND** the reason says the previous audiences were kept because no reason to narrow was given

### Requirement: Deleting or merging removes labels
Deleting a statement, or merging it away, SHALL delete the removed statement's label (waiting grants included) and its queue entry. The surviving statement of a merge SHALL keep its label.

#### Scenario: Delete
- **WHEN** an administrator deletes a labelled statement
- **THEN** no label or queue row remains for it

### Requirement: Labelled statement listing
`GET /api/audiences/statements` SHALL list statements filtered by label state (`unlabelled`, `ai`, `curator`, `text_changed`, `pending`, `queued`) and by `visibility` (`visible` or `hidden`) to a chosen live `audience`, newest first, with `offset` and `limit` (default 50, 1 to 200) and the total. Filtering by visibility without a live audience SHALL be refused with 400.

#### Scenario: Hidden from an external audience
- **WHEN** a curator lists `audience=external-technical&visibility=hidden`
- **THEN** the response lists the statements that audience cannot see, including unlabelled ones

### Requirement: Confirming external grants
While **Confirm external grants** is on (`confirm_external_grants`, default on), an AI grant that would make a statement visible to an external audience that could not see it before SHALL be stored as waiting (`pending`) rather than granted. Grants to internal audiences, and external grants the statement could already see, SHALL apply at once, and an external audience the AI no longer grants SHALL be withdrawn at once.

#### Scenario: New external grant waits
- **WHEN** the AI labels a new statement about SSO setup for `external-technical`
- **THEN** the label lists `external-technical` under `pending`
- **AND** an `external-technical` documentation run cannot see the statement

### Requirement: Waiting grants keep internal readers
While a grant waits, the label SHALL grant directly the narrowest internal audiences that include the waiting audience (and keep any audience that already saw the statement), so internal audiences do not lose the statement. Confirming the grant SHALL drop those internal grants that now see the statement through it.

#### Scenario: Internal audiences still see a waiting statement
- **WHEN** a grant to `external-non-technical` waits on a new statement
- **THEN** `internal-non-technical` and `internal-technical` can see the statement
- **AND** `external-technical` cannot

### Requirement: Switching confirmation off
Turning `confirm_external_grants` off SHALL make later AI external grants apply at once, and SHALL leave grants already waiting as waiting until a curator decides them.

#### Scenario: Switch off
- **WHEN** confirmation is turned off while two grants wait
- **THEN** newly labelled statements are granted external audiences directly
- **AND** the two waiting grants remain waiting

### Requirement: Deciding waiting grants
A real writer or administrator SHALL be able to confirm or reject a live audience's waiting grants with `POST /api/audiences/{audience_id}/pending/decide` (1 to 2000 statement ids, `decision` `confirm` or `reject`), which returns how many were pending. A confirmation SHALL make the grant effective and record who confirmed it and when, keeping the label an AI label. A rejection SHALL turn the label into a curator label without that audience, so the AI does not grant it again.

#### Scenario: Confirm
- **WHEN** a curator confirms the `external-non-technical` grant on a statement
- **THEN** the statement becomes visible to `external-non-technical` and `external-technical`
- **AND** the label records the confirmation and its curator

#### Scenario: Reject
- **WHEN** a curator rejects the grant
- **THEN** the label's source becomes `curator` and a later relabel does not grant it

### Requirement: Waiting grants grouped by concept
`GET /api/audiences/{audience_id}/pending` SHALL list a live audience's waiting grants grouped under the concept each statement names that has the most waiting statements (statements naming no concept grouped last), with each statement's text, kind, the AI's reason, model, time and concepts, plus the total, `sample_size` and `min_sample_precision_percent`.

#### Scenario: Grouping
- **WHEN** five waiting statements mention "Invoices" and two of them also mention "Exports"
- **THEN** all five appear once, under "Invoices"

### Requirement: Stratified sample of waiting grants
`GET /api/audiences/{audience_id}/pending/sample` SHALL draw a fresh random sample of the audience's waiting grants of `sample_size` (default 50, at most 500), allocated across the concept groups in proportion to their size by largest remainder.

#### Scenario: Proportional sample
- **WHEN** an audience has 300 waiting grants in two concept groups of 200 and 100 and the sample size is 50
- **THEN** the sample holds 33 grants from the first group and 17 from the second

### Requirement: Accepting the rest after a sample
`POST /api/audiences/{audience_id}/pending/accept-rest` with the sample's ids (1 to 500) SHALL require at least one decided grant among them, confirm every grant still waiting for the audience, record on each the sample's decided size and precision (share confirmed), and return `accepted`, `sample_size`, `precision` and `below_threshold` (precision under `min_sample_precision_percent`, default 90). Rejections in the sample SHALL stand.

#### Scenario: Accept after a sample
- **WHEN** a curator decides 50 sampled grants, confirming 47, and accepts the rest
- **THEN** every remaining waiting grant is confirmed with precision 0.94 recorded
- **AND** the three rejected grants stay rejected

#### Scenario: Nothing decided
- **WHEN** a curator accepts the rest without deciding any sampled grant
- **THEN** the request is refused with 400

### Requirement: Confirmed grants after an edit
When an edited statement's relabel still grants an external audience a curator had confirmed, and reveals it to no external audience the confirmed grants did not, that grant SHALL stay in force and confirmed; any other external grant SHALL wait as usual. Such a statement SHALL appear, still visible, in `GET /api/audiences/spot-checks` with the text the grant was confirmed for, the new text and the kept audiences. With confirmation off nothing is kept for a spot check.

#### Scenario: Edit keeps a confirmed grant
- **WHEN** a statement with a confirmed `external-technical` grant has a rate limit number changed and the relabel grants `external-technical` again
- **THEN** the grant stays in force without waiting
- **AND** the statement is listed in spot checks with its old and new text

#### Scenario: Edit reveals to a new external audience
- **WHEN** the relabel of an edited statement confirmed only for `external-technical` also grants `external-non-technical`
- **THEN** every external grant in the relabel waits for confirmation

### Requirement: Deciding spot checks
`POST /api/statements/{statement_id}/audiences/spot-check` with `decision` `confirm` SHALL confirm the kept grants for the new text by the calling curator; `narrow` SHALL withdraw the kept grants, make the label a curator label and still grant the narrowest internal audiences that saw the statement through them. It SHALL require a real writer or administrator and return `decided` 1, or 0 when nothing waited.

#### Scenario: Narrow
- **WHEN** a curator narrows a spot-checked statement
- **THEN** external audiences no longer see it, internal audiences still do, and the AI does not grant it again

### Requirement: Audience boundary
Reading as an audience, the system SHALL expose only statements it may see, statement links whose ends and `when` statements it may see, and concepts a visible statement mentions. Internal audiences SHALL see those concepts' descriptions, names and links; external audiences SHALL see no concept descriptions or links and only the names visible statements were matched through. Search SHALL rank only visible statements, and the visible set SHALL be fixed when a read starts.

#### Scenario: Internal codename stays hidden
- **WHEN** a concept "Invoices" has an internal alias "Ledger-X" that no externally visible statement was matched through
- **THEN** an external audience sees the concept as "Invoices" without "Ledger-X", its description or its concept links

### Requirement: Media audience labels bound documentation
Media items SHALL carry their own curator-decided audience label under the same visibility rules (unlabelled media is internal only, inclusion applies), and a media item SHALL be offered to a documentation run only when its own label allows the run's audience, whatever the label of the statement it is attached to; see the `media` capability.

#### Scenario: Unlabelled media and an external run
- **WHEN** an external documentation run writes about a statement with unlabelled media attached
- **THEN** the run is not offered the media

### Requirement: Audiences do not scope principals
Users, tokens and OAuth grants SHALL carry no audience: every principal reads what its role allows, and audiences bound only documentation runs, plans and documents.

#### Scenario: Reader and internal-only knowledge
- **WHEN** a reader token searches for a statement visible only to internal audiences
- **THEN** the statement is returned
