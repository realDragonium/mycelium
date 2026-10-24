---
name: mycelium-documentation
description: Have a Mycelium server write, revise and maintain documents from its knowledge base. The server writes; this skill helps choose the writing profile, document type and concept anchor, starts runs with request_documentation or revise_document, follows them with get_documentation_run, retries refused runs with the review's notes, brings out-of-date documents current, and works the documentation plan (which documents a profile's audience needs). Use when someone asks for a knowledge-base article, how-to, reference or troubleshooting page from product knowledge, or to update, retry or plan such documents. Needs a real writer or admin connection to start runs.
---

# Documents from a Mycelium server

The server writes the documents. A documentation run reads the knowledge
base through its profile's audience boundary, writes from the profile's
guidance and template, has a separate review conversation check the result,
and stores it as a generated document with revision history
(`docs/DOCUMENTATION_MODELS.md`). This skill asks for runs, follows them and
reports what they produced. **Never write the document yourself**, from the
code or from memory: a missing fact is a knowledge gap to fill first.

## Before you start

- Starting runs (`request_documentation`, `revise_document`) needs a **real**
  writer or admin. A drafter or reader sees neither; say so and stop.
  Readers can still follow runs and read documents.
- Several steps below are HTTP routes, not MCP tools. Call them with the same
  base URL and a bearer token for a real writer
  (`-H "Authorization: Bearer $MYCELIUM_TOKEN"`). When you have no token, the
  same action is a button in **Documents** (`#/documentation`); tell the
  operator which.
- Every run costs model spend on the server and counts against its
  active-run limit. A run over that limit is `queued` with a
  `queue_position` and starts by itself when one finishes; do not start it
  again.

## Choose profile, type and anchor

- **Profile** (`guideline_set`) decides the guidance, the templates and the
  **audience** the document is for, which decides what it may draw on.
  `GET /api/documentation/profiles` lists them with `effective_audience`,
  templates, `ready` and `issues`. Pass one when the request or the operator
  names it, or the audience makes it clear (a customer-facing page needs a
  profile that writes for an external audience); otherwise the run chooses
  among the ready profiles. The starter profile is `kb-authoring`.
- **Type** (`document_type`) is a template of that profile; the starter
  profile has `tutorial`, `how-to`, `reference`, `explanation` and
  `troubleshooting`. Pass it when the request makes it clear: "how do I"
  is a how-to, "what are the limits" a reference, "why does" an
  explanation, "it fails when" troubleshooting.
- **Anchor** (`anchor_entity_id`) names the one concept the document is
  about, found with `search_entities` / `list_entities`. With a profile and
  a type, it gives the document a stable identity: a later request for the
  same concept, profile and type revises that document instead of creating
  another. Anchor every document that is about one concept; leave it out for
  a document that spans several.

Without an anchor, `request_documentation` always creates a new document. To
change an existing one, revise it.

## Write a new document

1. Look for an existing document on the topic:
   `GET /list-generated-documents`. If one exists, revise it instead.
2. Write the prompt: the topic, who reads it and what they need to do or
   understand. Do not paste guidance or templates; the profile has them.
3. `request_documentation(prompt=…, guideline_set=…, document_type=…,
   anchor_entity_id=…)` with only the parts you chose. It returns the run.
4. Follow the run (below).

## Follow a run

Poll `get_documentation_run(run_id)` until `status` is neither `queued` nor
`running`. Runs take several minutes; poll every minute or so, not faster.
`waiting_for_agent` means documentation is set to External agent: the run
waits until an outside agent claims and writes it (`agent_task` shows who
holds it), which the `mycelium-agent-tasks` skill covers. Do not poll for
it; tell the operator.
`summary` reports what the run is doing while it runs, then its turns,
tokens, the statements it retrieved and cited, and the gaps it filed.

| `status` | Report |
|---|---|
| `document_written` | `get_generated_document(document_id)`: title, id, `current_revision`, audience, and the body or a summary of a long one |
| `nothing_written` | `error`. When the review refused the document, `summary.review_findings` lists the failed findings and `draft_title` / `draft_body` hold the refused text; summarize the findings against it |
| `failed` | `error` |
| `document_superseded` | a later run replaced this document; follow that one |

