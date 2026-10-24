# storage-and-backup Specification

## Purpose
Keep an instance's state in one data directory of SQLite databases and derived index files, upgrade it safely on startup, and move it between hosts or recover it through portable export archives.

## Requirements

### Requirement: Data directory
The system SHALL keep all instance state in one data directory, taken from the `--data-dir` option of the `mycelium` command, otherwise `MYCELIUM_DATA_DIR`, otherwise `./.mycelium`, and SHALL create the directory on first start.

#### Scenario: Default location
- **WHEN** `mycelium-http` starts with `MYCELIUM_DATA_DIR` unset
- **THEN** it reads and writes `./.mycelium` relative to its working directory

### Requirement: Instance databases
The system SHALL store knowledge in `mycelium.db`, the audit log in `mycelium-history.db`, users and tokens in `mycelium-auth.db`, drafts, documentation runs and the AI usage ledger in `mycelium-drafts.db`, prompt texts and instance settings in `mycelium-prompts.db`, and media in `mycelium-media.db`, and SHALL keep the statement and name vector indexes in `mycelium.vec` and `mycelium-names.vec` beside them.

#### Scenario: Listing the files to restore
- **WHEN** an operator runs `mycelium databases`
- **THEN** it prints `mycelium.db`, `mycelium-history.db`, `mycelium-auth.db`, `mycelium-drafts.db`, `mycelium-prompts.db` and `mycelium-media.db`, one per line

### Requirement: Databases use WAL mode
The system SHALL open its databases in SQLite WAL mode with a 5-second busy timeout, so that copying a live database file is not a safe backup.

#### Scenario: Journal mode of a running instance
- **WHEN** the server has opened `mycelium-drafts.db`
- **THEN** `PRAGMA journal_mode` on that file reports `wal`
- **AND** a consistent copy must be taken with `mycelium export` rather than by copying the file

### Requirement: Partial restore detection
The system SHALL, before opening the data directory, detect a substrate that holds statements or entities while a peer database that its schema version always creates is missing or empty, log a `PARTIAL RESTORE` error naming the missing files, and report them in `partial_restore` from `/api/server-info`, while still starting with those databases recreated empty.

#### Scenario: Restore without the auth database
- **WHEN** a data directory holding knowledge is started without `mycelium-auth.db`
- **THEN** startup logs a `PARTIAL RESTORE` error naming `mycelium-auth.db`
- **AND** `/api/server-info` answers 200 with `"partial_restore": ["mycelium-auth.db"]`

#### Scenario: Fresh instance
- **WHEN** an empty data directory starts
- **THEN** no partial restore is reported

### Requirement: Substrate schema version
The system SHALL record the substrate schema version in `mycelium.db`'s `user_version`, and on startup SHALL apply every migration above the stored version in order, up to the build's current version (25).

#### Scenario: Instance at an older version
- **WHEN** a substrate at schema version 21 starts on a build at version 25
- **THEN** migrations 22 through 25 run in order and `user_version` becomes 25

#### Scenario: Restart at the current version
- **WHEN** a substrate already at the current version starts
- **THEN** no migration runs

### Requirement: Fresh databases skip migrations
The system SHALL create a new substrate directly at the current schema and set its version without running any migration.

#### Scenario: First start
- **WHEN** a new data directory starts
- **THEN** `mycelium.db` is created at the current schema version and no migration is logged

### Requirement: Migrations commit one at a time
The system SHALL commit each migration and its version number together, so that a failed migration leaves the substrate at the last version that completed.

#### Scenario: Failure partway
- **WHEN** migration 24 fails during an upgrade from 22
- **THEN** the substrate stays at version 23 and startup fails

### Requirement: Migrations are logged
The system SHALL log each migration it runs with its version, name and duration.

#### Scenario: Progress in the log
- **WHEN** migration 21 runs
- **THEN** the log shows "substrate migration v21 (audience labels): starting" and then "... done in" with the seconds taken

### Requirement: No schema downgrade
The system MUST refuse to start on a substrate whose schema version is newer than the build knows, without changing it.

