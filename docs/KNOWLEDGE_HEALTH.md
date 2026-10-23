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
that an undecided draft already links or takes an alias from;
`skip_pending=true` leaves them out.

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
self-links, an edge conditioned on one of its own ends, a "new" concept whose name already exists (that would rewrite its
description), and a name or alias the batch text does not contain. Unlike
ingest, which drops only an edge that is provably backwards, the pass drops
every edge whose statement kinds break its type's direction (for example
`accepts` to anything other than a `property`).

"Connect next N" sends the next N statements after the last run's (remembered
in the browser), skipping statements already in a pending draft. **Start from
the first** forgets that position.

### Settings

- Model: **Settings → Models → Connecting statements** (default Claude Sonnet).
- Instructions: **Settings → Prompts → Connecting statements**. A fixed
  contract after them says what the run may propose.
- Limits: **Settings → Limits → Connecting statements**: batch size (most
  statements per run, default 10), spending cap per run (default $0.75),
  operation cap, run time, tokens and retries.

The spending cap is checked before each model turn; the turn under way and the
final emit still finish, so a run can end slightly over it. A model without a
known price shows no cost and the cap cannot apply; the operation cap and run
time still bound the run. Each run's cost is shown with its result and written
to `connect_trace.jsonl` in the data directory.
