# Alias-based statement discovery

Entity names and aliases identify concepts. Statement text is matched against the
known vocabulary. Distinctive matches form a recomputable discovery index;
ambiguous matches (including short aliases such as SSO) remain possible matches.
Neither shared names nor possible matches create semantic statement links.

The former per-occurrence Mentions review screens and HTTP review endpoints are
retired. Ingestion and recomputation no longer produce pending review tasks.
Existing approval decisions remain effective while their name still matches the
statement. Historical decisions travel with new backups; older archives that did
not export them cannot reconstruct those decisions.

`get_mention_candidates(entity_id, after=0, limit=50)` is available through MCP and
its HTTP mirror. `GET /api/mention-candidates` exposes the same read-only operation.
It returns statement text, matched names, and a match label: `derived`, `approved`
(historical), or `possible`. These labels explain matching, not factual confidence.
Names and aliases management uses this discovery view for statement examples.

A page scans at most 2,000 statements and returns at most 200 matches. Continue
with `next_after` whenever `has_more` is true, including after an empty page.
Pagination reads current data, so concurrent statement edits may change results.
The matcher respects token boundaries and longest-name precedence. A query for
“account” does not claim a match inside the more specific “service account.”

Existing confirmed-mention filters and connection scoring retain their semantics.
Use the candidate operation when investigating ambiguous names; possible matches
are not silently mixed into those confirmed results. Changing vocabulary takes
effect immediately in candidate queries; stored distinctive matches are updated
by the existing recomputation worker.
