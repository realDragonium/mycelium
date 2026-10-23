# The web app

Mycelium's browser app is served at `/ui/` by `mycelium-http`. It is one React
and TypeScript application built from `frontend/ui/`; the build is committed in
`src/mycelium/webui/`, so running the server needs no Node. See SETUP.md §6 to
change it.

`/cockpit` was a second app until it was merged into this one. `/cockpit`,
`/cockpit/` and anything under it redirect permanently to `/ui/`. The browser
keeps the `#…` part across the redirect, and the app maps both former apps'
addresses to the current ones (table below).

## Where things are

The sidebar groups screens by what you are doing. Ask and Find are not in the
sidebar: the command bar at the top of every screen runs them, and ⌘K / Ctrl-K
focuses it.

| Group | Screen | Address | What it is for |
|---|---|---|---|
| | Home | `#/` | Ask or Find, what is waiting for a person, what the knowledge base holds |
| | Ask | `#/ask?q=…` | A reasoned answer with confidence, gaps, provenance and a trace; report a gap from it |
| | Find | `#/find?q=…&mode=semantic\|grep\|survey` | Raw scored statements, plus entities whose names match |
| Explore | Browse | `#/browse` | Every statement, entity and name as a table |
| | Statement | `#/s/<id>` | Text (editable), mentions, connections graph or list, conditions, lineage, audiences with their label's source and reason (curators override; a curator label whose text changed since the decision is flagged to confirm or hand back to AI) |
| | Entity | `#/e/<id>` | Aliases, mentioning statements, entity links |
| | Statement graph | `#/graph?focus=<id>` | Force-directed graph of statements and entities |
| | Entity map | `#/entities?focus=<id>` | Entities and their links; add and remove entity links |
| | Documents | `#/documentation` | Plan which documents a profile's audience needs, then approve or dismiss each proposal ([Documentation planning](DOCUMENTATION_PLANNING.md)); generate (optionally about a concept; the form says whether it revises an existing document), edit, review and publish documents; see each pull request's state; see which documents are out of date with their sources and revise them; revise from the published copy when both sides changed; read a document's sources as statement text linked to each statement; retry a run that wrote nothing, or see why the review refused it and retry it with those notes briefed to the writer, also from the plan; follow a run as it works and see what it spent (turns, duration, tokens, estimated cost, statements retrieved and cited, gaps filed) on the run and in the generation history |
| Add knowledge | Ingest text | `#/ingest` | Paste prose; a loop extracts a draft |
| Curate | Drafts | `#/drafts`, `#/drafts/<id>` | Review, edit, submit, approve, reject or withdraw drafts; answer the reviewer's questions. Approving is all-or-nothing: if any statement is refused (the phrasing linter), nothing is applied and each refusal is listed with its reasons. Applying a draft resolves the gaps reported about it |
| | Knowledge gaps | `#/gaps` | Resolve, dismiss or reopen reported gaps; follow a gap to the statement, draft or document it names |
| | Names & aliases | `#/names` | Curate a concept's names; merge or dismiss possible duplicate concepts, and restore dismissed pairs; decide AI alias suggestions |
| | Glossary | `#/glossary` | Statement kinds and link types |
| | Activity | `#/activity` | The audit log of every change |
| | Settings | `#/settings/<section>` | Everything configured, below |

The sidebar badges count drafts that are open or submitted, and open knowledge
gaps. Home lists the same, plus drafts whose AI reviewer is waiting on a
person's answer.

## Settings

One screen, one section per task. `#/settings` opens Account & tokens.

| Group | Section | Address | Contents |
|---|---|---|---|
| You | Account & tokens | `#/settings/account` | Your name, role and auth state; create and revoke MCP tokens |
| | Appearance | `#/settings/appearance` | Theme, density and answer typeface, saved in this browser |
| People | Members & invites | `#/settings/members` | Admins: roles, suspension, invites, service accounts and their tokens |
| AI | Models | `#/settings/models` | Provider, model and reasoning effort per action |
| | Prompts | `#/settings/prompts` | Each action's instructions, with history; marks edited prompts behind the shipped default |
| | Draft review | `#/settings/review` | Automatic review mode, reviewer, model, whether reviews may apply; review the backlog |
| | Limits | `#/settings/limits` | Token, time and operation budgets per action; concurrent runs |
| Publishing | Documentation | `#/settings/documentation` | GitHub connection (disconnecting asks first), publishing destinations, writing profiles, their audience and templates |
| | Audiences | `#/settings/audiences` | Who documents are written for; per audience, visible and unlabelled statements; labelling status, backfill progress and cost; statements by audience and label state, including curator labels whose text changed since the decision. See [Audiences](AUDIENCES.md) |

What a person can change depends on their role; sections say so where it
applies.

## Older addresses

Bookmarks from either former app still open the right screen. The address bar
is rewritten to the current form.

| Older address | Opens |
|---|---|
| `/cockpit/…` | `/ui/…` |
| `#/b/<id>` | `#/s/<id>` |
| `#/draft/<id>` | `#/drafts/<id>` |
| `#/search?q=…` | `#/find?q=…&mode=grep` |
| `#/coverage` | `#/gaps` |
| `#/mentions`, `#/pending` | `#/names` |
| `#/documentation?tab=settings`, `?tab=profiles` | `#/settings/documentation` (GitHub's install flow returns here) |
| `#/settings` | `#/settings/account` |

## Data the app loads

At start the app loads the whole substrate from `GET /api/data` and builds an
index in memory. Find, Ask, drafts, gaps, activity, documents, names and
settings use their own endpoints. These screens still read the in-memory dump:
Browse, statement and entity detail, both graphs, the draft graph, activity's
context panel, Find's grep entity strip, Ask's provenance titles, the
Documents concept picker, and Home's counts.

## Design system

One token set in `frontend/ui/styles/tokens.css`, dark first with a light
variant. Colour encodes the activity: green (`--bio`) for Ask, cyan (`--cyan`)
for Find and entities, violet (`--write`) for drafts and ingest, amber
(`--warn`) for conditions and gaps. `base.css` holds the shared components
(buttons, fields, cards, notices, chips, tables, tabs, page header);
`shell.css` the sidebar and command bar; `screens.css` and the remaining files
the individual screens.
