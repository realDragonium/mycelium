## ADDED Requirements

### Requirement: Publication is one-way
The system SHALL treat its own revision as the only source of a document's text: a revision always starts from the revision stored in Mycelium, and nothing is read back from GitHub into a document. Publication SHALL write the selected revision over whatever the file holds, on the open pull request branch or, when no pull request is open, in a new pull request from the base branch, including text someone changed on GitHub by hand.

#### Scenario: Reviewer edited the PR branch
- **WHEN** someone commits a change to `docs/exporting-invoices.md` on the document's open pull request branch and a writer publishes the next revision
- **THEN** the file on that branch holds the revision's text and the reviewer's change is gone from it

#### Scenario: File edited on the base branch after merge
- **WHEN** the pull request was merged, someone edits the file on the base branch, and a writer revises and publishes the document
- **THEN** the revision starts from the text in Mycelium, and a new pull request replaces the file with it

### Requirement: Publication keeps a deleted file deleted and makes no empty commit
Publication MUST be refused when the file was deleted in the open pull request, and SHALL make no commit when the file on the open pull request branch already holds the revision's text.

#### Scenario: File deleted in the open pull request
- **WHEN** someone deletes the file on the open pull request branch and a writer publishes
- **THEN** publication is refused asking to restore the file there or close the pull request

#### Scenario: Publishing the same revision again
- **WHEN** a writer publishes a revision whose text the open pull request branch already holds
- **THEN** no commit is made and the result names the same pull request

## MODIFIED Requirements

### Requirement: Documentation run roles
The system MUST require a real writer or admin role (a drafter does not qualify) to request, revise, retry or publish documents and to start, approve, retry or dismiss plan items; any authenticated caller may read runs, documents, revisions, plans, destinations and the maintenance feed, subject to audience scoping.

#### Scenario: Drafter requests a document
- **WHEN** a drafter calls `request_documentation`
- **THEN** the call is refused with a role error and no run is created

### Requirement: Agent runs
The system SHALL have a run with provider `agent` written by an outside agent (see agent-tasks), needing a model only when the server reviews it; it is the default while documentation is set to External agent, and `list_documentation_models` lists `agent` while documentation is set to External agent.

#### Scenario: Explicit server provider while External agent is selected
- **WHEN** documentation is set to External agent and a writer requests `provider="claude"`
- **THEN** the run is written on the server with the Claude documentation model

### Requirement: Run listing and detail
The system SHALL list the newest 100 runs through `list_documentation_runs` with `draft_chars` instead of draft text, and return one run through `get_documentation_run(run_id)` (MCP) or `GET /api/documentation/runs/{run_id}` including `draft_title` and `draft_body` of a refused draft, `error`, `summary`, `review_notes`, the captured `profile_snapshot` and `retryable`; an unknown run id is an error (404 over HTTP).

#### Scenario: Reading a refused run
- **WHEN** a run's document failed review
- **THEN** `get_documentation_run` returns the refused `draft_title` and `draft_body` beside the findings in `error`

### Requirement: Revising a document
The system SHALL expose `revise_document(document_id, expected_revision, prompt, provider?, update_sources?)`, advertised over MCP, that starts a run revising exactly that revision under the document's own profile and type; it requires a nonblank prompt unless `update_sources` is true, and a stale `expected_revision` is refused (409 over HTTP).

#### Scenario: Stale revision
- **WHEN** a writer revises with `expected_revision` 2 while the document is at revision 3
- **THEN** the request is refused asking to reload, and no run is created

### Requirement: Recovering failed runs
The system SHALL, from the 60-second maintenance sweep, retry each finished run that wrote nothing of an `ai`-recovery profile as a writer's retry would, briefed with the review's notes when the review refused it, within the active-run limit. After `run_retries` automatic retries (default 2) the run is given up with `recovery` `gave_up` and a `recovery_note` giving the last reason; a person's retry starts the count again.

#### Scenario: Refused revision retried with notes
- **WHEN** the review refuses an automatic revision of an `ai`-recovery profile
- **THEN** a later sweep starts a retry briefed with the review's findings, which the document's maintenance entry follows

#### Scenario: Run finished before the upgrade
- **WHEN** a profile's recovery is set to `ai` after an upgrade
- **THEN** runs that wrote nothing before the upgrade are not retried

#### Scenario: Given up after the attempts
- **WHEN** the second automatic retry with `run_retries` at 2 also writes nothing
- **THEN** no further retry starts and the run shows `recovery` `gave_up` with the reason

## REMOVED Requirements

### Requirement: Manual edits are grounded and reviewed
**Reason**: A document is written from the statements in the knowledge base; text a person changes by hand can disagree with them. A document's text now changes only through a writer run: a request, a revision, a retry or an automatic revision.
**Migration**: Change the statements, or ask for a revision with a note saying what to change (`revise_document`, or **Create revision** in the web app). `POST /api/documentation/documents/{id}/edits`, `POST /api/documentation/runs/{run_id}/edits` and `POST /api/documentation/preview` no longer exist. Runs and revisions earlier manual edits created stay stored and are treated like any other; nothing recognises them.

### Requirement: Document edits over MCP
**Reason**: Manual edits are removed, so `edit_document` and its HTTP route `POST /edit-document` are gone.
**Migration**: Use `revise_document` with a prompt describing the change.

### Requirement: Publication does not overwrite edits made on GitHub
**Reason**: Publishing is one-way; see "Publication is one-way". Mycelium's text is the only source, so a publish overwrites the file.
**Migration**: Do not edit a published file on GitHub: the next publish replaces it. Change the statements or ask for a revision instead. A file deleted in the open pull request is still refused.

### Requirement: Revisions start from the published copy
**Reason**: Nothing is read back from GitHub into a document; see "Publication is one-way".
**Migration**: `start_from_destination` is no longer a parameter of `revise_document` or of `POST /api/documentation/documents/{id}/revisions`, runs no longer report `revision_base`, and no request is refused with code `both_sides_edited`. Stored values of earlier runs and documents are ignored.
