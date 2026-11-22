## Context

The reader is a developer on the product who wants something more visual than search results: one place to learn a concept and how it relates to others. Agents keep using search. For now readability and ease of use come first; checking each sentence against its statements comes later.

Prototype rounds on a private copy of real data led here:

| Approach | Result |
|---|---|
| Pages rendered by code only | Complete, but reads as actions, not information |
| A model writing freely | Readable, but drops facts and invents steps |
| A model writing every statement as a cited sentence | Complete and traceable, but ten times longer and stiff |
| A model writing short coherent prose and choosing the sections, code drawing flows | Readable; each page took a shape that fits its concept |

What exists and is reused: writing profiles with templates; one document per (profile, template, anchor concept), with a slug that is unique within its profile and template; the planner, which proposes concept-anchored documents and knows each concept's parent; external agents that claim a documentation task, read through the server and submit; the opening brief that lists the anchor concept's statements; document-level citations with out-of-date detection; a reviewer that is told in text what placed media shows; a safe Markdown-to-HTML renderer behind the web app's document view; audience-checked copying of media for publication.

What blocks the prototype's result today, each confirmed in the code:

- The opening brief tells the writer that every statement about the concept belongs in the document. That overrides a template asking for short prose.
- The brief lists statement text without links, so a writer must hydrate statements batch by batch to find a chain of steps.
- A statement id anywhere in a body is refused, and the reviewer is told to fail a body that shows one, or that leaves a placeholder in.

## Goals / Non-Goals

**Goals**

- A page per concept that a developer can read top to bottom and click through.
- Written by an external agent over MCP through the existing agent-task flow.
- Flows the writer cannot invent, that the reviewer can read, and that stay the same from submission through revision to rendered page.
- A styled static site that can be handed to any host.
- Find out early, on real pages, whether the framing works.

**Non-Goals**

- Hosting, custom domains or access control on the exported site.
- Publishing concept links and flows to GitHub.
- A new mechanism for choosing which concepts get a page. The existing planner and an operator's requests do that.
- Sentence-level citations and automatic checks of sentences against statements.
- A directive that prints statements word for word. In the prototypes those bullets read as machine text.

## Decisions

### 1. The body stays Markdown

Review, revisions and out-of-date detection all work on a Markdown body. Two additions are enough. The prototypes used a structured page instead, so the first task tests Markdown with the two additions on the prototype harness before any product code is written.

The frame is read from plain Markdown conventions, with no new syntax. The title is the document's title field; the body carries no title heading. The lead is everything before the first `##` heading. Each `##` heading starts a section and gets an anchor made from its text, with a number added when two headings match.

### 2. Concept links

`[[Invoice]]` or `[[Invoice|invoices]]` (name, optional display text). At submission a name is matched, ignoring case, against the names and aliases of concepts the document's audience may see. A name that matches no concept, or more than one, is not refused: it renders as its text, and the submission's result lists it so the writer can correct it. Readability comes first, and a mistyped link costs the reader nothing. Inside code spans and code blocks the syntax is left alone.

The matched concept id and the name as written are stored with the revision. Rendering uses the stored id, so a renamed concept keeps its link. When the id no longer exists, the name is looked up again: a merged concept's names move to the concept that survives, so the link follows the merge. A name that then matches nothing renders as text.

Stored links travel with the body exactly as flows do (decision 3).

The renderer links to the document anchored on that concept in the same profile, preferring the linking document's template and otherwise the template that comes first by name. A concept without a page renders as its text. A link to the page's own concept renders as its text. In the web app the link opens that document's view; in the site export it is the page's file. For an internal audience the link carries the concept's description as a tooltip.

### 3. Flows are previewed, submitted beside the body, and stored

Placed media is the model: the body carries a short reference, the meaning lives beside it, and the reviewer is told what it shows.

**Preview.** `preview_flow(start, stop?)` returns the flow that would be drawn from `start`: steps, side outcomes and conditions, each with statement id and text, and whether a limit cut it short. `stop` is a list of statement ids. The statements it returns count as read, so they may be cited. It is a read tool of documentation runs only, served like the other reads so an external agent reaches it through `read_for_agent_task`; `ask` does not get it. The limits in decision 4 keep its answer well under the size at which read results are cut.

**Submission.** `emit_document` accepts `flows`: a list of `{name, title, start, stop}`. The body places one with a fenced block holding only its name:

````markdown
```flow
export-request-to-download
```
````

The body therefore contains no statement ids, and the internal-vocabulary rule is unchanged.

