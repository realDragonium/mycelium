---
name: mycelium-draft-review
description: Decide Mycelium drafts (submitted drf_ drafts) against the product's code. Finds the queue with list_drafts (waiting drafts, corrections the server's reviewer held, its questions, drafts it rejected), checks each operation against the code with file:line evidence, and decides with review_draft (approve, approve with precise corrections, reject with a reason, or ask a person), reopening wrongly rejected drafts with reopen_draft first. Works whatever Settings → Draft review is set to. Use when asked to review, decide, triage, drain or approve the draft queue, or to reconsider drafts the AI reviewer rejected or held. Needs a real writer or admin token, and never decides a draft the same principal created. To be the server's reviewer for one claimed task while draft review is set to External agent, use mycelium-agent-tasks (kind draft_review).
---

# Mycelium draft review

Drafts are queued knowledge changes. They come from `ingest`, from drafter
connections (CI pipelines, the `mycelium-draft` skill), from the connect pass
on Knowledge health, from curation agents (`mycelium-code-curation`) and from
alias suggestions. Nothing in a draft is live until it is applied.

You decide drafts as a curator does in the web app, and you have what the
server's reviewer does not: the product's code. The reviewer judges how a
draft fits the existing knowledge and trusts the producer on what the product
does; you check that, operation by operation, and decide.

## Who does what

- **The server's reviewer** (`docs/DRAFT_REVIEW.md`) runs when a draft is
  submitted, if review is on, on a server model or as `draft_review` agent
  tasks. Under `review-only` its assessment is advice; under
  `review-and-apply` it can apply, reject, hold corrections (`held`) or ask a
  person (`needs_human`).
- **You** decide with `review_draft` and `reopen_draft`, whatever the mode,
  `off` included. Your decision is a curator's decision: it is applied or
  final, and logged with your principal, reason and evidence in the draft's
  `decisions`.
- **A person** can do the same in the draft detail view (`#/drafts/<id>`).

You cannot decide or reopen a draft your own principal created; leave those
for another writer or admin, and say so.

## Connection

`list_drafts`, `review_draft` and `reopen_draft` are advertised only to a real
writer or admin. On a drafter or reader connection you cannot decide: say so
and stop.

## Phase 0 — find the queue

`list_drafts` returns each draft with `op_count` and a summary of its latest
automatic review (`review_assessment`: `label`, `application`, `stale`).

| Queue | Call |
| --- | --- |
| Waiting for a decision | `list_drafts(status="submitted")` |
| Corrections the reviewer held for a curator | `list_drafts(status="submitted", application="held")` |
| The reviewer's questions for a person | `list_drafts(status="submitted", application="needs_human")` |
| Drafts the automatic reviewer rejected | `list_drafts(status="rejected", application="rejected")` |

