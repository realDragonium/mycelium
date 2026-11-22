## ADDED Requirements

### Requirement: Concept links in a document body
The system SHALL accept `[[Name]]` and `[[Name|text shown]]` in a document body as a link to a concept, outside code spans and code blocks. At submission each name SHALL be matched, ignoring case, against the names and aliases of concepts the document's audience may see, and the name as written SHALL be stored with the revision beside the concept it matched.

#### Scenario: A link by an alias
- **WHEN** a document body holds `[[invoices]]` and the concept Invoice has the alias "invoices"
- **THEN** the revision stores the link with the name `invoices` and the Invoice concept's id

### Requirement: Unmatched concept links are not refused
A concept link whose name matches no concept the audience may see, or more than one, MUST NOT refuse the document: it SHALL read as its text, and the run SHALL name it.

#### Scenario: A name that matches nothing
- **WHEN** a document body holds `[[Ledgr]]` and no concept the audience may see has that name
- **THEN** the document is recorded, the link reads as "Ledgr", and the run lists `Ledgr` under `unmatched_concept_links` in its summary

### Requirement: Flow preview for documentation runs
The system SHALL offer documentation runs, and no other loop, a read `preview_flow(start, stop?)` that returns the flow drawn from the statement `start`: its numbered steps, each step's arrows, side outcomes and conditions with statement ids and text, `truncated` when a limit cut it short, and `missing` for a `start` or `stop` that does not exist or that the document's audience may not see. Every statement it returns SHALL count as read, so the document may cite it.

#### Scenario: Previewing a chain
- **WHEN** a writer previews the statement "A member requests a workspace export." and two statements follow it over `proceeds` links
- **THEN** the preview holds three steps with their statement ids, and the document may cite all three

#### Scenario: A start the audience may not see
- **WHEN** a writer for an external audience previews a statement that audience may not see
- **THEN** the preview holds no steps and names the statement under `missing`

### Requirement: Flows are submitted beside the body
The system SHALL accept `flows` with a submitted document, each `{name, title, start, stop}`, and SHALL place a flow where the body holds a fenced block with the info string `flow` whose only content is the flow's name. The server SHALL draw each flow from the stored links inside the document's audience, so the body carries no statement ids. On a revision the `flows` submitted SHALL replace the document's stored flows.

#### Scenario: A placed flow
- **WHEN** a writer submits a flow named `export-steps` starting at a statement that leads to two more, and the body holds a `flow` block with `export-steps`
- **THEN** the document is recorded with that flow drawn as three steps

#### Scenario: Revising without the flow
- **WHEN** a writer revises that document with a body that places no flow and submits no `flows`
- **THEN** the new revision holds no flow

### Requirement: How a flow is drawn
The system SHALL draw a flow from its start statement by following stored links breadth-first in stored order, reading no statement text. `proceeds` and `next` SHALL lead to the next step, `contains` (event to event, procedure to action) to a step that is part of its parent, `triggers` to a step that starts a separate process, `on-success` and `on-failure` to a branch named so, and `fallback-to` to an alternative named "otherwise".

#### Scenario: A chain
- **WHEN** statement A proceeds to B and B proceeds to C
- **THEN** the flow from A draws three steps

#### Scenario: A separate process
- **WHEN** a step triggers the statement "The billing worker sends the invoice email."
- **THEN** that statement is a step whose arrow says it starts a separate process

### Requirement: Results, joins, stops and conditions in a flow
An `establishes` link SHALL put its target at the side of its step as a result, and a statement that leads nowhere SHALL be drawn at the side when its step also continues elsewhere. A link's condition SHALL be written on its arrow in words. A statement reached again SHALL be drawn once, the later arrow naming the step it joins. The walk SHALL NOT continue past a `stop` statement, and a link whose target or condition the audience may not see SHALL be left out.

#### Scenario: A loop
- **WHEN** A proceeds to B and B proceeds back to A
- **THEN** the flow from A draws two steps and B's arrow joins step 1

#### Scenario: A result
- **WHEN** a step establishes the state "The export file is available for seven days."
- **THEN** that state is drawn at the side of the step as its result and nothing is drawn from it

#### Scenario: A stop
- **WHEN** A proceeds to B, B proceeds to C and the flow is drawn from A with `stop` holding B
- **THEN** the flow draws A and B only

### Requirement: Flow limits
A drawing SHALL hold at most 12 steps and 4 side outcomes per step, and the walk SHALL visit at most 60 statements. Side outcomes beyond the fourth SHALL be counted, not drawn. Where a step or visit limit cuts the walk, the drawing SHALL be marked truncated, the step where it happened SHALL say the flow continues and name up to three of the statements left out, and the rendered flow SHALL say that it continues.