**Storage.** At submission the server draws each flow inside the audience and stores, with the document revision, the definition, the drawing, and the ids of the links and conditions it used. Every statement in the drawing is added to the revision's cited statements. The reviewer, the web app and the site export all read the stored drawing.

**Refusals.** All problems with a submission's flows are reported in one refusal, so they cost one of the writer's three attempts. Each names the flow and the reason: a start or stop the writer did not read or the audience may not see; a drawing with fewer than three statements; a placement naming no flow; a flow that is never placed.

**Carried everywhere a body is.** The flows of a revision travel with its body wherever the body goes: the document held for an agent's review, a refused draft, the archive, the web app's preview, and the brief for a revision, which shows each current flow's definition and drawing. The review hold and the revision brief are built before the trial; the rest after it, since the trial may change the format. A revising writer submits `flows` again; what it submits replaces the stored set.

Alternative considered: ids inside a flow block in the body. Rejected: it needs an exception to the id rule and to the reviewer's instructions, and drawing at render time lets the page differ from what was reviewed.

Alternative considered: the writer draws the diagram as text. Rejected: it could show steps and conditions that are not stored.

### 4. How a flow is drawn

From the start statement the walker follows links breadth-first, in stored order:

| Link | Drawn as |
|---|---|
| `proceeds`, `next` | the next step |
| `contains` from an event to an event, or from a procedure to an action | steps marked as part of their parent, in stored order |
| `triggers` | the next step, its arrow labelled as starting a separate process |
| `on-success`, `on-failure` | a branch labelled with the link's meaning |
| `fallback-to` | an alternative listed under its step as "otherwise" |
| `establishes` to a state | a result at the side of its step |

Every statement reached over a step link is a step, including the last one: `A proceeds B proceeds C` draws three steps. A statement is drawn at the side only when it is a result, or when it leads nowhere and its source step also continues elsewhere.

A link's condition is written on its arrow in full, with `and`, `or`, `not` and brackets as stored; condition statements belong to the stored flow. A statement reached twice is drawn once and the second arrival names the step it joins, which also ends any loop. Several links from one step to the same statement draw one arrow that keeps each link's meaning and condition, the conditions joined by "or". The walker does not continue past a `stop` statement.

No drawing rule reads statement text. A refusal is marked as one only where the link type says so (`on-failure`).

Step numbers identify steps; arrows carry the order. Sibling branches are not presented as a sequence.

**Limits.** A drawing holds at most 12 steps and 4 side outcomes per step, and the walk visits at most 60 statements. Side outcomes beyond the fourth, in stored order, are summarised as "and N more". When a step or visit limit is hit the page says the flow continues, and `preview_flow` reports it so the writer can pick a later start or add a stop. The numbers are settled in the trial.

### 5. What the opening brief adds for a document about one concept

- **Where flows start:** statements about the concept that have an outgoing step link and no incoming one from another statement about it, with the number of statements a bounded walk from it draws. Where a loop leaves no such statement, the one with the most outgoing step links is offered. Computed over all the concept's statements, also beyond the 200 the brief lists; the 15 largest are shown. A statement link is visible to an audience when both its ends and its condition statements are, so this section is filled for external audiences too.
- **Related concepts:** the concept's direct concept links, with direction and type.
- **More specific concepts:** concepts it contains or that are a kind of it, each with its statement count.
- **Often named together:** the concepts most often named in the same statements.

Related and more specific concepts are empty for an external audience, where the hierarchy is withheld today. "Often named together" is filled for every audience.

The sentence that every listed statement belongs in the document becomes: each belongs unless it is off-topic or the template asks for a summary.

The writer's protocol gains a short paragraph on concept links and flows. How a page is shaped stays in the profile's template, as the existing rule requires.

### 6. The reviewer

The reviewer's message gains **PLACED FLOWS**: for each placed flow, its title and its steps, outcomes and conditions as text. Its instructions name `[[…]]` and a flow placement as permitted body syntax, not placeholders. It fails conformance for a flow that does not show what the surrounding text describes, as it does for an image. This is built before the trial, because every agent submission passes review.

### 7. One renderer

The web app's Markdown rendering moves to a shared module and learns concept links and flow placements; it is given the revision's stored links and flows. A flow renders as nested lists with classes, each step linking to its entry in the page's source list, so it is readable without a stylesheet and styled by one.

### 8. Site export

`mycelium docs-site --profile <name> --out <dir>` writes an index, one HTML file per document and one stylesheet. (`mycelium export` already means an instance snapshot.)