#### Scenario: Older build on migrated data
- **WHEN** a build whose latest version is 24 starts on a substrate at version 25
- **THEN** startup fails with "database schema version 25 is newer than this build's latest known version 24" and the database is unchanged

### Requirement: Unrescued legacy links block upgrade
The system MUST refuse to migrate a substrate below version 14 that still holds legacy entity-to-statement links or non-statement condition nodes, and MUST refuse to export such a substrate, without deleting those links.

#### Scenario: Legacy links remain
- **WHEN** a version-12 substrate with legacy entity-to-statement links starts on a current build
- **THEN** startup fails with a message that the knowledge rescue must be completed first, and no legacy link is deleted

### Requirement: Auxiliary databases upgrade themselves
The system SHALL bring `mycelium-history.db`, `mycelium-auth.db`, `mycelium-drafts.db`, `mycelium-prompts.db` and `mycelium-media.db` up to the build's shape on every start without a schema version, and an older build SHALL NOT refuse them.

#### Scenario: Removed feature data
- **WHEN** a current build starts on an instance that still holds research-feature settings in `mycelium-prompts.db`
- **THEN** the research instructions, model selection, limits, sources and concurrency limit are deleted

### Requirement: Upgrades keep data
The system SHALL upgrade a populated instance from every shipped schema version to the current one without losing rows, except where a migration deliberately rewrites them, ending in the schema a fresh database has.

#### Scenario: Upgrade from an old fixture
- **WHEN** a populated instance captured at schema version 14 starts on the current build
- **THEN** every statement, entity, link and draft it held is still present afterwards

### Requirement: Export archive
The system SHALL write, through `mycelium export <archive>`, one gzip-compressed tar archive containing a `manifest.json`, the substrate's relational data, the audit log, auth records, drafts and their reviews, applications and runs with the AI usage ledger, every prompt-text version including retirements, when each shipped prompt default was first seen, generated documentation, media, saved draft-review, model and product settings, and the vector indexes with their `.meta.json` files.

#### Scenario: Export prints counts
- **WHEN** an operator runs `mycelium export /backups/workspace-kb.tar.gz`
- **THEN** the archive is written and a row count per table is printed to standard error

#### Scenario: No substrate
- **WHEN** an operator exports a data directory without `mycelium.db`
- **THEN** the export fails and no archive is written

### Requirement: Export options
The system SHALL leave the audit log out with `--no-history`, the vector indexes and their ID mappings out with `--no-vectors`, and screenshots and recordings out with `--no-media`, recording each choice in the manifest.

#### Scenario: Smaller archive without media
- **WHEN** an operator exports with `--no-media`
- **THEN** the manifest has `includes_media` false and the archive holds no `media.jsonl`

### Requirement: Export is safe while serving
The system SHALL read each database as one consistent snapshot without writing to the live files, so that export can run while the server serves, while different databases MAY be read at different moments.

#### Scenario: Writes during export
- **WHEN** a statement and a link to it are written while an export reads the substrate
- **THEN** the archive holds either both or neither

### Requirement: Archives are owner-only
The system SHALL create the export archive with mode 0600 before writing any data to it.

#### Scenario: File permissions
- **WHEN** an export finishes
- **THEN** the archive is readable and writable only by its owner

### Requirement: Deliberately unarchived data
The system SHALL leave out of archives only OAuth authorization codes and consent screens, pending media upload links, outside agents' curation claims, the one-time settings-import markers and the removed operation telemetry, and SHALL archive every other table of every instance database.

#### Scenario: Curation claims after a restore
- **WHEN** an instance is restored from an archive taken while an agent held curation claims
- **THEN** the restored instance has no claims and the agent must claim again

### Requirement: Unreadable configuration blocks export
The system MUST fail an export when saved model, draft-review or product settings cannot be read, and SHALL instead export without a prompt-text section when only prompt-text rows cannot be serialised.

#### Scenario: Corrupt model settings
- **WHEN** a saved model selection cannot be parsed
- **THEN** `mycelium export` fails rather than writing an archive without it

### Requirement: Import into an empty data directory
The system SHALL restore an archive with `mycelium import <archive>` only into a data directory that holds no instance databases, and MUST otherwise refuse unless `--force` is given.