#### Scenario: A chain of fifteen statements
- **WHEN** a flow is drawn from the first of fifteen statements that each proceed to the next
- **THEN** it draws twelve steps, is marked truncated, and step 12 names the thirteenth statement as where it continues

### Requirement: Flow refusals
The system MUST refuse a submission, naming every problem with its flows in one refusal, when the body places a flow that `flows` does not hold, a flow is never placed, a flow's name is not lowercase letters, digits and hyphens, two flows share a name, a `start` or `stop` does not exist or the audience may not see it, or a drawing holds fewer than three statements.

#### Scenario: Two problems at once
- **WHEN** a submission's body places `refund-steps`, which `flows` does not hold, and `flows` holds `export-steps`, which the body does not place
- **THEN** one refusal names both, and it counts as one refused attempt

#### Scenario: A flow of two statements
- **WHEN** a submitted flow draws only its start and one more statement
- **THEN** the submission is refused saying the flow draws fewer than three statements

### Requirement: Links and flows are stored with the revision
The system SHALL store with each document revision its resolved concept links and each placed flow's definition and drawing, SHALL add every statement a placed flow draws, condition statements included, to the revision's cited statements, and SHALL return them as `concept_links` and `flows` on `get_generated_document` and on a revision read. Documentation archives SHALL carry them.

#### Scenario: Flow statements are cited
- **WHEN** a writer cites one statement and places a flow that draws three others
- **THEN** the revision cites all four

### Requirement: A refused draft keeps its links and flows
A run whose document was refused SHALL keep the draft's concept links and flows and return them as `draft_concept_links` and `draft_flows`.

#### Scenario: A refused draft
- **WHEN** the review refuses a document that places a flow
- **THEN** `get_documentation_run` returns the refused draft with that flow under `draft_flows`

### Requirement: The reviewer sees placed flows
The system SHALL give the document reviewer, for each flow the body places, its title and its steps, side outcomes and conditions as text, and SHALL tell it that concept links, flow placements and image placeholders are permitted body syntax, not placeholders left in.

#### Scenario: Reviewing a page with a flow
- **WHEN** a document that places the flow "From request to download" is reviewed
- **THEN** the reviewer's message lists that flow's steps as text

### Requirement: Rendering concept links and flows
The system SHALL render a document's `body_html` from the links and flows stored with the shown revision: a concept link leads to the document anchored on that concept in the same profile, preferring the same template, and reads as its text when there is none or when it names the document's own concept; a placed flow renders as a captioned figure of its stored drawing. A `flow` block naming no stored flow SHALL render as plain text.

#### Scenario: A link to another page
- **WHEN** a reader opens a document whose body links `[[Invoice]]` and the profile holds a document anchored on Invoice
- **THEN** "Invoice" is a link that opens that document

#### Scenario: A concept without a page
- **WHEN** the body links `[[Workspace]]` and the profile holds no document anchored on Workspace
- **THEN** "Workspace" is shown as text

### Requirement: A flow goes out of date with its links
The system SHALL report a document as `out_of_date` when the step links leaving the statements a placed flow draws, or their conditions, differ from those stored with the drawing. Each difference SHALL be listed under `stale.flow_changes` with the flow's name and title, `change` (`step_added`, `step_removed` or `condition_changed`), the link type and the text of the statements at both ends as the document's audience may read them.

#### Scenario: A step is added
- **WHEN** a statement drawn in a document's flow gets a new `proceeds` link after the document was written
- **THEN** the document reports `stale.status` `out_of_date` with a `step_added` change naming the flow

#### Scenario: A condition changes
- **WHEN** the condition on a link between two drawn steps is replaced
- **THEN** the document reports a `condition_changed` change for that link

### Requirement: Bringing a changed flow current
A revision with `update_sources` of a document whose flow changed SHALL be briefed with each change in the flow, by statement text, and told to preview the flow and submit it again so it is redrawn.

#### Scenario: Revising after a step was removed
- **WHEN** a writer revises with `update_sources` a document whose flow lost a step link
- **THEN** the run's brief names the flow and says which step no longer leads to which

### Requirement: Image placeholders
The system SHALL accept `![description](image-wanted)` in a document body as a mark where a picture would help. It is not media: it needs no media id and is not checked against offered media. A submission MUST be refused when a placeholder's description has fewer than three words, in the same refusal as any flow problem. The rendered document SHALL show the placeholder as a marked note with its description.

#### Scenario: A placeholder with a description
- **WHEN** a body holds `![The export dialog with CSV selected](image-wanted)`
- **THEN** the document is recorded and the page shows a note saying which picture is wanted

#### Scenario: A vague placeholder
- **WHEN** a body holds `![Dialog](image-wanted)`
- **THEN** the submission is refused asking for a description of at least three words

