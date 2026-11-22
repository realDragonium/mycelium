Step 0 costs no product code. Steps 1 to 3 are the smallest build that lets an external agent write, pass review, revise and export a real page. Step 4 is the trial and a decision point; nothing after it starts until the owner has read the pages.

## 0. Test the body format on the prototype harness

- [x] 0.1 Draft `docs/profile-examples/developer-reference.md`
- [x] 0.2 Rerun the prototype on three concepts: Markdown, `[[…]]` links and flow placements, written against that template from the product's brief shape, with flow previews on request
- [x] 0.3 Render them with the page frame and a plain stylesheet; compare with the structured-page prototypes; change the brief or the format here if the pages are worse

## 1. Flows the writer can see

- [x] 1.1 Flow walker as a pure function, tested on a chain, a branch, a join, a loop, stops and each limit
- [x] 1.2 `preview_flow` read tool for documentation runs, inside the audience, whose statements count as read
- [x] 1.3 Opening brief: where flows start, related, more specific and often-named-together concepts
- [x] 1.4 Opening brief: coverage sentence defers to the template

## 2. Concept links and flows in a document

- [x] 2.1 `emit_document` accepts `flows`; the body places them by name
- [x] 2.2 Store resolved concept links and drawn flows with the revision; add flow statements to the cited statements
- [x] 2.3 Report unmatched concept links in the result; refuse the flow cases in the design, all in one refusal
- [x] 2.4 Carry links and flows through the agent-review hold and into the revision brief
- [x] 2.5 Writer protocol paragraph; reviewer sees PLACED FLOWS and the permitted syntax; submit description in `skills/mycelium-agent-tasks/SKILL.md`
- [x] 2.6 Refuse GitHub delivery of a body with concept links or flow placements

## 3. Rendering

- [x] 3.1 Move the web app's Markdown rendering to a shared module
- [x] 3.2 Render stored concept links and flows; steps link to the source list
- [x] 3.3 `mycelium docs-site`: pages with breadcrumb, contents list, context block from direct links and source list; flat index; plain stylesheet; empty output directory required
- [x] 3.4 Download the site from a running server: admin-only zip route with title and feedback address, and "Download as a website" on the profile in Settings

## 4. Trial (decision point)

- [x] 4.1 Update the example profile with what step 0 taught
- [x] 4.2 Smoke test on a local instance: one concept through write, review, revise, export
- [x] 4.3 An external agent writes the five-concept neighbourhood through the task flow
- [x] 4.4 Record reads, refusals and help needed per page
- [ ] 4.5 Owner reads the pages against the acceptance list; adjust template and limits, or stop

## 5. Keep it true over time

- [x] 5.1 A document is out of date when the step links of a stored flow's statements changed; the revision brief says what changed
- [x] 5.2 Carry links and flows through refused drafts, the archive and the web app's preview
- [ ] 5.3 Leave out of the export any document citing a statement or placing media its audience can no longer see

## 6. Make it a site

- [ ] 6.1 "Often appears with" in the context block
- [ ] 6.2 Grouped index with a title filter; media copied
- [ ] 6.3 Theme: mock, agreement, stylesheet

## 7. Specs and docs

- [ ] 7.1 `documentation` spec delta
- [ ] 7.2 `docs/DOCUMENTATION_MODELS.md`, `docs/MCP_TOOLS.md`, `docs/GUIDELINE_SETS.md`, `docs/AGENT_TASKS.md`

## 8. After the trial: the basis

- [x] 8.1 Brief: pages that exist, preferred names; guidance for small concepts
- [x] 8.2 Image placeholders: protocol, reviewer, check, rendering
- [x] 8.3 A sent-back or refused writer receives its last body and flows
- [x] 8.4 Site: automatic concept links and stub pages
- [x] 8.5 Site: grouped home page, sidebar, search
- [x] 8.6 Site: "Also called", revision date, feedback link, images-wanted list, site report
- [x] 8.7 Write a connected area of about twenty pages and read it
- [x] 8.8 Theme and flow visuals
