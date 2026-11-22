## 1. Remove manual edits from the server

- [x] 1.1 Remove the manual-edit admission (saved document and unsaved draft) and its branches in the run executor and the writing loop
- [x] 1.2 Remove the edit and preview HTTP routes and the `edit_document` MCP tool
- [x] 1.3 Remove the code that recognised runs left by earlier manual edits

## 2. Make GitHub publication one-way

- [x] 2.1 Start every revision from the revision in Mycelium; remove `start_from_destination`, `revision_base` and the `both_sides_edited` refusal
- [x] 2.2 Publish over whatever the file holds; keep the refusal of a file deleted in the open pull request and the no-commit publish of unchanged text
- [x] 2.3 Remove reading a document back from GitHub and the sync state it needed, leaving stored columns in place

## 3. Web app

- [x] 3.1 Remove the page editor, its unsaved-edit guard and the edit buttons on a document and on a run's draft
- [x] 3.2 Remove **Start from the published copy on GitHub** and the note on runs that started there
- [x] 3.3 Rebuild the committed web app

## 4. Documentation

- [x] 4.1 Remove manual edits from the documentation, media, agent task, web app and MCP guides and the documentation skill
- [x] 4.2 Say in the documentation guide and skill that a publish overwrites the file on GitHub
- [x] 4.3 Update the advertised and registered MCP tool counts
