---
name: mycelium-draft-review
description: Work through the Mycelium draft queue (submitted drf_ records) alongside the server's internal draft reviewer. Reads each draft's review_assessment, checks what the reviewer cannot (product truth against the code, cross-draft duplicates), and recommends approve / reject / answer / rerun. Use when the operator wants to review, drain, approve or triage the mycelium draft queue. The agent verifies and recommends; approving, rejecting and answering the reviewer are the operator's decisions, made in the Mycelium UI.
---

# Mycelium draft review

Drafts are queued substrate changes: from `ingest`, drafter
accounts (CI pipelines, the `mycelium-draft` skill) and alias suggestions. When
a draft is submitted, the server's **internal reviewer** assesses it if review
is switched on in AI settings (see `docs/DRAFT_REVIEW.md`). This skill works
on top of that reviewer, not instead of it.

## Who decides what

- **The internal reviewer** judges how a draft fits the existing knowledge:
  duplicates, contradictions, link type and direction, missing links to live
  neighbours, entity variants. It **trusts the producer on what the product
  does** and has no access to the product code. In `review-and-apply` mode,
  with application allowed, it can correct up to eight operations and then
  apply or reject the draft itself, or stop and ask a person a question.
  In `review-only` mode its assessment is advice. In `off` mode there is none.
- **You** check what the reviewer cannot: whether the claims are true in the
  product code, and whether several queued drafts propose the same thing.
  You recommend; you do not approve, reject or answer.
- **The operator** approves, rejects, answers the reviewer's questions and
  starts reruns, in the Mycelium UI's draft detail view.

There is no MCP tool that approves, rejects, applies or reruns a draft. The
HTTP routes behind the UI buttons exist (`POST /api/drafts/{id}/approve`,
`/reject`, `/review`, `/review/answer`); do not call them unless the operator
explicitly asks you to act for them in this session.

## Content standards come from the authoring skills

Load and follow `mycelium-authoring` (and `mycelium-guide-authoring` for
procedures, actions, checks and causes) for every content judgment: kinds,
phrasing, decomposition depth, link direction, topology. Where this file
appears to differ from them, they win.

## Phase 0 — index the queue

`list_drafts` is visible only to a real writer or admin; a drafter or reader
connection cannot see the queue, so say so and stop.

1. `list_drafts(status="submitted")`, then `get_draft` each one (bulk through
   a subagent; keep the raw JSON in a scratch file).
2. For each draft, read `review_assessment`:
   - `status`: `running`, `completed` or `failed`; `stale` is true when the
     draft changed after the assessment.
   - `label`: `good`, `changes_suggested`, `reject` or `needs_context`, with
     `rationale`, `questions`, `corrections` and `contradictions`.
   - `application`: `unapplied`, `applied`, `rejected` or `needs_human`, with
     `detail`.
   - `answers`: curators' earlier answers to its questions.
3. Sort the queue into:
   - **Waiting for an answer** (`application: needs_human`): the reviewer asked
     a person something. These need the operator most.
   - **Assessed, not applied**: advisory assessments (`review-only`), runs the
     application gate held, `reject` labels in `review-only`.
   - **Not assessed**: no assessment, a `failed` run, or a `stale` one. Failed
     runs are retried automatically for a while; a stale or missing one needs
     **Run again** in the UI. No assessment at all can also mean review is on
     but no model is configured in AI settings.
   - **Alias suggestions** (drafts holding only `alias_suggestion` operations)
     always wait for individual human decisions and are never reviewed
     automatically.
4. Build the duplicate map across the queue: entity names upserted by more
   than one draft (spelling variants included; case variants already resolve
   to one entity), the same claim authored in several drafts, drafts sharing
   one domain. Review **oldest first** so descriptions don't regress.

## Phase 1 — per draft

1. **Start from the reviewer's output.** If it asked questions, your first job
   is to find the answer in the product code or the substrate, with evidence,
   so the operator can answer it. If it suggested corrections or listed
   contradictions, check each.
2. **Truth against code.** The product codebase is authoritative and the
   reviewer never sees it. Verify non-obvious claims, orderings and every link
   that anchors new statements to live ones, with `file:line` evidence. For
   substantial or surprising drafts, spawn an adversarial subagent as the
   `mycelium-draft` skill describes: disprove the claims and list the paths the
   draft does not model. Never invent a link; mark inference 💡 and open
   questions ⚠️.
3. **What the reviewer cannot see across drafts.** Queued statements are
   invisible to reads, and to other drafts, until applied. Check the duplicate
   map: a claim another queued draft also makes, or an entity it also creates.
4. **Structure**, where the reviewer's assessment is silent or advisory:
   `discover_facts` every new text and read each `exists` / `near` match
   (scores measure similarity, not sameness of claim; mirror pairs such as
   Low/High legitimately score near 1.0). Link types must exist in
   `list_link_types()` / `list_entity_link_types()` fetched this session.
   Apply the flip test, look for a walkable spine rather than a star, and
   hydrate every `when` leaf with `get_statements`.
5. **Recommendation**, one of:
   - **Approve** (the operator clicks Approve).
   - **Approve, then fix**: the exact follow-up operations after it lands.
   - **Reject**: why, and what should be re-authored.
   - **Answer**: the text the operator should give the reviewer, with evidence.
   - **Run again**: the assessment is stale, missing or failed.
   - **Correct first**: an operation a curator should edit in the draft detail
     view before approving.
   Present recommendations in small batches (2–4, oldest first).

## Replay facts to keep in mind

- `upsert_entity` matches names case-insensitively. Replaying it with a
  different description overwrites the live description: decide which one
  wins before approving.
- Approving replays every operation in order. An operation that errors (a
  missing id, a flipped link) fails the whole approval and leaves the draft as
  it was. A statement that fails the phrasing check does **not**: a manual
  Approve leaves it out, with every statement that references it, and applies
  the rest. The reviewer's automatic application refuses instead. Check
  phrasing findings before recommending Approve.
- The author cannot add or change operations on a submitted draft, but can
  still replace its evidence, which makes the assessment stale. A curator can
  edit or remove an operation in the UI, and the reviewer can make its own
  corrections.

## Phase 2 — after each approval or automatic application

Check what landed (descriptions, mentions resolved, links where intended),
walk the new statements once for orphans and a spine, and update the queue
index: a later draft's duplicate entity upsert just became an overwrite or a
no-op.

## Running state

Keep a tally (applied / rejected / waiting for an answer / remaining) and
persist queue-position notes so a later session resumes instead of
re-deriving.
