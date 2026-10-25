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

### AI curation pass

The server can also work the [curation lists](#curation-work-for-outside-agents)
itself, as a curation agent named `model:<model>` on the Connecting statements
model. Each step has its own switch in **Settings → Limits → Connecting
statements**, all off by default (and off after an upgrade):

- **Connect statements automatically**: every minute, runs the connect pass on
  the next isolated statements (then the next statements naming no concept),
  as "Connect next N" does.
- **AI decides duplicate candidates**: for each `duplicate` pair, proposes a
  draft that merges one side into the other (`merge_statements` or
  `merge_entities`), or records that the pair is distinct. A distinct concept
  pair is dismissed in Names & aliases by `model:<model>`.
- **AI describes concepts without a description**: proposes a description from
  the statements that name the concept, citing them as evidence.
- **AI acts on rephrase gaps and gaps about drafts**: rephrases or keeps a
  statement the connect pass could not judge, and for a gap about a draft (a
  rejected draft, a contradiction resolved in its favour) proposes a corrected
  draft or closes the gap with a reason. Gaps about no draft, such as
  questions Ask could not answer, need product knowledge and stay for agents
  in the product's code and for people.

Every proposal is a draft with the statements it rests on as evidence, created
by no account, so the [reviewer](DRAFT_REVIEW.md) judges and, in
review-and-apply, applies it (a merge only under an admin reviewer); with review off it waits for a curator. An item
the model leaves undecided, or decides with something the server cannot check
(a statement it was not given, an operation outside the fixed set), is released
`skipped`: outside agents can still claim it, and the pass does not try it
again until it changes. A connect run that fails, or ends without looking at
a statement it took, counts a failure for that statement; after **Retries of
a statement after a failed connect run** further failures (`connect_retries`,
default 2) the statement stops (see [Stopped automations](#stopped-automations))
until its text changes. The pass does nothing while Connecting statements runs
on an External agent or has no credentials; its calls are metered as the
connect pass.

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
| `question` | A question the [draft reviewer](DRAFT_REVIEW.md) asked a person (`needs_context`) | The answer, with the evidence that settles it |
| `duplicate` | A pair of statements, or of concepts, that look alike | Merge them, or say they are distinct |
| `undescribed` | A concept without a description | Its description |
| `unused` | A concept no statement mentions | The statements that name it, a merge, or nothing |

An item's id is the statement's id for `isolated` and `unnamed`, the
gap's id for `rephrase`, `gap` and `question`, the concept's id for
`undescribed` and `unused`, and both ids sorted and joined by `~` for
`duplicate`. A `duplicate` item carries `pair`: its kind (`statement` or
`concept`), both sides (for concepts with their names, description and some
statements naming them) and the score. `undescribed` and `unused` items carry
`concept`: its names, description and the statements naming it. A `rephrase`
or `gap` item whose gap names a draft carries `draft`: its id, title, status,
the latest review's rationale and its operations. A `question` item is the
newest open gap about a submitted draft whose latest review waits for a
person and that has not changed since; it also carries `question`: the
`draft_id`, the draft's title, the `run_id` of the review that asked, its
`questions` and its rationale. These gaps are not offered as `gap` items,
since their draft is still undecided.

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
   An item whose lease runs out goes back to the pool, and that counts as a
   skip (see below).
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
   - A merge: `merge_statements(from_id, into_id)` or
     `merge_entities(from_entity_id, into_entity_id)` on your draft, keeping
     the better phrased side. The reviewer judges it like any operation.
   - A description: `upsert_entity(name, description)` with the concept's
     name.
   - Evidence can also be a knowledge-base statement: `{kind: "doc",
     statement_id, excerpt, claim}`.
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

   For gaps (`rephrase` and `gap`), an agent can also close a gap it
   settled, as a curator would on the Gaps page:
   - `resolved` with the `draft_id` of an applied draft (anyone's) that
     closed it: the gap is resolved and tied to that draft;
   - `not_applicable` with a `reason` (at most 300 characters): nothing
     should change, and the gap is dismissed.

   The gap records the agent as who resolved or dismissed it and when, as
   it records a person; the Gaps page shows the agent's reason beside it.

   A `duplicate` item takes `proposed` (your merge draft), `not_applicable`
   with a reason (the pair is distinct; a concept pair is dismissed in Names
   & aliases as you) or `skipped`. It is not offered again until either side's
   text, or a concept's names, change. Pairs either side of which an undecided
   draft touches are left out. Merges stay admin operations: a merge draft
   applies only when its reviewer is an admin (an external agent with an
   admin token, or an admin reviewer account for a server model). Under a
   writer reviewer the attempt fails with the role error and the draft waits.

   A `question` item is released as `answered` (one item per call) with
   `answer` (at most 6,000 characters) and `evidence`: one to five items in
   the shape `set_operation_evidence` takes (code, UI, doc or media). An
   answer without evidence is refused, and so is an answer from the draft's
   creator. The answer is recorded on the review as a curator's answer is,
   with the agent as `answered_by` and its evidence, and the draft is
   reviewed again with it exactly as after a person's answer
   ([Draft review](DRAFT_REVIEW.md#evidence-and-scope)). The question's gap
   stays open until the draft is applied. A `question` item takes only
   `answered` or `skipped`.

   `proposed`, `no_link`, `answered`, `resolved` and `not_applicable` items
   are not offered again, to agents or the connect pass, until the
   statement's text, a neighbour you were offered, or a statement naming
   one of its concepts changes (for a gap: until its text or the statement
   it is about changes, or a person reopens a gap an agent closed). A reviewer that asks again files a new gap, which
   is a new item. `skipped` items are offered again at once, but each skip,
   and each claim of the item that ran out, counts: past **Retries of a
   curation item that was skipped or whose claim ran out** (**Settings →
   Limits → Connecting statements**, `skip_retries`, default 2) the item is
   not offered again until it changes or an admin retries it under [Stopped
   automations](#stopped-automations). Any other outcome forgets the count.
   A reviewer's question stops being offered once agents and the model
   answered it more often in a row than the draft review's `answer_retries`;
   it waits for a person. Releasing an
   item you do not hold, or with an outcome its kind does not take, is
   refused.

### Watching and unblocking

Knowledge health shows per list who holds items and how many, how many
listed items someone has looked at, and the outcomes: looked at by the
connect pass, proposed, no link, skipped, answered. A gap an agent
resolved or dismissed leaves the list; the Gaps page shows who closed it and
why. An admin can release an agent's
claims on a list (`POST /api/knowledge-health/claims/free` with `kind` and
`claimed_by`) when the agent stopped; no outcome is recorded, so the items
are offered again.

### Rejected proposal chains

A rejected draft files a gap about it, and acting on that gap proposes another
draft, which can be rejected again. So that curation and review do not loop,
a gap about a draft is not offered to the AI curation pass or to outside
agents once its chain holds more than **Retries after a curation proposal is
rejected** (`follow_up_retries`, default 2) earlier rejected curation
proposals: the draft it is about was proposed for a gap about another
rejected draft, and so on. Such a gap stays open for a person and is listed
under Stopped automations. An admin's retry lets that one gap be offered once
more; if its proposal is rejected too, the new gap stops again.

Other outcomes already keep an item from being offered again while its text
is unchanged: a proposal (whatever became of its draft), a pair recorded as
distinct, a gap closed as not applicable, and an item the agent skipped.

### Stopped automations

Knowledge health lists the items automatic work stopped retrying, each with
the reason, the failures and when it stopped:

- connect pass statements;
- [audience decisions](AUDIENCES.md#stopped-decisions);
- gap follow-ups;
- [draft reviews](DRAFT_REVIEW.md) that failed past their retries;
- curation items skipped, or whose claim ran out, past their retries;
- mention recomputes: a queued vocabulary change whose recompute failed
  past **Retries of a failing mention recompute** (`mention_retries`);
- embeddings: a statement or name that failed to embed, while others
  embedded, past **Retries of a statement or name that fails to embed**
  (`embedding_retries`).

The last two are under **Settings → Limits → Agent tasks and background
work**, default 2. A failing row no longer holds up its queue: the mention
worker redoes a failing chunk row by row and the embedding worker halves a
failing batch until the row is alone, then passes over it. A provider outage
fails every row alike and so stops none. Nothing retries a stopped item
automatically until its inputs change (the statement text, the label, the
gap, the draft, the item). An admin's **Retry** (`POST /api/knowledge-health/stopped/retry`
with `kind` and `item_id`) offers the item to its automation again with a
fresh count.
