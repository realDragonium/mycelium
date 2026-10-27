## Why

A writer or admin could only change knowledge live from the web app. Proposing a change for review needed a separate drafter account or a drafter-scoped token, which the web app cannot use.

## What Changes

- A **Propose as draft** mode in the web app for writers and admins. While it is on, their knowledge writes stage on their own open draft through the same path a drafter's writes take; nothing changes live.
- The mode is a per-request marker the server honours only for real writers and admins, narrowing them to a drafter for that request. It grants a reader or drafter nothing.
- A banner shows while the mode is on, with the open draft's change count and a link to it. The draft is submitted and reviewed like any other.
- Over MCP nothing new: a writer or admin agent proposes through a drafter-scoped token, now documented as the way to do so.

## Impact

- A writer proposing cannot use live-only curation (deciding drafts, the names workspace) in the same request; the web app sends the marker only on knowledge requests.