A deployed server has no shell to run that on, so the same files are also served as one zip: `GET /api/documentation/sites/<profile>`, with optional `title` and `feedback_url`, for a real admin only, because the site holds everything the profile's audience may see whoever asks. The profile's settings in the web app offer it as "Download as a website". The site is built on request from the stored documents; nothing is kept.

- **File names** are `<template>/<slug>.html`, since a slug is unique only within its template; `index.html` sits at the top. The output directory must be missing or empty, so a page left out of this export cannot survive from an earlier one.
- **Page, top to bottom:** a breadcrumb from the index down the concept's parents to the page; title and lead; a contents list built from the section headings; a **context block**; the sections; a folded list of cited statements.
- **Context block,** drawn by code as labelled arrows (for example "Workspace — contains → Invoice"): the concept's direct links, containment and kind before the other types, then the concepts most often named in the document's cited statements, labelled "often appears with" so co-occurrence is not mistaken for structure, ranked by count and then name, leaving out concepts already listed. At most 12 entries. Every entry is shown; one with a page in the export is a link, the others are muted text.
- **Index:** documents grouped under their parent concept, by the planner's existing parent rule, which is reused rather than restated; documents without a parent or an anchor listed flat; a title filter that runs in the browser.
- **Audience:** the export reads stored revisions. A document is left out, and the command names it, when a statement it cites, a statement in one of its flows or a media item it places is no longer visible to the profile's audience. Links resolve only to pages that are in the export. For an external audience the index is flat and the context block holds only "often appears with".
- **Media** is copied with the existing audience-checked publication helper.

It is a command, not a publishing destination, because where the site is hosted is undecided.

### 9. The example profile

`docs/profile-examples/developer-reference.md` holds a profile to paste, with one template, "Entity page":

- **Frame:** the concept name as title; a lead of two to four sentences on what it is and why it exists; a closing "Not documented yet" section when there are open questions.
- **Middle:** sections chosen for this concept and titled as a developer's questions, usually three to seven. Each has one to three short paragraphs and at most one visual: a flow for something that happens in steps, a table for who can see or do what or for comparing cases, a list for precise technical details.
- **Limits:** 350 to 700 words of prose; at most three flows.
- **Style:** everyday language; exact identifiers and thresholds; prose may repeat what a visual shows; link a concept at its first mention in a section.
- **Large concepts:** cover the concept itself and link to its more specific concepts; do not try to cover every statement.
The profile names no GitHub destination.

**Which concepts, in which order.** Nothing new is built. The owner asked to start with the higher-level concepts; for the trial and the first pages an operator requests them in that order. The plan's "Concepts without a document" list and the planner's proposals remain available. A profile has no text that reaches the planner, so ordering the planner's proposals by level would be a change of its own. In the site, the breadcrumb and the grouped index put higher-level concepts first for the reader.

### 10. Out-of-date detection for flows

Stored with each flow is the set of step links leaving its drawn statements, each as source, target, type and condition. A document is out of date when that set differs from the current one, which catches a removed link, a changed condition and a step or branch added to a drawn statement. Link row ids are not used, because replacing a statement's links renumbers them. The comparison is one indexed read; nothing is redrawn while listing documents. The revision brief then says what changed in the flow: a step added or removed, or a condition changed.

### 11. GitHub

Delivering a document whose body has a concept link or a flow placement to GitHub is refused with a reason. A reversible form, like the one media uses, is a later change.

### 12. Stylesheet and theme

The trial uses a plain stylesheet taken from the prototype, enough to read a flow as a flow. The theme is designed after the trial, against the pages it produced, and agreed as a mock before it replaces the plain one. It must hold at phone width, in light and dark, with a long condition, a wide table and a flow at its limits.

## Trial and acceptance

**Before any product code:** the example profile is drafted, and the prototype harness is rerun on three concepts with the writer producing Markdown, concept links and flow placements against that template. The writer is given what the product's brief will give it (statement text, where flows start, related concepts, and an answer to a flow preview on request) and not the full list of links the earlier prototypes handed over. If the writer cannot produce a good page from that, the brief or the format changes here.

**Smoke test:** on a local instance with private data, an external agent takes one process-heavy concept through the whole path: write, review, revise one paragraph, export. This proves flows survive a revision.

**Trial:** the agent then writes a neighbourhood of five concepts that link to each other: a hub with hundreds of statements and four of its neighbours of different kinds (a process, a set of rules, a setting, a small one). The owner reads the exported pages at a desktop width of 1280 pixels. The change continues when, for at least four of the five:

