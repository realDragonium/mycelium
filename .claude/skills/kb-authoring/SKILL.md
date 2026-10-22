---
name: kb-authoring
description: >
  Have the Mycelium server write or revise a knowledge-base document from the mycelium
  substrate, using its configured guideline set and Diátaxis templates (tutorial, how-to,
  reference, explanation, troubleshooting), through request_documentation and
  revise_document. Use this skill when someone asks to create or update a standalone
  knowledge-base article from product knowledge — when the source of truth is the mycelium
  graph rather than features/, backend/, or frontend/ docs. Needs a writer or admin MCP
  connection.
---

# Knowledge-base documents from the substrate

The Mycelium server writes these documents itself. A documentation run queries
the substrate, writes from the instance's guideline set and template, reviews
the result in a separate model conversation, and stores it as a generated
document with revision history (see `docs/DOCUMENTATION_MODELS.md`). This skill
asks for that run and reports what it produced. It does not write the document
locally.

## Before you start

- `request_documentation` must be in your tool list. It is visible only to a
  real writer or admin; on a drafter, reader or asker connection, say so and
  stop.
- The guidance and templates belong to the server. The starter guideline set
  is `kb-authoring`, with document types `tutorial`, `how-to`, `reference`,
  `explanation` and `troubleshooting`; an instance may configure others under
  Documentation → Profiles & templates. Do not paste guidance into the prompt.

## A new document

1. Write the prompt: the concept, the intended audience (internal or
   user-facing), and what the reader needs to do or understand. Pass
   `document_type` only when the request makes the type clear, and
   `guideline_set` only when the operator names one; otherwise the run
   resolves them.
2. Call `request_documentation(prompt=…)`. By default (`match_existing=true`)
   the run first checks whether the request looks like an update to an
   existing document. If it does, it writes nothing and its `error` names that
   document; ask the operator, then either revise it (below) or request again
   with `match_existing=false` for a separate document.
   - It refuses when the instance's active-run limit is reached. Tell the
     operator rather than retrying in a loop.
3. Poll `get_documentation_run(run_id)` until `status` is neither `queued` nor `running`.
   Runs take minutes, so poll sparingly.
4. Report by outcome:
   - **Document written**: `get_generated_document(document_id)`, then give the
     title, id, `current_revision` and the body (or a summary of a long one),
     with the run's review result.
   - **Nothing written**: give the run's `error`. When the review gate turned
     the document down, the run carries the refused `draft_title` and
     `draft_body`; summarize the findings against them.
   - **Failed**: give `error`.
   Facts the substrate could not supply are reported as knowledge gaps; name
   them so the operator can fill them in the substrate first.

## Revising a document

1. `get_generated_document(document_id)` for its `current_revision`.
2. `revise_document(document_id, expected_revision=<current_revision>, prompt=<the change>)`.
3. Poll and report as above. If another revision landed first, the call is
   refused: read the document again and retry once with the new revision.

A published document can be edited on GitHub. A revision then starts from the
GitHub text and keeps those edits (the run's `revision_base` is
`destination`). If the document also has an unpublished revision here, the
call is refused with an explanation. Relay it to the operator; do not choose
for them.

## Not here

- **Publishing** a document as a GitHub pull request is a UI action
  (Documentation → open the document → Create / update GitHub PR); it is not
  on MCP. Tell the operator the document is ready to publish there.
- **Missing facts.** If the run reports gaps, do not fill them from the code or
  from memory in the document. Suggest documenting them in the substrate (the
  `mycelium-draft` skill) and running the request again.
- **Server unavailable.** Report it. Do not write the article by hand instead.