### Requirement: Opening brief for a document about a concept
The system SHALL, for a run anchored on a concept, add to the writer's opening brief the concept's preferred name, up to 15 statements where flows start among the concept's statements (largest drawing first), up to 20 related concepts from its direct links, up to 20 more specific concepts with their statement counts, and up to 10 concepts most often named in the same statements. Related and more specific concepts SHALL be empty for an audience that may not see concept relations.

#### Scenario: Where a flow starts
- **WHEN** a run is anchored on Workspace export and one of its statements leads over step links to four others, with no step link into it from another of the concept's statements
- **THEN** the brief lists that statement under where flows start, with five statements

### Requirement: The brief names pages that exist
The opening brief SHALL list, for the related, more specific and often-named-together concepts that already have a document in the profile whose cited statements the audience may all see, that document's title and opening paragraph, and tell the writer to link to it. The brief SHALL say that each listed statement belongs in the document unless it is off-topic or the template asks for a summary.

#### Scenario: A page that exists
- **WHEN** the anchor concept is related to Invoice and the profile holds a document about Invoice
- **THEN** the brief lists that document's title and how it opens

### Requirement: A revising writer is given the earlier document
The system SHALL give a writer that revises a saved document its current text, its current flows with their definitions and drawings, and the ids of the statements it cites. A writer that retries a refused run with the review's notes SHALL be given the refused draft's text and flows with those notes.

#### Scenario: Revising a page with a flow
- **WHEN** a writer revises a document that places one flow and cites twelve statements
- **THEN** its brief holds the document's text, that flow's definition and steps, and the twelve statement ids

### Requirement: Concept links and flows are not delivered to GitHub
The system MUST refuse to deliver to GitHub a document whose body holds a concept link or a flow placement, naming which it holds.

#### Scenario: Delivering a page with a flow
- **WHEN** a writer publishes a document whose body places a flow
- **THEN** delivery is refused saying only Mycelium renders flow placements, and nothing is sent to GitHub

### Requirement: Static site command
The system SHALL provide `mycelium docs-site --profile <name> --out <dir>` with optional `--title`, `--feedback-url` and `--data-dir`, which writes the profile's current documents as a static site read through the audience the profile writes for, prints what the export revealed and how many files it wrote, and migrates nothing. The site SHALL load nothing from elsewhere and be readable from `file://`. Without `--title` the site is named after the profile, made readable.

#### Scenario: Exporting a profile
- **WHEN** an operator runs `mycelium docs-site --profile developer-reference --out site` on an instance whose profile holds three documents
- **THEN** `site/` holds `index.html`, one page per document, the stylesheet, the script, the search index, `images-wanted.html` and `site-report.html`

#### Scenario: Default title
- **WHEN** the command runs without `--title` for the profile `developer-reference`
- **THEN** the site is titled "Developer reference"

### Requirement: Static site refusals
The system MUST write nothing and say why when the output directory exists and is not an empty directory, the profile does not exist, the profile's audience was retired, the data directory lacks one of the instance's databases, the feedback address does not start with `http:`, `https:` or `mailto:`, or a document's template name or slug is empty, starts with a dot, or holds a path separator or a control character.

#### Scenario: Output directory in use
- **WHEN** the command is given an output directory that holds a file
- **THEN** it exits with an error asking for a new or empty directory and writes nothing

#### Scenario: Unsafe template name
- **WHEN** a document of the profile has the template name `../outside`
- **THEN** no site is written and the refusal names the document and its template name

#### Scenario: Feedback address
- **WHEN** the command is given `--feedback-url javascript:alert(1)`
- **THEN** no site is written and the refusal says the address must start with `http:`, `https:` or `mailto:`

### Requirement: Site pages
The system SHALL write each exported document to `<template>/<slug>.html` holding, in order: a breadcrumb from the home page down the concept's parents; the title; the concept's other names as "Also called"; the lead; a contents list of the section headings; a context block of the concept's direct relations, containment and kind first, at most 12; the sections; the cited statements folded as sources; and the date the revision was written. Placed media SHALL be copied to `media/`.

#### Scenario: A page about a concept
- **WHEN** the document "Workspace export" is anchored on a concept that is part of Workspace and has the other name "data export"
- **THEN** its page has the breadcrumb Home, Workspace, Workspace export, the line "Also called: data export", and a context block listing Workspace under "Part of"

#### Scenario: A placed screenshot
- **WHEN** a document places media `med_0123456789ab`, a PNG its audience may see
- **THEN** the site holds `media/med_0123456789ab.png` and the page shows it

### Requirement: Site feedback link
When a feedback address is given, every written and generated page SHALL carry a "Report a problem with this page" link to it, with `{title}` and `{page}` replaced, URL-encoded, by the page's title and its path within the site. Without one there SHALL be no such link.

#### Scenario: Feedback link
- **WHEN** the site is built with the feedback address `mailto:docs@example.com?subject={title}`
- **THEN** the page "Workspace export" links to `mailto:docs@example.com?subject=Workspace%20export`

