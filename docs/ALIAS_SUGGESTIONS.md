# Alias suggestions

Open **Names & aliases → AI suggestions**. AI proposes alternative
names for existing concepts; names recognized in statement text support discovery
without creating explicit entity-to-statement links.

Ingestion can propose an alias when the supplied prose establishes equivalence,
for example “single sign-on (SSO)”. Suggestions retain the exact quoted evidence,
the original source text, target concept, reason, and possible ambiguity. A
substring check verifies the quote came from the input; review decides
whether it actually supports equivalence. Ingestion puts its suggestions in a
separate submitted draft titled after the knowledge draft, so the knowledge can
be reviewed and applied without waiting for the alias decisions.

To scan existing knowledge, expand **Discover aliases in existing statements**,
search for statements, select up to 50 across searches, and start discovery.
Manual scans use the Alias discovery model configuration; proposals made during
ingestion use the Ingestion model configuration. Both support Claude and OpenAI
and their configured reasoning effort.

The scan uses one structured model request with existing names and descriptions
as context. It creates a normal submitted draft containing the suggestions.
Names or source changes during the scan prevent stale suggestions from landing.
No live knowledge is changed by discovery. Invalid individual proposals are
skipped with their reasons while valid proposals remain available for review.
Evidence outside the selected statements aborts the scan without saving a draft.

## Review

Human writers and administrators can accept, reject, or assign each suggestion
to a different concept. The screen shows current names and examples of statements
using the proposed alias. Retargeting preserves the AI's original proposal and
source evidence. Every decision records its actor and time.

Acceptance adds only the selected alias and triggers normal discovery of older
statements. It does not approve other operations in the draft. Changes to the
target concept, its names, the alias's current owner, or supporting source text
are checked again before acceptance. Inspect and refresh a suggestion after a
vocabulary change. If the supporting statement changed, reject the old suggestion
and scan the current statement.

Each suggestion is decided individually. By default a person decides: the
draft reviewer gives such drafts advisory assessments only, even in **Review
and apply**. With **Reviewer decides alias suggestions** on (**Settings →
Draft review**, off by default), the reviewer, on a server model or an
external agent, accepts or rejects each suggestion with a quote from its
source text and a reason, recorded on the decision with the reviewer as
actor; see [Draft review](DRAFT_REVIEW.md#alias-decisions). In **Review and
apply**, the reviewer also settles a suggestion that went stale: it rejects one
whose supporting statement changed, and refreshes one whose names changed and
reviews the draft again. Pending
suggestions must be individually decided before applying, rejecting, or
withdrawing their draft. Drafts containing only alias suggestions close after
the final decision. Mixed drafts, which ingestion no longer produces, remain
available for normal review.

Accepted and rejected records remain visible through the status filter. Replaying
a draft skips these records, so it cannot recreate an alias removed after its
original acceptance. If acceptance commits but draft finalization is interrupted,
the screen offers **Recover accepted decision**. Recovery records the completed
acceptance without repeating the name mutation.

## Configuration and API

**Settings → Models → Alias discovery** selects Claude or OpenAI, each with its own
remembered model and reasoning effort. **Alias discovery limits** configures the
output-token budget, request timeout, retry count, and maximum input size. The
scan shares the existing AI concurrency budget. These settings are stored in
Mycelium and included in configuration backups; no new environment variables
configure this action. Ingestion uses its own model selection.

- `GET /api/alias-suggestions?status=pending|accepted|rejected|all` lists records.
- `POST /api/alias-suggestions/scan` accepts `{"statement_ids": ["stm_..."]}`
  and returns `suggestions` plus `skipped` proposals with their reasons.
- `POST /api/alias-suggestions/{draft_id}/{operation_ref}/review` accepts an
  `action` of `accept`, `reject`, `retarget`, or `refresh`, the displayed
  `expected_revision`, and `entity_id` for retargeting.

Reading requires reader access. Scanning requires a real writer or administrator.
Individual decisions additionally require a human account. Stale review requests
return HTTP 409. Generic draft payload editing and operation deletion cannot
change or remove suggestion evidence or decisions.
