---
name: kb-authoring
description: >
  Generate knowledge-base markdown documentation by querying the mycelium substrate for
  product facts and writing them into a Diátaxis-aligned template (tutorial, how-to,
  reference, explanation, or troubleshooting). Use this skill when someone asks to create
  or update a standalone knowledge-base article from product knowledge — when the source of
  truth is the mycelium graph rather than features/, backend/, or frontend/ docs.
---

# Knowledge-Base Authoring from Substrate

The guidance lives in the package, not here:

**Read `src/mycelium/guidelines/kb-authoring/guidance.md` and follow it end to
end.** It is the same text a deployed instance seeds into its prompt store as
`guideline-set` / `kb-authoring/guidance`, so a document written from this
skill and one written by a generation run follow one set of rules.

It addresses a run whose only handle on the set is the store, so it names each
template as a sibling row. You have the checkout — read the file:

| Row the guidance names | File here |
|---|---|
| `kb-authoring/tutorial` | `src/mycelium/guidelines/kb-authoring/templates/tutorial.md` |
| `kb-authoring/how-to` | `src/mycelium/guidelines/kb-authoring/templates/how-to.md` |
| `kb-authoring/reference` | `src/mycelium/guidelines/kb-authoring/templates/reference.md` |
| `kb-authoring/explanation` | `src/mycelium/guidelines/kb-authoring/templates/explanation.md` |
| `kb-authoring/troubleshooting` | `src/mycelium/guidelines/kb-authoring/templates/troubleshooting.md` |

`templates/README.md` in that folder is the longer form of the type-picking
table and of what the `audience` values mean — read it if either is a close
call.

Nothing else differs. Query the substrate as the guidance says, mark anything
it cannot support rather than inventing it, and check the guidance's own
quality checklist before declaring done.