Facts the knowledge base could not supply are filed as knowledge gaps during
the run. Name them so the operator can fill them in the knowledge base (the
`mycelium-draft` or `mycelium-authoring` skill) before the next run.

## Retry

`retryable` on the run says whether it can start again as it was: it wrote
nothing and was not a manual edit.

- **Retry**: `POST /api/documentation/runs/{run_id}/retry` with
  `{"with_review_notes": false}` starts the same request again. Use it after a
  failure that has gone away (a provider error, a limit since raised).
- **Retry with notes**: `{"with_review_notes": true}` briefs the new writer
  with the review's findings. Use it when the review refused the document for
  something the writer can fix. The notes go to the writer only; the next
  review judges the unchanged request. The new run lists them in
  `review_notes`.

Do not retry a refusal caused by missing knowledge: fill the gap first.

## Revise a document

1. `get_generated_document(document_id)` for `current_revision`, `stale` and
   `pull_request`.
2. `revise_document(document_id, expected_revision=<current_revision>,
   prompt=<the change>)`.
3. Follow the run. If another revision landed first, the call is refused:
   read the document again and retry once with the new revision.

**Out of date.** When `stale.status` is `out_of_date`, statements the
document cites were edited, deleted, merged away or are no longer visible to
its audience; `stale.changes` shows old and new text. Revise with
`update_sources=true` (no prompt needed) to brief the run with exactly those
changes.

**Edited on GitHub.** A published document can be edited on its pull
request branch or after merge. A revision then starts from the published
text and keeps those edits (`revision_base: destination`). If the document
also has a revision here that was never published, the call is refused.
Relay the choice to the operator: keep the GitHub edits with
`start_from_destination=true`, or undo them on GitHub. Do not choose for them.

## Plan which documents an audience needs

The planner proposes documents for one profile's audience; nothing is
written until an item is approved (`docs/DOCUMENTATION_PLANNING.md`).

1. `GET /api/documentation/plans/{guideline_set}` shows the latest plan:
   `items` (each `create` or `update`, with title, type, concept, rationale,
   priority and the statements it would draw on), `stale` (out-of-date
   documents), `coverage` (concepts with many visible statements and no
   document), `uncovered_statements` and `uncovered` (statements the
   audience may see that no document of the profile cites), and
   `replan_hint` when enough new knowledge became visible.
2. To plan again, `POST /api/documentation/plans/{guideline_set}` (one model
   call). Each plan is offered a batch of the uncovered statements and
   places them in updates of existing documents or in new ones; approving
   such an update briefs its revision with the statements to add. Re-planning
   is manual unless the profile's `planning` policy is `propose` or `write`
   (see Maintenance).
3. Present the items to the operator with your view of each. Approving starts
   a documentation run per item, so the operator decides which.
4. Approve the chosen ones with `POST /api/documentation/plan-items/approve`
   and `{"item_ids": […]}`, at most `approve_batch` at a time; each result
   carries its run or the reason it could not start. Follow the runs as
   above. `POST /api/documentation/plan-items/{item_id}/retry` (same body as
   a run retry) restarts an item whose run wrote nothing;
   `POST /api/documentation/plan-items/{item_id}/dismiss` drops a proposal so
   later plans do not offer it again, and
   `POST /api/documentation/plans/{guideline_set}/uncovered/{statement_id}/dismiss`
   stops a statement the profile should never document counting as
   uncovered. Dismiss only on the operator's word.

## Maintenance

Each profile has a maintenance policy: `manual` (out-of-date documents wait
for a revision), `propose` (they become update items in the plan) or
`auto-revise` (the server revises them itself, after a quiet period and up to
a daily cap). `GET /api/documentation/maintenance` lists what it revised and
what waits on a person: a proposal to approve, a pull request to merge, a
document still out of date. Report those; revise the ones the operator asks
for.

A profile's planning policy covers statements no document cites: `off`
(the default) waits for someone to plan, `propose` plans by itself once
enough of them were offered to no plan and leaves the items for approval,
and `write` also starts the items' runs within the batch and active-run
limits.

## Not here

- **Publishing** a document as a GitHub pull request is a UI decision
  (open the document → **Create / update GitHub PR**). Tell the operator the
  document is ready to publish there.
- **Missing facts.** Fill them in the knowledge base, then run the request
  again.
- **Server unavailable.** Report it. Do not write the document by hand.
