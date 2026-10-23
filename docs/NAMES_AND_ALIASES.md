# Names and aliases

Open **Names & aliases**. Search by a concept's name, alias, or
description, then select it to see all names, generated plurals, example
statements, relationships, and recorded changes. Readers can inspect the
vocabulary. Writers can add, correct, prefer, move, or split names. Removing an
alias or merging concepts requires admin access. Drafters cannot apply edits.

The example statements distinguish recognized names, historically approved
references, and possible references. An ambiguous match is discoverable without
becoming an approval task. **Find more matches** continues the bounded search;
**Continue searching statements** advances when a scanned portion has no matches.

## Editing

Every edit has a preview and a separate **Apply reviewed change** button. The
preview explains the effect, shows matching prose, and includes relationship
changes when merging. If the vocabulary, statements, or relationships change
before application, Mycelium rejects the stale preview. Review a new preview to
continue. Statement wording is never rewritten by a vocabulary edit.

- **Add alias:** recognize another name for an existing concept.
- **Correct spelling:** replace an incorrect name. The old spelling stops
  matching; its generated plural is regenerated.
- **Change preferred name:** choose an existing authored name for display. To
  use a new name, add it as an alias first. Previous names remain aliases.
- **Move alias:** move a name and its generated plural to another existing
  concept. The source concept's description and relationships stay put.
- **Split names:** move selected names and their generated plurals to a new
  concept, choosing its description and preferred name. Source relationships
  stay with the source.
- **Merge concepts:** choose the destination, surviving description, and preferred
  name. Names and relationships move to the destination. Duplicate relationships
  and self-links created by the merge are removed.
- **Remove alias:** stop recognizing a name and its generated plural. The concept
  can remain without names and will then be displayed by its identifier.

Generated plurals follow their source name and cannot be independently moved,
removed, or selected as preferred names. New concepts use their first authored
name for display. Existing concepts receive a stable preference using the existing
case-insensitive name ordering, even when that name is a generated plural. Adding
an alias does not rename the concept. Moving or deleting a preferred name selects
and retains a remaining authored name, or another remaining name if no authored
name remains. Bare concepts have no preference. Existing name and entity readers
use the preferred name consistently.

Moving a name to a different concept or correcting its spelling does not carry
historical per-occurrence approvals into the new interpretation. Those decisions
are archived in change history before they are invalidated. Merging equivalent
concepts preserves those decisions.

Preferred-name references are included in substrate backups. Older archives
without a preference restore using the same case-insensitive ordering. The
reference is a deferred foreign key so an archive can restore entities before their names in one
transaction.

## Possible duplicates

**Possible duplicates** lists pairs of concepts whose names suggest they are the
same concept, with every name pair that matched and why. Names are compared as
words, split on spaces, punctuation, `_`, `-` and camelCase:

- the same words once case and punctuation are ignored ("answer type" and
  "Answer-Type");
- the same words in another order or spelling style ("Admin Only Exports" and
  `only_admin_exports`);
- one name spells the initials of the other ("SSO" and "Single sign-on");
- similar meaning, from name embeddings at 75% similarity or more ("Login page"
  and "Sign-in page").

Word matches come first, then similar-meaning matches by similarity. Names
whose wording marks them as different concepts are left out even when they
embed close together, as families of identifiers do:

- one name extends the other ("Login" and "Login page");
- one word takes another's place, as the only difference or right after a word
  both share ("invoice_template_v1" and "invoice_template_v2", "Sign-in page" and
  "Sign-up").
  A word that abbreviates the other ("admin" and "administrator") still
  matches;
- each adds its own words to a shared stem of two or more words, or to words so
  common they mark a family (used in 3% of names, and at least ten).

So a synonym swapped for a single word ("Workspace settings" and "Workspace
preferences") is not listed. The list shows 50 pairs at a time with the total;
**Show more** loads the next 50.

Admins can open either merge direction straight into the merge preview above;
the destination's preferred name and description are preselected. Writers can
mark a pair **Not a duplicate** so it stops appearing. **Dismissed** lists those
pairs, newest first, and **Restore** lets a pair be proposed again. Dismissals
are kept in substrate backups and disappear when either concept is merged away
or deleted.

## API

- `GET /api/names-workspace?q=...`: searchable vocabulary and writer capability.
- `GET /api/names-workspace/{entity_id}`: concept detail and history.
- `POST /api/names-workspace/preview`: `{ "action": { "kind": "add", "entity_id": "...", "text": "..." } }`.
- `POST /api/names-workspace/apply`: the same action plus the preview's
  `expected_revision`. A stale revision returns HTTP 409. A merge reports
  `documents_unanchored`, and the workspace tells the curator when documents
  lost their concept anchor.
- `POST /find-entity-duplicates`: `{ "limit": 50, "offset": 0 }` returns `{ "candidates": [...], "total": N }`, as listed above.
- `POST /api/names-workspace/duplicates/dismiss`:
  `{ "a_entity_id": "...", "b_entity_id": "..." }`. Requires a real writer.
- `GET /api/names-workspace/duplicates/dismissed`: `{ "dismissed": [...] }`, each
  with both ids, `dismissed_at` and `dismissed_by`.
- `POST /api/names-workspace/duplicates/restore`: the same body as dismiss;
  forgets the dismissal. Requires a real writer.
- `GET /api/mention-candidates?entity_id=...&after=...&limit=...`: bounded
  read-only discovery, including ambiguous matches. Follow `next_after` while
  `has_more` is true, even if a page contains no matches.
