---
name: mycelium-curation
description: Keep a Mycelium knowledge base healthy. Reads the knowledge-health counts and lists (isolated statements, statements naming no concept, concepts without a description or without statements, statements without an audience label), runs the AI connect pass as a reviewed draft, finds and consolidates duplicate statements and concepts, and works the knowledge-gap queue. Use when someone asks to clean up, tidy, audit, deduplicate or connect the knowledge base, or to triage knowledge gaps. Reads work on any connection; the connect pass needs a writer or drafter, merges need an admin, and gap status changes need a real curator. To check queue items against a product's code from its repository, use mycelium-code-curation.
---

# Curating a Mycelium knowledge base

Curation finds what is wrong with the knowledge that is already there and
routes each problem to the right fix. The checks are cheap reads; the fixes
are writes that follow the `mycelium-authoring` rules (or go through review
with `mycelium-draft`). Report what you found before you change anything, and
let the operator choose which fixes to run.

Most steps here are HTTP routes on the same server, not MCP tools. Call them
with the base URL and a bearer token
(`-H "Authorization: Bearer $MYCELIUM_TOKEN"`). Without a token, each one is
a screen under **Curate** in the web app; name the screen instead.

## Knowledge health

`GET /api/knowledge-health` returns the counts (also **Curate → Knowledge
health**, `#/health`):

| List | Means | Usual fix |
|---|---|---|
| `isolated` | No link leads to or from the statement | Connect it (below) or link it by hand |
| `unmentioned` | No concept name or alias appears in its text | Add an alias, create the concept, or reword the statement to name it |
| `undescribed` | A concept has an empty description | `upsert_entity(name, description)` |
| `unused` | No statement mentions any of the concept's names | Merge it into the concept statements do use, or delete it in **Names & aliases** |
| `unlabelled` | Only internal audiences see the statement | Label it on the statement page; read the failed labelling error first |

The counts also cover open gaps, out-of-date documents and pending drafts;
those have their own queues (gaps below, `mycelium-documentation`,
`mycelium-draft-review`).

Page a list with `GET /api/knowledge-health/statements/{isolated|unmentioned|unlabelled}`
or `/api/knowledge-health/entities/{undescribed|unused}`, passing `after` (the
last id you saw) and `limit` (at most 200). Statement lists mark statements
an undecided draft already touches and when the connect pass last looked at
them (`settled_at`); `to_connect=true` leaves out both, so you do not propose
the same fix twice.

A count is not a defect list. An isolated statement can be a fine fact that
nothing else needs yet; an unmentioned statement can name a concept nobody
has created. Read a sample before recommending a fix for the whole list.

Mentions come from text: a statement mentions a concept only when one of its
names or aliases appears in the statement. Adding an alias
(`upsert_name(text, entity_id)`) fixes every statement that uses that wording
at once; it is usually the cheapest fix for an `unmentioned` cluster.

## Connect pass

The connect pass asks the server's model to propose links and concept
mentions for a batch of statements, as an ordinary draft that goes through
draft review (`docs/KNOWLEDGE_HEALTH.md`). It never creates, rewrites, merges
or deletes a statement, and it prefers no link to a doubtful one. A statement
it finds badly phrased gets no links; the server opens a knowledge gap on it
asking for a rephrase instead.

- `POST /connect-statements` with `{"statement_ids": [...]}`, or **Connect
  next N** on the Knowledge health screen. Needs a writer or drafter. Take
  the ids from a list with `to_connect=true`: those are the statements the
  pass has not looked at since they or their neighbours last changed.
- `connect` in the health response gives the batch size, spending cap and
  model; `connect_error` says why the pass is unavailable (no credentials, a
  paused budget). Do not send more statements than the batch size.
- **Each run costs money.** Say how many runs you intend and get the
  operator's go before starting more than one.
- The result names the draft. Hand it to `mycelium-draft-review`, or tell the
  operator it is in the queue. Dropped proposals are listed in the draft's
  flags; rephrase requests land in the gap queue (below).

Connect by hand instead when the right link is clear from reading: it is
free, and you can run the flip test yourself. Follow `mycelium-authoring` for
link types and direction.

## Curation with code access

The connect pass sees only the knowledge base. An agent in the product's
repository (Claude Code there, or a CI job) can check whether statements
really relate: it claims the same lists as leased work with
`claim_curation_work`, proposes through a draft with code evidence on each
operation, and releases each item with its outcome. Use
`mycelium-code-curation` for that work. Items an agent holds or has settled
are left out of `to_connect=true`, and Knowledge health shows who holds what
and the outcomes.

## Duplicates

**Statements.** `POST /find-duplicates` with `{"threshold": 0.92, "limit":
50}` returns pairs `{a_id, a_text, b_id, b_text, score}`. At 0.92 a pair is
almost always the same fact; at 0.85 it includes related facts that may
deserve a link instead. For each pair, read both with `get_statements` and
decide:

- **Same fact**: `merge_statements(from_id, into_id)`, keeping the better
  phrased statement as `into_id`. Links are moved onto it. Admin only.
- **Related, not the same**: link them (`add_links`) with the type that
  says how.
- **Different facts worded alike**: reword one so the difference is in the
  text (`patch_statement`).

**Concepts.** `POST /find-entity-duplicates` with `{"threshold": 0.75}`
returns `candidates`: pairs `{a_entity_id, b_entity_id, score, matches}`,
where `matches` says which names matched and how (the **Names & aliases**
workspace, `#/names`, shows the same list). Read both with `get_entity`. For
each pair:

- **Same concept**: `merge_entities(from_entity_id, into_entity_id)` moves
  every name to the target, so statements keep their mentions. Write the
  target's description to cover both first. Admin only.
- **Different concepts**: `POST /api/names-workspace/duplicates/dismiss` with
  `{"a_entity_id", "b_entity_id"}` so the pair stops coming back. A
  curator action.

Merges cannot be undone. List the merges you intend with both sides' text
and get the operator's go before running them.

## Knowledge gaps

Gaps are facts someone needed and did not find: reported by readers and
agents (`report_knowledge_gap`), by Ask, by documentation runs and by the
draft reviewer's questions.

1. `GET /api/knowledge-gaps?status=open` (also **Curate → Knowledge gaps**,
   `#/gaps`). Each gap may name the statement, draft or document it
   concerns.
2. Group them: the same missing fact reported several times, gaps a pending
   draft already answers, gaps that are questions about a draft (answer those
   in the draft, with `mycelium-draft-review`).
3. For each distinct fact, find the answer in the product code or docs, and
   add it with `mycelium-authoring` or propose it with `mycelium-draft`.
   Applying a draft resolves the gaps reported about it.
4. Close the rest with `PATCH /api/knowledge-gaps/{gap_id}` and
   `{"action": "resolve"}` (answered), `"dismiss"` (not a real gap, or out of
   scope) or `"reopen"`. Needs a real writer or admin.

Do not resolve a gap you have not filled, and do not fill one from memory:
verify the fact first, and when you cannot, leave it open with a note to the
operator.

## Report

End with what you found and what you did: counts before and after, the
drafts you started, the merges and gap closures you made, and the fixes you
recommend but did not run.
