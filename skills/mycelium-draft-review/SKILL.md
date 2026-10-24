---
name: mycelium-draft-review
description: Work the Mycelium draft queue (submitted drf_ drafts) alongside the server's internal draft reviewer. Reads each draft's review_assessment, starts or reruns the reviewer with request_draft_review where an assessment is missing, failed or stale, checks what the reviewer cannot (product truth against the code, duplicates across queued drafts), and recommends approve, reject, answer or correct. Use when the operator wants to review, triage, drain or approve the draft queue. Needs a real writer or admin connection; approving, rejecting and answering the reviewer stay the operator's decisions, made in the Mycelium UI.
---

# Mycelium draft review

Drafts are queued knowledge changes. They come from `ingest`, from drafter
connections (CI pipelines, the `mycelium-draft` skill), from the connect pass
on Knowledge health, and from alias suggestions. Nothing in a draft is live
until it is applied. This skill works on top of the server's **internal
reviewer** (`docs/DRAFT_REVIEW.md`), not instead of it.

## Who does what

- **The internal reviewer** runs when a draft is submitted, if review is on.
  It judges how the draft fits the existing knowledge: duplicates,
  contradictions, link type and direction, missing links to live neighbours,
  entity variants. It **trusts the producer on what the product does** and
  never sees the code. Its authority depends on the mode under
  **Settings → Draft review**:
  - `off`: no review.
  - `review-only`: an advisory assessment. It never edits, applies or rejects.
  - `review-and-apply`: it applies the draft (`apply_reviewed_draft`),
    rejects it, or stops with questions for a person. It acts only while
    **Allow applying accepted reviews** is on; otherwise its assessment is
    advice. Under **Apply automatically: Only clean approvals** (the default)
    it applies only `good` drafts; a draft it wants to correct is `held`
    with up to twelve precise corrections (edit one statement, add or drop one
    link, drop one statement, strike or append an operation) for a curator
    to accept, edit or ignore. Under **Approvals with corrections too** it
    makes those corrections itself and applies.
- **You** read its assessments, start reviews that are missing, check what it
  cannot see, and recommend. You do not approve, reject or answer.
- **The operator** approves, rejects, edits operations and answers the
  reviewer's questions in the draft detail view (`#/drafts/<id>`), where
  they also accept a held review's corrections.

Approve and reject are UI decisions behind `POST /api/drafts/{draft_id}/approve`
and `/reject`; answering is `POST /api/drafts/{draft_id}/review/answer`;
accepting held corrections is `POST /api/drafts/{draft_id}/review/accept`. Do not
call those routes unless the operator explicitly asks you to act for them in
this session.

## Connection

`list_drafts` is advertised only to a real writer or admin. On a drafter,
reader or asker connection you cannot see the queue: say so and stop.

`request_draft_review` is not on MCP. It is an HTTP tool route with the same
arguments as JSON, and it needs a real writer or admin token:

```sh
curl -sX POST "$MYCELIUM_URL/request-draft-review" \
  -H "Authorization: Bearer $MYCELIUM_TOKEN" -H "Content-Type: application/json" \
  -d '{"draft_id": "drf_…", "rerun": true}'
```

Without `rerun` it returns the latest attempt or starts the first one; with
`rerun=true` it starts a fresh attempt after a completed or failed one. A
running attempt is returned as it is. It is refused while the mode is `off`.
Each attempt is a model call the server pays for: list the drafts you intend
to rerun and get the operator's go before starting more than a few. Without a
token, the operator clicks **Run review** or **Run again** on the draft.

## Phase 0 — index the queue

1. `list_drafts(status="submitted")`, then `get_draft` each one (in bulk, keep
   the raw JSON in a scratch file).
2. Read each `review_assessment`:
   - `status` (`running`, `completed`, `failed`) and `stale` (the draft
     changed after the assessment);
   - `label` (`good`, `changes_suggested`, `reject`, `needs_context`) with
     `rationale`, `questions`, `corrections` and `contradictions`;
   - `application` (`unapplied`, `applied`, `rejected`, `needs_human`,
     `held`) with
     `detail`, and `mode`, the mode it ran under;
   - `answers`: curators' earlier answers to its questions.
