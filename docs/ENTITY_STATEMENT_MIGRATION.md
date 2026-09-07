# Entity↔statement migration

Schema 14 removes authored links between entities and statements. Statement
links and their conditions remain; entity relationships, names, aliases and
derived mentions remain. Conditions now reference their owning statement link
with a cascading foreign key.

## Before upgrading

The upgrade refuses to start when any `entity_statement_links` rows or legacy
entity-link condition nodes remain. It does not discard them. Complete a
knowledge rescue using the previous build before deploying this schema:

1. Preserve the original SQLite database with a consistent SQLite backup. Keep
   its history database as well. Older JSONL exports omitted the mixed link
   table, so an export alone is not proof that this knowledge was preserved.
2. Inventory each legacy link, its endpoints and condition tree. Preserve any
   meaning absent from the statements in self-contained statement text or a
   justified statement relationship. Review that evidence before deletion.
3. Explicitly remove the rescued links using the previous build's `remove_links`
   tool. Its cascade removes their associated condition nodes. Do not delete
   unrelated statement conditions.
4. Check that the legacy link table and entity-kind condition set are empty.
   Retain the rescue mapping and original backup, then upgrade.

Orphan entity-kind conditions also block upgrading. Investigate and preserve
what they describe before explicitly removing them; deleting an empty link
table does not establish that its conditions were rescued.

The rebuild preserves statement condition node IDs, nesting and order, restores
foreign-key enforcement, and rolls back if any condition no longer references
an existing statement link, parent or statement. Startup can be retried after
repair with the previous build.

## Archives

Older archives with statement-only condition nodes remain importable; their
obsolete `link_kind: statement` discriminator is removed during import. Archives
containing mixed links, mixed condition nodes or a nonzero mixed-link manifest
count are rejected before replacing the destination, including forced restores.
Restore those with the previous build and complete the rescue first. An older
archive that omitted an unconditional mixed link cannot recover that link;
consult the original SQLite backup.

Export also refuses a database containing unrescued mixed links or conditions,
instead of producing another incomplete archive. This refusal is read-only;
use SQLite's backup facility to preserve a pre-migration database. Existing
prompt, settings, documentation, history and vector archive handling is unchanged.
