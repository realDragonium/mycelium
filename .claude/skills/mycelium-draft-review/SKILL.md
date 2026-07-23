---
name: mycelium-draft-review
description: Review pending CI-submitted Mycelium substrate drafts (drf_ records) for approval. Use when the operator wants to review, merge, approve, or drain the mycelium draft queue. Verification is the agent's job; the approve/reject decision is the operator's, made in the Mycelium UI.
---

# Mycelium draft review (CI queue)

A CI pipeline in a product repository submits substrate drafts — queued ops
(`upsert_entity`, `upsert_statements`, links) — typically after each merged PR.
Approval **replays the ops against the live substrate** and happens in the Mycelium UI;
there is no approve/reject MCP tool. The agent verifies and recommends; the operator
decides. A writer-role MCP credential may apply agreed fixes live (links, renames,
merges) after approval — never before.

## Content standards come from the authoring skills

Load and follow the `mycelium-authoring` skill (sibling of this one) for every content
judgment: kinds, phrasing, decomposition depth, link direction, topology. The structural
review method below is condensed from the `mycelium-draft` skill — when in doubt, read
the original. Where this file appears to differ from authoring, authoring wins.

## Replay semantics (observed 2026-07 — re-verify if the substrate has changed since)

- `upsert_entity` is name-keyed. As of writing, matching is **case-sensitive** (live
  proof at the time: two entities differing only in case), so case/spelling variants
  create real duplicates; a normalization change may land later — if in doubt, test.
- Exact-name replay overwrites the description (last approved wins).
- Same name + identical description = the CI sentinel pattern — a harmless no-op, not a defect.
  Since late July 2026 the CI prompt discards pure no-op sentinels before submitting, so drafts
  submitted after that change should not contain them — older queued drafts still do. A no-op
  re-upsert in a *new* draft means the discard failed (the draft's PR comment should say so) or
  the prompt regressed; flag it rather than shrugging it off.
- Same name + different description = silent overwrite: decide which description wins
  before approving.
- Submitted drafts are immutable (`discard_draft_op` is for open drafts). A flawed
  submitted draft is either approved-then-fixed-live or rejected whole.
- Pending drafts are invisible to all reads and to each other — cross-draft duplication
  is the expected failure mode of a backlog, and `add_links` cannot target queued
  statements (no ids until applied).

## Phase 0 — index the whole queue first

Never judge a draft in isolation. `list_drafts(status="submitted")`, then `get_draft`
everything (bulk via subagent; raw JSON to a scratch file). Build the duplicate map:
entity names upserted by more than one draft (including case/spelling variants and
variants of live entity names), same claims authored by multiple drafts, drafts sharing
one domain. Review **oldest-first** so descriptions don't regress.

## Phase 1 — per draft

1. **Boundary survey.** Before judging content, walk the substrate around the draft's
   domain (semantic + literal search, hydrate top hits): what exists upstream (entry
   statements), downstream (exit statements), and inside the domain already. The draft's
   new statements should land in the interior and wire to entries/exits. Zero live hits
   for the domain = genuinely new surface; an unanchored batch is then acceptable —
   otherwise missing anchors are findings, with the specific live ids named.
2. **Entities.** Classify each `upsert_entity`: new / sentinel no-op / overwrite
   (pick the winning description) / variant duplicate (block: reject or plan immediate
   `merge_entities`). Existence checks go beyond prefix search — stems, variants, grep of
   live statement text, concept-match against the entity catalogue; the substrate names
   concepts in product language, code names differ.
3. **Statements.** `discover_facts` every text; scores measure *similarity, not sameness
   of claim* — read each `exists`/`near` match before deciding. Same claim reworded →
   duplicate (reject or plan merge). Mirror pairs (Low/Medium/High, above/below,
   enable/disable) score ~0.99 and are legitimately distinct — never collapse them.
   Cross-check the queue duplicate map for the same claim in sibling drafts.
4. **Topology, read off the ops.** Every link type must exist in `list_link_types()` /
   `list_entity_link_types()` fetched this session — CI can invent types, and replay is
   the gate. A type that exists can still not fit: check the glossary's direction/kind
   constraints and layer — types whose glossary speaks of checks, actions, causes, or
   procedures (the prescriptive/diagnostic layer) never fit descriptive behaviour
   statements, and zero `usage_count` means read the definition extra carefully.
   Direction flip test on every edge (source = bigger/earlier/wrapping claim).
   Spine vs star: can you walk entry → terminal through real intermediates, or do spokes
   converge on a hub? No `configures`/`governed-by` edge may terminate on a bare
   capability. `when` leaves must resolve to states in the batch or confirmed-live ids
   (`get_statements` them — never trust an id you haven't hydrated). Flow contamination:
   both endpoints of a link reachable in the same execution path, not welded across
   mutually exclusive branches. Orphans wired or justified (condition-state `when`
   leaves are correctly link-free). Watch for invented success/failure forks: if the
   code swallows a failure with no observable difference, a success/failure branch in
   the draft is a defect, not detail.
5. **Truth check against code.** The product codebase is authoritative; the draft may
   encode wrong assumptions. Verify non-obvious claims, orderings, and every proposed
   anchor link — with file:line evidence. For drafts with substantial or surprising
   claims, spawn an adversarial subagent per the `mycelium-draft` template: disprove the
   claims AND enumerate unmodelled paths. Never invent a link; mark inference 💡,
   unresolved ⚠️.
6. **Verdict**: **Approve** / **Approve + fix after** (list the exact post-approval ops)
   / **Reject** (say why, and what if anything should be re-authored). Present verdicts
   in small batches (2–4, oldest first); the operator acts in the UI.

## Phase 2 — after each approval

Verify landed (descriptions, mentions resolved); apply the agreed fixes live; walk the
new statements once more for orphans and spine; update the queue index — later drafts'
duplicate upserts just became sentinels, overwrites, or rejects.

## Running state

Keep a tally (approved / fixed / rejected / remaining) and persist queue-position notes
across sessions so a later session resumes mid-queue instead of re-deriving.