- the lead alone tells a developer what the concept is;
- where the page has a flow, the process can be followed from it without reading the prose twice;
- three other pages of the neighbourhood can be reached by clicking;
- no section reads as a list of raw statements;
- the exact identifiers, values and thresholds a developer needs are on the page;
- the page is at most about six screens of 800 pixels, the hub excepted.

Also recorded per page: reads used, refusals met, and whether the agent needed help. If the trial fails, the template and the limits change first; the body format is reconsidered only if those do not fix it.

## Risks / Trade-offs

- **Prose correctness is unchecked.** Review rules on exposure and conformance. A reader can open the source list but cannot see which sentence rests on which statement. Accepted for now, as the owner asked.
- **Flow steps are statement text.** A step shows the statement's own wording, which can read stiffly. If the trial shows that it hurts, a writer may give a step a caption beside the body; not built before then.
- **Links may not form readable chains.** A flow is only as good as the links. The limits keep a drawing legible; they do not repair a tangled process.
- **Pages are only as good as the concepts.** A subject without its own concept gets no page. Knowledge health addresses that, not this change.
- **Syntax in stored bodies.** Once documents hold `[[…]]` and flow placements, changing the syntax needs a migration.
- **External audiences get a poorer site.** Flat index and a smaller context block. That follows the existing boundary.

## Open Questions

- Should the web app's document view get the theme, or only the plain rendering?
- Is one template enough, or do concept kinds (a record, a process, a setting) need their own once more pages exist? Decided after the trial.

## Decisions after the trial

The trial produced five reviewed pages. The owner read them and asked for the following before any visual work. Where one of these contradicts a decision above, this section wins.

### A. Concept names are always links

Replaces "a concept without a page renders as its text" in decisions 2 and 8.

- **Automatic linking.** In the site export, code links concept names in prose without the writer marking them. Candidates are the names and aliases of concepts named by the statements the document cites. Each concept is linked at its first occurrence in the lead and in each section; whole words only, longest name first, ignoring case; never inside code, headings, existing links or flows; never the page's own concept. A writer's `[[…]]` link still works and counts as that section's link for its concept.
- **Stub pages.** A linked concept with no written page in the export gets a generated page at `concept/<slug>.html`: name, other names, description, relations, how many statements name it, the written pages that link to it, and a note that the page is not written yet. Stubs are generated only for concepts some page links to. A link to a stub is styled differently from a link to a written page.
- External audiences: names are linked the same way; a stub shows only what that audience may see (no description, no relations).

### B. Finding your way

- **Home page.** `index.html` groups written pages under their parent concepts and shows each page's first lead sentence. Stubs are listed after them, muted.
- **Sidebar.** Every page carries the same grouped list, with the current page marked.
- **Search.** A search box on every page searches titles, headings and text of written pages and stub names, from an index file written with the site. It runs in the browser with no external resources and works from `file://`.

### C. What belongs on which page

- **Pages that exist.** The opening brief lists, for the concept's related, more specific and often-named-together concepts that already have a document in the profile, that document's title and first lead paragraph. The guidance tells the writer to link to those pages instead of repeating them.
- **Small concepts.** The example profile's guidance says: a more specific concept with fewer than ten statements is explained in a section of this page; a larger one gets one sentence and a link.

### D. One vocabulary

- The exporter prints "Also called" under the title from the concept's stored names; the writer does not list them.
- The opening brief names the concept's preferred name and tells the writer to use preferred names of concepts throughout.

### E. Image placeholders

- A writer may mark where a picture would help with `![what the picture should show](image-wanted)`. It is permitted body syntax for the writer and the reviewer, needs a description of at least three words, and is not media.
- The renderer shows it as a marked placeholder with the description.
- The site export writes `images-wanted.html`: every placeholder with its page, section and description.
- The placeholder marks where a picture is wanted. Later, agents add the picture themselves once images are part of Mycelium's knowledge; that is not built in this change.

### F. Pages that stay right

- A writer whose page was sent back by review, or refused, receives its last submitted body and flows in the brief, with the findings.
- Decision 10 (out-of-date detection for flows) and the rest of task 5.2 are built now.
- Each exported page shows when its current revision was written.

### G. Readers can push back

`mycelium docs-site --feedback-url <template>` adds a "Report a problem with this page" link to every page. The template may contain `{title}` and `{page}`, which are URL-encoded. Without the option there is no link. Filing a knowledge gap from the static site is not built.

### H. What the pages reveal

The site export writes `site-report.html` and prints a summary: stubs with how many pages link to each, images wanted, documents left out and why, flows cut short by a limit, and concept links a writer wrote that matched nothing. Sending these to the curation queue automatically is not built.
