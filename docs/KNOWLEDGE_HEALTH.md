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
| Out-of-date documents | A statement the current revision cites has changed | Documents |
| Pending drafts | Open with their author, or submitted and undecided | Drafts |

The server computes every count in SQL (`GET /api/knowledge-health`) and pages
each list by id (`GET /api/knowledge-health/statements/<list>` and
`/entities/<list>`, with `after` and `limit`). Statement lists mark statements
that an undecided draft already links or takes an alias from, and when the
connect pass last looked at them (`settled_at`); `to_connect=true` leaves out
both, giving the statements the pass should be offered next.

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
statements it weighed. "Connect next N" sends the next N statements that are
in no pending draft and were not looked at since they, a statement weighed
for them, or a statement mentioning one of their concepts last changed. A
statement the run never reached (for example when a cap stopped it) is
offered again.

### Settings

- Model: **Settings → Models → Connecting statements** (default Claude Sonnet).
- Instructions: **Settings → Prompts → Connecting statements**. A fixed
  contract after them says what the run may propose.
- Limits: **Settings → Limits → Connecting statements**: batch size (most
  statements per run, default 5), spending cap per run (default $0.50),
  operation cap, run time, tokens and retries.

Turns grow as the run reads, so before each model turn the run checks that
the spend so far plus twice its most expensive turn yet (the next turn and the
final emit) stays under the spending cap; otherwise it stops reading and emits
its draft. The estimate can fall short, so a run can still end slightly over
the cap. A model without a
known price shows no cost and the cap cannot apply; the operation cap and run
time still bound the run. Each run's cost is shown with its result and written
to `connect_trace.jsonl` in the data directory.

Its model calls count towards the monthly AI budget as the connect pass, a
background action: while the budget pauses background actions, a run is
refused with that reason.
