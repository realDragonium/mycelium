## Why

A generated document is written by a model or an outside agent from the statements in the knowledge base. Two paths let text from elsewhere into a document. A writer could change a document's title and body by hand, as a run that kept the text and only looked for statements supporting it. And a revision of a published document started from the file on GitHub when someone had edited it there. Text that arrives either way can say something the statements do not, so the document and the knowledge base drift apart.

## What Changes

- **BREAKING** A document's text changes only through a writer run: a request, a revision, a retry or an automatic revision. Manual edits of a saved document and of a finished run's unsaved draft are removed.
- **BREAKING** The HTTP routes `POST /api/documentation/documents/{id}/edits`, `POST /api/documentation/runs/{run_id}/edits` and `POST /api/documentation/preview`, the MCP tool `edit_document` and its route `POST /edit-document` are removed. MCP advertises 84 of 117 registered tools.
- **BREAKING** Publishing to GitHub is one-way. A revision always starts from the revision in Mycelium; `start_from_destination`, `revision_base` and the `both_sides_edited` refusal are removed, and a revision no longer needs GitHub to be reachable.
- **BREAKING** A publish overwrites the file, including changes someone made to it on GitHub by hand. A file deleted in the open pull request is still refused, and a publish of text the open pull request already holds still makes no commit.
- The web app loses **Edit Markdown** on a document, **Edit and review draft** on a run's unsaved draft, and **Start from the published copy on GitHub** on a revision. A refused run's draft stays readable and the run stays retryable.
- A refused run still keeps the draft its writer submitted, with its concept links and flows.

## Impact

- A person who wants different text changes the statements or asks for a revision with a note. Editing the file on GitHub does not last: the next publish replaces it.
- Nothing recognises runs and revisions that earlier manual edits or GitHub starts created. They stay stored and behave like any other: a run left by a manual edit can be retried as an ordinary writer run with its stored request.
- No stored data is changed or dropped. Columns that held the starting text's origin and the GitHub sync point stay and are ignored.
