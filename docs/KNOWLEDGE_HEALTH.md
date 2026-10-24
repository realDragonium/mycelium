# Knowledge health

**Curate → Knowledge health** (`#/health`) counts what needs a curator. Each
count opens the list behind it:

| Count | Means | Opens |
|---|---|---|
| Isolated statements | No link leads to or from the statement, and no link holds only when it does | `#/health/isolated` |
| Statements naming no concept | No concept name or alias appears in its text | `#/health/unmentioned` |
| Concepts without a description | The description is empty | `#/health/undescribed` |
| Concepts no statement mentions | No statement uses any of its names | `#/health/unused` |
| Statements without an audience label | Only internal audiences see it; the list shows a failed labelling attempt's error | `#/health/unlabelled` |
| Open knowledge gaps | Neither resolved nor dismissed | Knowledge gaps |
| Out-of-date documents | A statement the current revision cites has changed, or an image it places was replaced, deleted or relabelled | Documents |
| Statements no `<profile>` document cites | One count per writing profile: its audience may see the statement, no document of the profile cites it, and it was not dismissed for the profile (`uncovered_by_profile`; [Uncovered statements](DOCUMENTATION_PLANNING.md#uncovered-statements)) | Documents → Plan |
| Old media | Captured longer ago than the configured age, or against another product version ([Media](MEDIA.md#out-of-date)) | Curate → Media, **Old** |
| Pending drafts | Open with their author, or submitted and undecided | Drafts |

The server computes every count in SQL (`GET /api/knowledge-health`) and pages
each list by id (`GET /api/knowledge-health/statements/<list>` and
`/entities/<list>`, with `after` and `limit`). Statement lists mark statements
that an undecided draft already links or takes an alias from, and when the
connect pass or an outside agent last looked at them (`settled_at`);
`to_connect=true` leaves out both, and statements an agent holds, giving the
statements the pass should be offered next.

## Connecting statements with AI

Writers and drafters can ask the AI to connect statements: the next N
isolated statements, the next N naming no concept, or a batch selected in a
list. Each run is one call to `connect_statements(statement_ids)` and produces
one ordinary draft, which goes through [draft review](DRAFT_REVIEW.md) like an
ingest draft: submitted to the reviewer while review is on, otherwise open for
a curator.

The run is the ingest loop with a different brief. It searches around each
statement with the same read tools and must meet the same reconcile and
adjacency floor. Its draft may only:

- add links between existing statements, each touching a statement in the
  batch as an end or as its `when` condition, with a link type from the live
  vocabulary;
- suggest an alias for an existing concept, quoting the batch statement that
  uses it;
- create a concept whose name appears word for word in a batch statement and
  is distinctive enough to be matched as a mention.

Anything else is dropped and listed in the draft's flags: statement creation,
rewrites, merges and deletions, edges that touch no batch statement,
self-links, `composes` between two states, an edge touching a statement the
run found badly phrased, an edge conditioned on one of its own ends, a "new" concept whose name already exists (that would rewrite its
description), and a name or alias the batch text does not contain. Unlike
ingest, which drops only an edge that is provably backwards, the pass drops
every edge whose statement kinds break its type's direction (for example
`accepts` to anything other than a `property`).

The brief asks for precision over coverage: no link between sibling states,
none between different records that only share words, and none for a badly
phrased statement ("Invoice Settings accepts due date."). The run marks such a
statement unphraseable instead, the server drops any edge it still proposes
for it, and opens a knowledge gap on it asking for a rephrase, unless it
already has an open gap.

The server remembers each statement the run reached, with its text and the
statements it weighed, in the memory it shares with
[outside agents](#curation-work-for-outside-agents). "Connect next N" sends
the next N statements that are in no pending draft, that no agent holds, and
that nobody looked at since they, a statement weighed for them, or a
statement mentioning one of their concepts last changed. It takes first the
statements whose concepts the most linked statements also name, since those
sit beside connected knowledge; ties, and statements naming no concept, go in
id order. A statement the run never reached (for example when a cap stopped
it) is offered again.

### Settings

- Model: **Settings → Models → Connecting statements** (default Claude Sonnet).
- Instructions: **Settings → Prompts → Connecting statements**. A fixed
  contract after them says what the run may propose.
- Limits: **Settings → Limits → Connecting statements**: batch size (most
  statements per run, default 5), token cap per run (default 2,000,000, 0 for none),
  operation cap, run time, tokens and retries.

Turns grow as the run reads, so before each model turn the run checks that
the tokens used so far plus a reserve for the next turn and the final emit
(its largest turn yet, the history it has added since, and the output bound)
stays under the token cap; otherwise it stops reading and emits its draft.
The reserve can fall short, so a run can still end slightly over the cap.
Each run's tokens are shown with its result and written
to `connect_trace.jsonl` in the data directory.

Its model calls are reported on the AI usage page as the connect pass.

## Curation work for outside agents

The connect pass sees only the knowledge base, so it cannot tell whether two
statements really relate. An agent working in the product's codebase (Claude
Code in the product repository, or a CI agent) can. Mycelium hands such
agents the same lists as claimable work over MCP and takes their proposals
as drafts with evidence, so the reviewer and curators can judge them. The
server never reads the code itself.
The `mycelium-code-curation` skill (`skills/`) walks an agent through this
workflow.

The agent needs a token with the drafter role or higher. A drafter's writes
go to its draft, so nothing lands without review. A token scoped to an
audience cannot claim work.

### Kinds of work

| `kind` | Item | What the agent decides |
|---|---|---|
| `isolated` | A statement with no links | Which statements it relates to, with which link type |
| `unnamed` | A statement naming no concept | Which existing concept it names (an alias), or a new concept it names word for word |
| `rephrase` | An open knowledge gap the connect pass filed, asking for a statement to be rephrased | A rephrasing of the statement |
| `gap` | Any other open knowledge gap | The statements, links or concepts that close it |

An item's id is the statement's id for `isolated` and `unnamed`, and the
gap's id for `rephrase` and `gap`.

### Workflow

1. **Claim a batch.** `claim_curation_work(kind, limit=5)` (at most 20)
   leases items for 30 minutes and returns:
   - `items`: each with `id`, `kind`, `text` (the statement's, or the
     gap's), `statement` (`{id, kind, text, concepts: [{id, name}]}`, or
     null for a gap about no statement), and `neighbours`: the five nearest
     statements as `{id, kind, text, score}`;
   - `link_types`: the vocabulary, with each type's description and, where
     it has one, its direction (which statement kinds it goes from and to);
   - `expires_at`, and `renewed`: the items of this kind you already held.

   Items come in id order: those nobody holds, no undecided draft covers, and
   nobody has looked at since they or the statements around them changed. A
   second token cannot claim an item the first holds. Each claim extends the
   lease on every item of that kind you still hold; `limit=0` only renews.
   An item whose lease runs out goes back to the pool.
2. **Check each item in the codebase.** Find where the product implements
   what the statement says, and what the neighbouring statements describe.
   Read the neighbours and any other candidates with `get_statements`, and
   search further with `search_statements`, `grep_statements` and
   `search_entities` when the neighbours are not enough.
3. **Propose, with evidence, or decide there is nothing.**
   - A link: `add_links(links=[{from_id, to_id, link_type, when?}])`. Read
     the edge aloud as "source `link_type` target"; the source is the
     bigger, earlier or wrapping claim. A type with a direction only goes
     between those statement kinds. Keep each link you want judged on its
     own evidence in its own `add_links` call.
   - A concept: `upsert_name(text, entity_id)` for an alias of an existing
     concept, or `upsert_entity(name, description)` for a new one whose name
     appears word for word in the statement.
   - A rephrase: `patch_statement(id, text=...)` with one claim in the
     statement's kind.
   - Each write returns a receipt with `draft_id`, `operation_ref` and
     `revision`. Attach what you found to that operation with
     `set_operation_evidence(draft_id, operation_ref, evidence,
     expected_revision)`. Each of up to five items is
     `{kind, path?, lines?, commit?, url?, excerpt, claim}`: `kind` is
     `code`, `ui`, `doc` or `other`; give a repository-relative `path` (with
     `lines` such as `"40-52"` and the `commit` you read) or a `url`; an
     `excerpt` of at most 1,500 characters; and a one-line `claim` of at most
     200 characters saying what the excerpt shows. The reviewer may accept a
     link that a concrete code excerpt supports even when the statement texts
     alone do not settle it, and judges a link without evidence more
     strictly.
   - Nothing to propose: no write; release the item as `no_link` in step 5.
4. **Submit the draft.** `submit_draft(draft_id)` sends it to the
   [reviewer](DRAFT_REVIEW.md) while review is on; otherwise it waits for a
   curator.
5. **Release.** `release_curation_work(item_ids, outcome, draft_id?, reason?)`
   for every item you claimed:
   - `proposed` with the `draft_id` (one of yours) that proposes something
     for them. A gap released this way is tied to the draft when it names no
     other, and applying the draft resolves it;
   - `no_link` with a short `reason` (at most 300 characters): you checked
     and nothing should change;
   - `skipped`: you did not get to them.

   `proposed` and `no_link` items are not offered again, to agents or the
   connect pass, until the statement's text, a neighbour you were offered,
   or a statement naming one of its concepts changes (for a gap: until its
   text or the statement it is about changes). `skipped` items are offered
   again at once. Releasing an item you do not hold is refused.

### Watching and unblocking

Knowledge health shows per list who holds items and how many, how many
listed items someone has looked at, and the outcomes: looked at by the
connect pass, proposed, no link, skipped. An admin can release an agent's
claims on a list (`POST /api/knowledge-health/claims/free` with `kind` and
`claimed_by`) when the agent stopped; no outcome is recorded, so the items
are offered again.
