# Documentation planning

Open **Documents → Plan**, choose a writing profile and select **Plan
documentation**. The planner proposes which documents the profile's audience
needs; nothing is written until you, or the profile's
[AI reviewer](#reviewing-by-ai), approve an item. An agent with a writer or
admin token starts the same plan over MCP with
`request_documentation_plan(guideline_set)` and reads it, with its items,
reviews and uncovered statements, with `get_documentation_plan(guideline_set)`.

## What the planner reads

One model call per plan by default, through the **documentation planning**
action (see [Large backlogs](#large-backlogs) for more). It has
its own model (**Settings → Models**), instructions (**Settings → Prompts**) and
limits (**Settings → Limits**: tokens, timeout, retries, how many concepts and
key statements the overview carries, how many uncovered statements and items
one planning call places and keeps, how many calls a plan makes, the coverage
and re-plan thresholds, and how many items one batch approval starts).

The call gets the profile's audience description, its templates, its existing
documents (type, concept, out-of-date or not, and the opening of each), a
batch of its [uncovered statements](#uncovered-statements) to place, and an
overview of what the audience may see: concepts with their counts of visible statements by kind and,
for internal audiences, their parent concept and description, plus the most
connected capability and procedure statements. The overview is read through
the same boundary as a documentation run ([Audiences](AUDIENCES.md)), so the
planner never sees a statement, name, description or concept link the audience
may not. External audiences therefore get no concept hierarchy or
descriptions.

## What a plan keeps

Each item is `create` or `update` (a document whose scope should change, or
that should take in uncovered statements), with
a title, template, concept, rationale, priority and the statements it would
mainly draw on. The model proposes; Mycelium keeps an item only when:

- its template belongs to the profile and its concept is in the overview;
- an update names one of the profile's documents;
- it draws on at least one statement the audience may see (ids it may not see
  are removed, and a new document about a concept is topped up from that
  concept's statements);
- it is not a document the profile already has, another item of the same plan,
  or a proposal dismissed before.

A `create` about a concept that already has a document of that template becomes
an update of it. The plan shows how many proposals were set aside and why.

Three lists need no model and are always current: **Out-of-date documents**
(approve to start a revision briefed with the changed statements),
**Statements without a document** (see below) and **Concepts without a
document**, concepts with many visible statements and no document of the
profile about them.

## Uncovered statements

A statement is uncovered for a profile when its audience may see it and no
document of the profile cites it. The plan page counts them and lists the
first 50, capabilities and procedures and the most connected first; knowledge
health counts them per profile. **Dismiss** one the profile should never
document: it stops counting for that profile, and no plan is offered it. The
dismissed statements the audience may still see are listed below; **Undo
dismissal** (`POST /api/documentation/plans/{profile}/uncovered/{statement}/restore`,
writers and admins) counts one as uncovered again.

Each planning call is offered up to **Uncovered statements per planning call**
of them (40 by default), those no earlier plan of the profile was offered
first, so a large backlog is worked through over several calls or plans. The planner places each one a
reader needs: as an `update` listing it, for the existing document it
belongs in, or in a `create` that groups it with related statements.
Approving an update that lists statements its document does not cite starts
a revision briefed to add them, quoting each one's text, the way an
out-of-date revision is briefed with what changed.

A profile whose maintenance policy is `propose` (see
[Keeping documents up to date](DOCUMENTATION_MODELS.md#keeping-documents-up-to-date))
gets an update item among the proposed documents instead, for each document
that goes out of date, with the changed statements as its rationale. It can be
approved with others; approving briefs the revision with what changed by then.
These items stay with the profile across re-plans until the document's next
revision.

## Large backlogs

**Planning calls per plan** (Settings → Limits → Documentation planning; 1 by
default) lets one plan make more calls while statements no plan was offered
remain. Each call gets the next batch, the same overview, and the items earlier
calls proposed (`already_proposed`), which it does not propose again; an
update of a document an earlier call updates adds its statements to that item.
Each call keeps up to **Proposed documents per planning call**, and the plan
records how many calls it made and their tokens together. While planning is
set to External agent, each call is its own `documentation_planning` task,
which any agent may claim.

## Reviewing

**Approve** starts the same run as **Generate** (`request_documentation` with
the concept), or a revision for an update; the item then shows its run's
status and links the document when it is written. When that run wrote
nothing, **Retry** starts it again and the item follows the new run; when the
review refused it, **Retry with these notes** also briefs the writer with the
review's findings (see [Documentation models](DOCUMENTATION_MODELS.md)). Select several items to
approve them together, up to the batch limit (2 by default); each is its own
documentation run and counts against the active-run limit. Runs beyond that
limit are queued rather than refused: the item shows its place in line and
starts when a running one finishes. **Dismiss** is
remembered per profile, so a later plan drops the same proposal. A dismissed
out-of-date document comes back after its next revision.

Re-planning is manual unless the profile's planning policy says otherwise.
When enough statements have become visible to the audience since the last
plan (written after it, or for an external audience labelled after it), the
page says so.

## Reviewing by AI

A profile's **Who decides proposed plan items** setting (its editor under
**Settings → Documentation**, beside the planning policy) is a person by
default, also for profiles saved before it existed. Set to an AI reviewer,
the maintenance sweep has a reviewer decide every proposed item of the
profile's plan: the planner's items and the update items for out-of-date
documents. Out-of-date documents of a `manual` profile are then proposed to
the reviewer as update items, as under `propose`, rather than waiting in
**Out-of-date documents**.

The reviewer approves or dismisses each item with a reason, which the item
shows. A dismissal is remembered for the profile like a person's. An approved
item starts its run as a person's approval would, within the batch-approval
and active-run limits; the rest start on later sweeps. With a reviewer, the
`write` planning policy no longer approves every item of an automatic plan:
only those the reviewer approved start. A person can still decide any item
the reviewer has not.

The reviewer is never the planner. It runs where the documentation planning
action does ([AI models](AI_MODELS.md)): one model call, separate from the
planner's, with the planning model, limits and token accounting, or, while
planning is set to External agent, a `plan_review` task
([Agent tasks](AGENT_TASKS.md)) that the agent who made the plan cannot
claim. The reviewer reads the audience description, the profile's templates
and documents, and each item with the statements it draws on that the
audience may see. A review that fails, or an agent's that is refused too
often, marks its items "not reviewed" for a person. When the profile retries
failed AI work ([below](#when-ai-work-fails)), the next sweeps review those
items again, up to the retry attempts, and then leave them for a person with
how often the review failed.

## Planning by itself

A profile's planning policy (its editor under **Settings → Documentation**)
is `off` by default. Under `propose` or `write`, the maintenance sweep
([Keeping documents up to date](DOCUMENTATION_MODELS.md#keeping-documents-up-to-date))
starts a plan once the profile has as many uncovered statements no plan was
offered as the re-plan threshold (25 by default). The plan runs through the
documentation planning action, a server model or an external agent like any
other. Under `propose` its items wait for approval. Under `write` the sweep
approves them in order, at most the batch-approval limit per minute and only
while the active-run limit has room; each run is reviewed like any other.

The sweep waits while the profile has a plan running, while its latest plan
still has a proposed item or a run that has not finished, while the planning
model has no credentials, and after its own last plan failed, until a person
plans. An item whose run could not start stays proposed for a person, with
the reason. When the profile retries failed AI work, both are tried again
instead.

## When AI work fails

A profile's **When AI work fails** setting (its editor under **Settings →
Documentation**) is `person` by default, also for profiles saved before it
existed: failed AI work waits for a person, as described above. Set to `ai`,
the maintenance sweep retries it, up to **Retry attempts for failed AI work**
(Settings → Limits → Documentation maintenance; 2 by default), then gives up
with a reason a person can read:

| Failed work | Retried by | After the last attempt |
|---|---|---|
| An automatic plan | The next sweep plans again | The plan page says automatic planning gave up; it plans by itself again once someone plans |
| A plan review | The next sweep reviews the undecided items again | The items wait for a person, with how often the review failed; they no longer hold up automatic planning |
| A plan item whose run could not start | The next sweep starts it again | The item stays proposed with the reason; it no longer holds up automatic planning |
| A run that wrote nothing (plan item, automatic revision, or a request) | A new run of the same request, briefed with the review's notes when the review refused it | The run shows how many automatic retries it had and the last reason |
| An automatic revision that could not start or was cut off by a restart | The next sweep claims the revision again | The document stays out of date for someone to revise |
| An automatic publication | The next sweep publishes again | The run shows the publication error |

The plan item or automatic revision follows each retry, as it follows a
person's **Retry**. A person's retry starts the count again. Runs that
finished before an upgrade to this version are not retried.
Plans, items and dismissals live with documentation runs in
`mycelium-drafts.db` and are included in instance backups. A plan running
when the server restarts is marked failed.