#### Scenario: Existing instance
- **WHEN** an operator imports into a data directory that already holds `mycelium.db`
- **THEN** the import fails saying the directory already contains an instance

### Requirement: Forced import keeps a safety export
The system SHALL, on `mycelium import --force` over an existing substrate, first export it to `<data dir>.before-restore.<UTC timestamp>.tar.gz` beside the data directory and then replace the instance, and MUST refuse a forced import into a directory holding documentation data without a substrate.

#### Scenario: Forced restore
- **WHEN** an operator force-imports an archive over `/srv/kb/data`
- **THEN** a file `/srv/kb/data.before-restore.<timestamp>.tar.gz` is written before any data is replaced

### Requirement: Archive compatibility
The system SHALL import an archive written by the same or an older build and MUST refuse an archive whose `schema_version` is newer than the build's, or that has no valid `manifest.json`.

#### Scenario: Archive from a newer build
- **WHEN** a build at schema version 24 imports an archive with `schema_version` 25
- **THEN** the import fails saying the build is too old for the archive

#### Scenario: Older archive
- **WHEN** a current build imports an archive from schema version 12
- **THEN** the data is restored and brought to the current shape

### Requirement: Archives are validated before the target changes
The system SHALL check the archive's settings, documentation and section contents before replacing anything in the data directory, treat archive contents as untrusted (no unsafe paths, no columns the destination table lacks), and skip records of removed tables.

#### Scenario: Unknown column
- **WHEN** an archive record names a column the destination table does not have
- **THEN** the import fails without leaving a partial database

#### Scenario: Removed-feature records
- **WHEN** an archive carries records of the removed annotation or research features
- **THEN** those records are skipped and the rest is restored

### Requirement: Sections replace only what the archive carries
The system SHALL replace the auth, drafts, shipped-default and media tables only when the archive carries that section, leaving a target's existing rows in place otherwise.

#### Scenario: Restore of a no-media archive
- **WHEN** an archive exported with `--no-media` is force-imported over an instance that has media
- **THEN** the media already in the data directory is kept

### Requirement: Restore never imports the environment
The system MUST NOT import legacy environment configuration into a restored instance; settings come from the archive, and an archive without them gets built-in defaults with draft review off.

#### Scenario: Restore on a host with legacy variables
- **WHEN** an archive is imported on a host where `MYCELIUM_INGEST_MODEL` is set and the restored instance is started
- **THEN** the `ingest` model comes from the archive or the built-in default, never from the variable

### Requirement: Restored GitHub App connections are disabled
The system SHALL restore GitHub App connections from an archive in a disabled state.

#### Scenario: Moving hosts
- **WHEN** an instance with an enabled GitHub App connection is exported and imported on a new host
- **THEN** the connection exists on the new host but is disabled until an admin re-enables it

### Requirement: Inconsistent indexes are rebuilt
The system SHALL copy an archived vector index into the data directory only when it serves exactly the archived vector IDs, and otherwise leave it out so that the next start rebuilds it by re-embedding.

#### Scenario: Index changed during a live export
- **WHEN** a statement was deleted between the export's database snapshot and its index copy
- **THEN** import logs that the index disagrees and does not restore it, and the next start rebuilds it

### Requirement: Import reports the archive's counts
The system SHALL print, after an import, the archive's `exported_at` and the row counts recorded in its manifest.

#### Scenario: Checking a backup
- **WHEN** an operator imports an archive into a scratch directory
- **THEN** the printed counts are the ones recorded at export, not a recount of the restored data

### Requirement: Knowledge-base scaffold
The system SHALL create, through `mycelium-init <directory>`, a knowledge-base directory holding an empty `data/` directory, a `.mcp.json` that starts this installation's stdio server with `MYCELIUM_DATA_DIR` pointing at `data/`, a `.gitignore` excluding `data/` and `.mcp.json`, and a README, and MUST refuse a non-empty directory.

#### Scenario: Non-empty target
- **WHEN** an operator runs `mycelium-init` on a directory that already contains files
- **THEN** it exits with "refusing to overwrite non-empty directory" and writes nothing
