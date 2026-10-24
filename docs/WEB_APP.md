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
| | Statement | `#/s/<id>` | Text (editable), mentions, connections graph or list, conditions, lineage, audiences with their label's source and reason (curators override; a curator label whose text changed since the decision is flagged to confirm or hand back to AI; a curator confirms or rejects an external grant waiting for confirmation; a relabel after an edit that narrowed the audiences shows why), media (writers upload, edit, label and detach; readers see it) |
| | Entity | `#/e/<id>` | Aliases, mentioning statements, entity links, media |
| | Statement graph | `#/graph?focus=<id>` | Force-directed graph of statements and entities around a picked concept or statement; `?all=1` shows everything |
| | Entity map | `#/entities?focus=<id>` | Entities and their links, framed on a picked concept; `?all=1` without one; add and remove entity links |
| | Documents | `#/documentation` | Plan which documents a profile's audience needs, then approve or dismiss each proposal ([Documentation planning](DOCUMENTATION_PLANNING.md)); generate (optionally about a concept; the form says whether it revises an existing document), edit, review and publish documents; see each pull request's state; see which documents are out of date with their sources and revise them; under **Updates** (counted on the Documents badge), see documents revised automatically since your last visit and those waiting on someone, with what changed and the new revision's diff ([Documentation maintenance](DOCUMENTATION_MODELS.md#keeping-documents-up-to-date)); revise from the published copy when both sides changed; read a document's sources as statement text linked to each statement; retry a run that wrote nothing, or see why the review refused it and retry it with those notes briefed to the writer, also from the plan; follow a run as it works and see what it spent (turns, duration, tokens, estimated cost, statements retrieved and cited, gaps filed) on the run and in the generation history, and read the statements a run cited, written or refused |
| Add knowledge | Ingest text | `#/ingest` | Paste prose; a loop extracts a draft |
| Curate | Drafts | `#/drafts`, `#/drafts/<id>` | Review, edit, submit, approve, reject or withdraw drafts; answer the reviewer's questions; accept, untick or edit the corrections a reviewer suggests and approve with them. A draft from CI links its pull request, merge commit and workflow run; a draft reviewed in parts lists each part's assessment. Each operation shows the evidence its creator attached (location, excerpt and claim; a URL opens). Approving is all-or-nothing: if any statement is refused (the phrasing linter), nothing is applied and each refusal is listed with its reasons. Applying a draft resolves the gaps reported about it |
| | Knowledge health | `#/health`, `#/health/<list>` | Counts of what needs a curator, each opening its list: isolated statements, statements naming no concept, concepts without a description or without statements, statements without an audience label, open gaps, out-of-date documents, old media, pending drafts. Connect the next N isolated or unnamed statements with AI, or a selected batch, as a reviewed draft. Per curation list, which agents hold work, how many items were looked at and with what outcome; an admin releases an agent's claims ([Knowledge health](KNOWLEDGE_HEALTH.md)) |
| | Media | `#/media`, `#/media?show=unattached\|no_alt_text\|unlabelled\|old` | The screenshot and recording library: upload, filter, edit alt text and caption, replace, label for audiences, attach to a statement or concept by id, detach; admins delete ([Media](MEDIA.md)) |
| | Knowledge gaps | `#/gaps` | Resolve, dismiss or reopen reported gaps (writers and admins; others see the list only); follow a gap to the statement, draft or document it names |
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
| Instance | Set up Mycelium | `#/settings/setup` | Admins: the setup checklist (see below) |
| People | Members & invites | `#/settings/members` | Admins: roles, suspension, invites, service accounts and their tokens |
| AI | Models | `#/settings/models` | The model catalog (which models can be chosen, per provider); provider, model and reasoning effort per action |
| | Prompts | `#/settings/prompts` | Each action's instructions, with history; marks edited prompts behind the shipped default |
| | Draft review | `#/settings/review` | Automatic review mode, where it runs (Claude, OpenAI or External agent), reviewer, model, whether reviews may apply and whether only clean approvals apply automatically; review the backlog oldest first, with an optional spending limit, pause and resume |
| | Limits | `#/settings/limits` | Token, time and operation budgets per action; concurrent runs; the quiet period and daily cap for automatic document revisions |
| | AI usage | `#/settings/usage` | Admins: tokens used in the last 7, 30 or 90 days per day, action and model, with totals and the runs that used the most linked to their run, plan or draft; the optional monthly token budget. Mycelium keeps no prices; spend is on each provider's billing dashboard. See [AI usage and budget](AI_MODELS.md#ai-usage-and-budget) |
| Publishing | Documentation | `#/settings/documentation` | GitHub connection (disconnecting asks first), publishing destinations, writing profiles, their audience, maintenance policy and templates |
| | Audiences | `#/settings/audiences` | Who documents are written for and which audiences each includes; per audience, visible and unlabelled statements; labelling status, backfill progress and tokens used; statements by audience and label state, including curator labels whose text changed since the decision; external grants waiting for confirmation, grouped by concept, confirmed or rejected one by one, per concept, or by reviewing a random sample and accepting the rest (counted on the Audiences link); recently edited statements whose confirmed external grant stayed in force, with old and new text, to confirm or narrow. See [Audiences](AUDIENCES.md) |