Then `get_draft` each one you will work, keeping the raw JSON in a scratch
file. Read its `revision` (you decide at that revision), its `ops` (each with
`operation_ref`, `kind`, `payload` and the creator's `evidence`), its
`review_evidence`, `decisions`, and the full `review_assessment`: `rationale`,
`questions`, suggested `corrections`, `contradictions`, `parts` and earlier
`answers`.

Build a duplicate map across the queue: entities upserted by more than one
draft (spelling variants included; case variants already resolve to one
entity), the same claim in several drafts. Work **oldest first** so
descriptions do not regress. Present a batch of 2 to 10 drafts to whoever
asked before deciding many; decisions apply knowledge live.

## Phase 1 — check each operation against the code

1. **Truth.** The codebase is authoritative. For every statement, link and
   entity description, find the code that shows it, with `path`, `lines` and
   an excerpt. Read the creator's operation evidence and `review_evidence`
   first: they say what the creator checked; check that it shows the claim.
   For substantial or surprising drafts, run the adversarial verification the
   `mycelium-draft` skill describes.
2. **The reviewer's output.** Check each suggested correction and each
   contradiction it resolved. Answer its questions from the code. A rejection
   is often about fit (a duplicate, a wrong link direction) and sometimes
   wrong; judge it, do not take it as given.
3. **Across drafts.** Queued statements are invisible to reads and to other
   drafts until applied. Check the duplicate map.
4. **Structure**: apply the `mycelium-authoring` rules (and
   `mycelium-guide-authoring` for procedures, actions, checks and causes).
   `discover_facts` every new text and read each `exists` / `near` match.
   Link types come from `list_link_types()` / `list_entity_link_types()`.
   Apply the flip test, look for a walkable spine rather than a star, and
   hydrate every `when` leaf with `get_statements`.
5. **Phrasing.** Approving replays every operation all-or-nothing, and a
   statement the phrasing check refuses refuses the whole approval. Correct it
   first.

## Phase 2 — decide

```text
review_draft(draft_id, verdict, expected_revision=<revision you read>,
             reason="…", evidence=[…])
```

- **`approve`** when every operation holds as written.
- **`approve_with_corrections`** when it holds after small, precise fixes.
  `corrections` takes the reviewer's shape, up to twelve, each with every
  field present (`null` where unused) and a `reason`:

  ```json
  {"action": "edit", "operation_ref": "op_…", "statement": 0,
   "text": "A workspace owner exports invoices.", "kind": null,
   "description": null, "link": null, "tool_name": null,
   "payload_json": null, "reason": "Only owners pass the export check."}
  ```

  `edit` changes one statement's `text` or `kind` (`statement` is its index
  in an `upsert_statements` batch, `null` for a single-statement operation) or
  an `upsert_entity`'s `description`; the actions "add_link" and "drop_link" name one link
  (`link: {from_id, link_type, to_id, when_json}`, `@N` for the batch's own
  statements); `drop_statement` drops one batch statement; `strike` removes a
  whole operation; `append` adds one (`tool_name` and `payload_json`).
  Indices and `@` references name the draft as submitted. To accept a held
  review's corrections, pass them as they are, or edited. Corrections are
  also how you edit an operation; there is no separate edit tool.
- **`reject`** with a `reason` saying what is wrong and what should be
  written instead, when the draft should not land.
- **`needs_context`** with a `question` when only a person can settle it;
  the question is filed as a knowledge gap naming the draft.

`evidence` takes up to five items shaped like operation evidence (`kind`,
`path` with `lines` and `commit`, or `url` / `statement_id`, an `excerpt` and
a one-line `claim`). Give the code you checked; it is logged with your
decision.

**Refusals.** A draft changed since you read it is refused: `get_draft` again
and re-check what changed. An approval is refused when a record the draft
changes was rewritten after the draft was written; such a draft has to be
written again against current knowledge (reject it saying so, or leave it).
A correction that does not fit, or a corrected draft that still has an
operation finding, changes nothing; fix the correction.

## Reconsidering a rejected draft

When the code shows a rejected draft was right, or right after corrections:

1. `reopen_draft(draft_id, reason="…")`, saying why the rejection was wrong.
   It is refused when knowledge the draft changes was rewritten since.
2. `get_draft` for the new `revision`, then `review_draft` as above.

A reopened draft is not reviewed automatically again; it waits for your
decision.

## Application facts

- `upsert_entity` matches names case-insensitively. Replaying it with a
  different description overwrites the live description: decide which wins
  before approving.
- The author cannot add or change operations on a submitted draft, but can
  still replace its evidence, which changes its revision.
- Applying a draft resolves the knowledge gaps reported about it.

## After each application

Check what landed (descriptions, mentions resolved, links where intended),
walk the new statements once for orphans and a spine, and update the queue
index: a later draft's duplicate entity upsert just became an overwrite or a
no-op.

Keep a tally (approved, corrected, rejected, reopened, asked, remaining) and
persist queue-position notes so a later session resumes instead of
re-deriving.
