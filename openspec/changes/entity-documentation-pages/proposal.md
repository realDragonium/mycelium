## Why

A developer who wants to learn how one part of a product works has no browsable view of the knowledge base. Search returns single statements, and generated documents are plain Markdown with no diagrams and no links between them. Prototypes on real data showed that pages rendered by code alone read as a list of actions, and that a model writing freely is readable but cannot be trusted to draw a process.

## What Changes

- **Concept links** in a document body, written `[[Concept name]]`, which become links between pages.
- **Flows**: a writer names a start statement, the server draws the steps from the stored links, and the writer places the drawing in the body by name. The drawn flow is stored with the document revision and carried through revisions and edits, so the reviewer, the citations and the rendered page all show the same steps. A concept link's target is stored the same way.
- A **`preview_flow` read tool**, so a writer sees what a flow will draw before it submits one.
- A richer **opening brief** for a document about one concept: where flows start among its statements, and its related and more specific concepts.
- One **renderer** for document bodies, shared by the web app's document view and a new **site export** command that writes a static site for one writing profile: an index, one page per document, a relations block, a folded source list and one theme.
- An **"Entity page" example profile** in the docs, for an administrator to paste; nothing is installed.

The work starts with a trial slice: an external agent writes pages for five linked concepts over MCP through the real write, review and revise path, and the owner reads them before out-of-date detection, the theme and the grouped index are built.

## Impact

- A body without concept links or flows renders, reviews and publishes exactly as today.
- Delivering a document that contains a concept link or a flow to GitHub is refused with a reason. Publishing them there is a later change.
- The opening brief no longer says that every statement about the concept belongs in the document regardless of the template; the template decides how much to cover.
- Which concepts get a page is left to the existing planner and to an operator's requests. The site is not hosted, and there are no sentence-level citations or checks of each sentence against its statements.