What a person can change depends on their role; sections say so where it
applies. A save in any settings section reloads the other settings shown on
the page and the banners, so a value saved in one card shows in the next
without a page reload. A card with unsaved edits keeps them.

Model fields are choices from the model catalog on **Settings → Models**. The
catalog checks IDs against their provider: the Claude list refuses an OpenAI
model ID and the other way round. A model an action uses cannot
be removed until the action is moved to another one.

### Setup checklist

Until every step is done or dismissed, admins see a **Set up Mycelium** card
on Home listing the open steps; **Settings → Set up Mycelium** shows them all.
Each step links to the section that completes it:

| Step | Done when |
|---|---|
| AI provider credentials | The providers of the actions in use (Draft review only when it is on) have credentials on the server |
| Models for each AI action | Every action in use has a model ID |
| Audiences reviewed and statements labelled | An audience has been edited and every statement has a label |
| A writing profile with an audience | A profile names an audience explicitly |
| GitHub connection and destination (optional) | A publishing destination exists, outside quarantine (which refuses GitHub delivery) |
| Draft review mode | Review settings were saved, or review is on |
| Monthly AI budget (optional) | A monthly limit is set |

Statuses are read from saved settings and counts; credentials are checked for
presence only, never with a provider request. A dismissed step can be restored
from the Settings section. `GET /api/setup` returns the checklist and
`PUT /api/setup/steps/{step}` with `{"dismissed": true|false}` dismisses or
restores a step; both are admin-only.

### Banners

Banners above every screen report conditions that last until an operator acts:

- **Quarantine**: the server was started with `--quarantine`; background AI
  work, draft review and GitHub publishing are off. See
  [Opening a copy of production data](DEPLOYMENT.md#opening-a-copy-of-production-data).
- **Partial restore**: startup found databases missing beside a populated
  knowledge base.

An open tab rechecks these two every minute while it is visible, and when it
regains focus, so a server restart shows without reloading the page.
- **AI budget** (admins): this month's tokens passed the monthly budget's warning
  percentage.
- **Background AI work is waiting** (admins): automatic draft review, audience
  labelling or automatic document revision is on but its provider has no
  credentials. Those workers wait without starting runs until credentials are
  configured.

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

Home reads only its own endpoints, so it opens without the substrate: its
counts come from `GET /api/substrate-counts`. Neither graph opens on the whole
substrate, which on a real knowledge base is an unreadable clump: without a
focus both show a concept picker from `GET /api/graph/concepts`, and the
statement graph around a focus loads only that neighbourhood from
`GET /api/graph/neighbourhood?focus=<id>`. The first other screen opened
loads the whole substrate from `GET /api/data` and builds an index in memory,
which every later screen reuses. Find, Ask, drafts, gaps, activity, documents,
names and settings use their own endpoints, and so does Knowledge health, which
counts on the server. These screens still read the in-memory dump: Browse,
statement and entity detail, either graph showing everything, the entity map,
the draft graph, activity's context
panel, Find's grep entity strip, Ask's provenance titles and the Documents
concept picker.

The build's bundles under `/ui/assets/` are named after their content, so
they are served without a session and cached for a year
(`public, immutable`). Every other file under `/ui/` is revalidated on each
load (`no-cache, private`), so a deploy shows at once and a shared cache such
as a CDN never keeps a gated page. Of those, only the fonts under
`/ui/fonts/` are served without a session, for the public `/connect` page.

## Design system

One token set in `frontend/ui/styles/tokens.css`, dark first with a light
variant. Colour encodes the activity: green (`--bio`) for Ask, cyan (`--cyan`)
for Find and entities, violet (`--write`) for drafts and ingest, amber
(`--warn`) for conditions and gaps. `base.css` holds the shared components
(buttons, fields, cards, notices, chips, tables, tabs, page header);
`shell.css` the sidebar and command bar; `screens.css` and the remaining files
the individual screens.
