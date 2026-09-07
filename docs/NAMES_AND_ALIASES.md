# Names and aliases

Open **Names & aliases** in either UI. Search by a concept's name, alias, or
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
removed, or selected as preferred names. New concepts use their first authored name for display. Existing concepts retain
their previous display name when migrated, even when that name was a generated
plural. Adding an alias does not rename the concept. Moving or deleting a preferred
name selects and retains a remaining authored name, or another remaining name if
no authored name remains. Bare concepts have no preference.
Existing name and entity readers use the preferred name consistently.

Moving a name to a different concept or correcting its spelling does not carry
historical per-occurrence approvals into the new interpretation. Those decisions
are archived in change history before they are invalidated. Merging equivalent
concepts preserves those decisions.

Preferred-name references are included in substrate backups. Older archives
without a preference restore with their previous alphabetical display name. The reference is a
deferred foreign key so an archive can restore entities before their names in one
transaction.

## API

- `GET /api/names-workspace?q=...`: searchable vocabulary and writer capability.
- `GET /api/names-workspace/{entity_id}`: concept detail and history.
- `POST /api/names-workspace/preview`: `{ "action": { "kind": "add", "entity_id": "...", "text": "..." } }`.
- `POST /api/names-workspace/apply`: the same action plus the preview's
  `expected_revision`. A stale revision returns HTTP 409.
- `GET /api/mention-candidates?entity_id=...&after=...&limit=...`: bounded
  read-only discovery, including ambiguous matches. Follow `next_after` while
  `has_more` is true, even if a page contains no matches.
