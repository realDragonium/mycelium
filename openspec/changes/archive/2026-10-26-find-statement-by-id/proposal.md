## Why

People and agents often hold a statement id, copied from a link, a draft or an answer's citation. Pasting it into Find or `search_statements` searched it as text and rarely found the statement.

## What Changes

- `search_statements` and `grep_statements` return the statement a query names by id as the first hit, marked `matched_via: "id"` and without a score. The text search fills the rest.
- An id that does not exist is searched as text. The id hit obeys the same filters and audience scope as any other hit.
- Find shows the hit as an exact id match in every mode, so the command bar's Find does too.

## Impact

- Callers that treated a hit without a `score` as a graph expansion must also check `matched_via`.