### Requirement: Automatic concept links in the site
The system SHALL, in the exported site, link the names and aliases of concepts named by the statements a page cites, without the writer marking them: each concept once in the lead and once in each section, at its first occurrence, as whole words. A name SHALL NOT be linked inside code, headings, links, table headers, flows or image placeholders, and the page's own concept SHALL NOT be linked.

#### Scenario: A name in prose
- **WHEN** a page about Workspace export cites a statement naming Invoice and its lead says "An invoice is exported as CSV."
- **THEN** "invoice" in the lead links to the Invoice page

### Requirement: Generated pages for concepts without a written page
A linked concept with no written page in the export SHALL get a generated page at `concept/<slug>.html` that says it is not written yet and shows the concept's name, other names, description, relations, up to 100 statements naming it with the first 10 unfolded, and the written pages that link to it. A link to a generated page SHALL be marked as not written yet.

#### Scenario: A concept without a written page
- **WHEN** two pages link to the concept Ledger sync and the profile holds no document about it
- **THEN** the site holds `concept/ledger-sync.html`, which lists both pages under "Linked from"

### Requirement: Site home page and sidebar
The system SHALL write `index.html` listing the written pages as a tree under their parent concepts, each with the first sentence of its lead, followed by the generated pages under "Not written yet", and SHALL put the same tree on every page as a sidebar that marks the current page. For an audience that may not see concept relations the pages SHALL form one flat group.

#### Scenario: Grouped pages
- **WHEN** the profile holds pages about Workspace and about Workspace export, which is part of Workspace
- **THEN** the home page lists Workspace export under Workspace

#### Scenario: External audience
- **WHEN** the site is built for an external audience
- **THEN** the home page lists every page in one group and no page has a context block

### Requirement: Site search
The system SHALL write a search index with the site and put a search box on every page that searches, in the browser and without a network request, the titles, other names, headings and text of written pages and the names and descriptions of generated pages. A written page SHALL rank above a generated one, a match in a title or name above a match in text, and a whole word above the start of a word.

#### Scenario: Finding a page by another name
- **WHEN** a reader types "data export" and the page Workspace export is also called "data export"
- **THEN** Workspace export is the first result and the result names the other name it was found by

### Requirement: Search corrects a query that finds nothing
A query that finds nothing SHALL be answered with the results for a corrected spelling, or with close names, when there are any, and the status SHALL say which query the results are for.

#### Scenario: A misspelled word
- **WHEN** a reader types "invioce" and pages mention "invoice"
- **THEN** the results are those for "invoice", and the status says which word was searched

### Requirement: The site stays inside the profile's audience
The system MUST read everything the site shows through the profile's audience, so nothing that audience may not see is written, and MUST leave out, naming the document and the reason, a document that cites a statement, places a flow drawing a statement, or places media that the audience can no longer see, and a document whose template name is one of the site's own file or directory names. Links SHALL lead only to files of the same export.

#### Scenario: A cited statement left the audience
- **WHEN** a statement a document cites is relabelled so the profile's audience may no longer see it
- **THEN** the export has no page for that document and names it as left out with the statement's id

#### Scenario: Media the audience may not see
- **WHEN** a document places an image the profile's external audience may not see
- **THEN** the document is left out and no media file is written

### Requirement: Images-wanted list and site report
The system SHALL write `images-wanted.html`, listing every image placeholder with its page, section and description, and `site-report.html`, listing the linked concepts without a written page with how many pages link to each, the number of images wanted, the documents left out and why, the flows a limit cut short, and the concept links writers wrote that matched no concept. The command SHALL print the same findings.

#### Scenario: A report with findings
- **WHEN** an export leaves out one document and one page holds an image placeholder
- **THEN** `site-report.html` names the document with its reason and says one image is wanted

#### Scenario: Nothing to report
- **WHEN** an export has no generated pages, placeholders, left-out documents, cut flows or unmatched links
- **THEN** each section of the report says "None."

### Requirement: Site download
The system SHALL serve the same files as one zip from `GET /api/documentation/sites/{guideline_set}`, with optional `title` and `feedback_url`, to a real admin only, answering 400 with the reason when the site is refused. The site SHALL be built on request and not kept. The web app SHALL offer it as "Download as a website" on the profile in Settings, with a site name and a feedback address.

#### Scenario: An admin downloads the site
- **WHEN** an admin requests `GET /api/documentation/sites/developer-reference?title=Product%20reference`
- **THEN** the response is a zip named `developer-reference-site.zip` holding `index.html` and the pages, titled "Product reference"

#### Scenario: A writer asks
- **WHEN** a writer requests the same address
- **THEN** the request is refused with 403

#### Scenario: A bad feedback address
- **WHEN** an admin requests the site with `feedback_url=ftp://files.example.com`
- **THEN** the response is 400 with the reason