3. Sort the queue:
   - **Waiting for an answer** (`application: needs_human`). These need the
     operator most; the questions are also filed as knowledge gaps naming the
     draft.
   - **Corrections waiting** (`application: held`): the reviewer would
     accept the draft with its corrections. Check each correction; recommend
     accepting all, some, or edited ones, or approving as submitted.
   - **Assessed, not applied**: `review-only` assessments, runs the
     application gate held, `reject` labels under `review-only`.
   - **Needs a review**: no assessment, `failed`, `stale`, or assessed under a
     mode other than the current one. Failed runs are retried by a sweep for
     about two and a half hours; a stale or missing one needs
     `request_draft_review` (or **Run again**). An admin can list everything
     the current configuration has not reached with
     `GET /api/draft-review/backlog`.
   - **Alias suggestions** (drafts holding only `alias_suggestion`
     operations) are never sent to the reviewer; each waits for an individual
     decision under **Names & aliases**.
4. Build the duplicate map across the queue: entity names upserted by more
   than one draft (spelling variants included; case variants already resolve
   to one entity), the same claim in several drafts, drafts sharing a domain.
   Work **oldest first** so descriptions do not regress.

## Phase 1 — per draft

1. **Start from the reviewer's output.** If it asked questions, find the
   answer in the product code or the substrate, with evidence, so the operator
   can answer. Check each suggested correction and each contradiction it
   resolved.
2. **Truth against the code.** The codebase is authoritative and the
   reviewer never sees it. Verify non-obvious claims, orderings and every link
   that anchors new statements to live ones, with `file:line` evidence. Read
   the draft's `review_evidence` on `get_draft`: that is everything the
   reviewer was told about the product. For substantial or surprising
   drafts, run the adversarial verification the `mycelium-draft` skill
   describes.
3. **Across drafts.** Queued statements are invisible to reads, and to other
   drafts, until applied. Check the duplicate map.
4. **Structure**, where the assessment is silent or advisory: apply the
   `mycelium-authoring` rules (and `mycelium-guide-authoring` for procedures,
   actions, checks and causes). `discover_facts` every new text and read each
   `exists` / `near` match. Link types must come from `list_link_types()` /
   `list_entity_link_types()`. Apply the flip test, look for a walkable spine
   rather than a star, and hydrate every `when` leaf with `get_statements`.
5. **Recommendation**, one of:
   - **Approve** — the operator clicks Approve.
   - **Approve, then fix** — with the exact follow-up operations.
   - **Reject** — why, and what should be re-authored.
   - **Answer** — the text the operator should give the reviewer, with
     evidence.
   - **Accept corrections** — for a held review: which suggested corrections
     to keep, untick or edit, each with why.
   - **Correct first** — an operation the operator should edit or remove in
     the draft detail view before approving.
   - **Review** — the assessment is missing, failed, stale or from another
     mode; start it with `request_draft_review` or ask the operator to.

   Present recommendations in small batches (2–4, oldest first).

## Application facts

- Approving replays every operation in order and is all-or-nothing. A failing
  operation (a missing id, a flipped link) or a statement the phrasing check
  refuses leaves the draft as it was, and the refusal lists each statement
  with its reasons. Check phrasing before recommending Approve.
- `upsert_entity` matches names case-insensitively. Replaying it with a
  different description overwrites the live description: decide which wins
  before approving.
- The author cannot add or change operations on a submitted draft, but can
  still replace its evidence, which makes the assessment stale. A curator can
  edit or remove operations in the UI.
- Applying a draft resolves the knowledge gaps reported about it.

## Phase 2 — after each application

Check what landed (descriptions, mentions resolved, links where intended),
walk the new statements once for orphans and a spine, and update the queue
index: a later draft's duplicate entity upsert just became an overwrite or a
no-op.

Keep a tally (applied, rejected, waiting for an answer, remaining) and
persist queue-position notes so a later session resumes instead of
re-deriving.
