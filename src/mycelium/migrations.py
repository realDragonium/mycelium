"""Versioned schema migrations for the substrate.

The runner records the current schema version in SQLite's `user_version`
PRAGMA. On startup, `apply_migrations` compares the stored value to the
latest entry in `MIGRATIONS` and applies every pending function in order.
Each migration commits independently — a failure halts the chain at the
last successful version rather than leaving the DB torn.

Versioning strategy
-------------------
- `SCHEMA` in store.py reflects the **latest** column set. A fresh DB
  reaches the current state via CREATE TABLE IF NOT EXISTS; the runner
  detects "fresh" and fast-forwards `user_version` to the latest with
  no migration functions actually executed.
- Legacy DBs (existing before this work) sit at `user_version=0` with
  a partial schema. The runner detects them and runs every pending
  migration from v1 upward.

A future schema change adds:
1. A new migration function below.
2. A new tuple in `MIGRATIONS`.
3. Updates to `SCHEMA` in store.py so fresh DBs pick it up directly.

That's it — no ad-hoc idempotent ALTER checks scattered through the code.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

# --- migration definitions --------------------------------------------------


def _migration_v1_audit_columns(conn: sqlite3.Connection) -> None:
    """Add `created_at` / `updated_at` / `created_by` / `updated_by` to
    every authored-record table; add `created_at` / `created_by` to the
    insert-only link and join tables. Mirrors the columns the latest
    `SCHEMA` in store.py declares.

    All columns are nullable TEXT — legacy rows stay NULL, matching the
    honest 'we don't know when this was created' answer."""
    full = ("entities", "statements", "names", "annotations")
    create_only = (
        "statement_links",
        "entity_links",
        "statement_annotations",
        "entity_annotations",
    )
    for table in full:
        for col in ("created_at", "updated_at", "created_by", "updated_by"):
            _ensure_column(conn, table, col, "TEXT")
    for table in create_only:
        for col in ("created_at", "created_by"):
            _ensure_column(conn, table, col, "TEXT")


def _migration_v2_when_not_op(conn: sqlite3.Connection) -> None:
    """Widen `when_nodes.op` CHECK constraint from `('and', 'or')` to
    `('and', 'or', 'not')` so NOT can appear in when-expressions.

    SQLite cannot alter a CHECK constraint in place — we rebuild the
    table via the standard rename-and-copy dance. Foreign keys are
    temporarily disabled during the swap; the `when_nodes_new → when_nodes`
    rename preserves the same name so existing FK references from
    `statement_links` (via the `link_id` column) keep pointing at the
    right place once FKs are re-enabled.

    No-op on fresh DBs (already at v2 via SCHEMA), so this only runs
    on a legacy v1 DB."""
    # Skip when when_nodes doesn't exist yet (a partial legacy schema
    # that predates the table entirely — store.migrate() runs SCHEMA
    # before the runner, so this only happens when the runner is
    # invoked directly without SCHEMA, e.g. in tests).
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='when_nodes'"
    ).fetchone()
    if row is None:
        return
    # Skip when the CHECK is already widened (defensive — a legacy DB
    # somehow created from the latest SCHEMA but stuck at v1).
    if "'not'" in row["sql"]:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    # SCHEMA may have already created triggers that reference
    # `when_nodes`. SQLite resolves trigger bodies against the live
    # schema, so dropping the table out from under them fails. Drop
    # the triggers first; v3 (or the next SCHEMA run) recreates them.
    conn.execute("DROP TRIGGER IF EXISTS statement_links_delete_cascade_when")
    conn.execute("DROP TRIGGER IF EXISTS entity_statement_links_delete_cascade_when")
    # Defensive: a previous half-applied migration may have left the
    # scratch table behind.
    conn.execute("DROP TABLE IF EXISTS when_nodes_new")
    try:
        conn.execute("""
            CREATE TABLE when_nodes_new (
                node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id     INTEGER NOT NULL REFERENCES statement_links(link_id) ON DELETE CASCADE,
                parent_id   INTEGER REFERENCES when_nodes_new(node_id) ON DELETE CASCADE,
                op          TEXT,
                statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
                child_index INTEGER NOT NULL,
                CHECK ((op IS NULL) <> (statement_id IS NULL)),
                CHECK (op IS NULL OR op IN ('and', 'or', 'not'))
            )
        """)
        conn.execute(
            "INSERT INTO when_nodes_new "
            "(node_id, link_id, parent_id, op, statement_id, child_index) "
            "SELECT node_id, link_id, parent_id, op, statement_id, child_index "
            "FROM when_nodes"
        )
        conn.execute("DROP TABLE when_nodes")
        conn.execute("ALTER TABLE when_nodes_new RENAME TO when_nodes")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS when_nodes_link_id ON when_nodes (link_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS when_nodes_statement_id "
            "ON when_nodes (statement_id)"
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migration_v3_entity_statement_links(conn: sqlite3.Connection) -> None:
    """Add the `entity_statement_links` table and the `link_kind` column
    on `when_nodes` that discriminates which link table a `when_nodes.link_id`
    points at. The new table is created in `SCHEMA` via CREATE TABLE IF
    NOT EXISTS, so a fresh DB picks it up; this migration backfills
    legacy DBs.

    The `when_nodes.link_id` FK to `statement_links` is also dropped here
    — it's incompatible with a polymorphic owner. We rebuild the table
    without the FK; cascade-on-link-delete becomes an app-level
    responsibility (see `_delete_when_tree`).
    """
    # 1. Create the new table if missing (fresh DBs already have it via
    # SCHEMA; this branch fires for legacy DBs that predate v3).
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_statement_links'"
    ).fetchone()
    if row is None:
        conn.execute("""
            CREATE TABLE entity_statement_links (
                link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    TEXT NOT NULL REFERENCES entities(id),
                statement_id TEXT NOT NULL REFERENCES statements(id),
                direction    TEXT NOT NULL CHECK (direction IN ('es', 'se')),
                link_type    TEXT NOT NULL,
                when_hash    TEXT NOT NULL,
                created_at   TEXT,
                created_by   TEXT,
                UNIQUE (entity_id, statement_id, direction, link_type, when_hash)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS entity_statement_links_entity "
            "ON entity_statement_links (entity_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS entity_statement_links_statement "
            "ON entity_statement_links (statement_id)"
        )

    # 2. Add link_kind to when_nodes and drop the now-incompatible FK.
    wn = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='when_nodes'"
    ).fetchone()
    if wn is None:
        return
    if "link_kind" in (wn["sql"] or ""):
        return  # already migrated

    conn.execute("PRAGMA foreign_keys = OFF")
    # Same reasoning as v2: drop triggers that reference `when_nodes`
    # before swapping the table out from under them. Recreated below.
    conn.execute("DROP TRIGGER IF EXISTS statement_links_delete_cascade_when")
    conn.execute("DROP TRIGGER IF EXISTS entity_statement_links_delete_cascade_when")
    # Defensive: a previous half-applied migration may have left the
    # scratch table behind.
    conn.execute("DROP TABLE IF EXISTS when_nodes_new")
    try:
        conn.execute("""
            CREATE TABLE when_nodes_new (
                node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id     INTEGER NOT NULL,
                link_kind   TEXT NOT NULL DEFAULT 'statement',
                parent_id   INTEGER REFERENCES when_nodes_new(node_id) ON DELETE CASCADE,
                op          TEXT,
                statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
                child_index INTEGER NOT NULL,
                CHECK ((op IS NULL) <> (statement_id IS NULL)),
                CHECK (op IS NULL OR op IN ('and', 'or', 'not')),
                CHECK (link_kind IN ('statement', 'entity_statement'))
            )
        """)
        conn.execute(
            "INSERT INTO when_nodes_new "
            "(node_id, link_id, link_kind, parent_id, op, statement_id, child_index) "
            "SELECT node_id, link_id, 'statement', parent_id, op, statement_id, child_index "
            "FROM when_nodes"
        )
        conn.execute("DROP TABLE when_nodes")
        conn.execute("ALTER TABLE when_nodes_new RENAME TO when_nodes")
        # Recreate indexes.
        conn.execute("DROP INDEX IF EXISTS when_nodes_link_id")
        conn.execute(
            "CREATE INDEX when_nodes_link_id ON when_nodes (link_kind, link_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS when_nodes_statement_id "
            "ON when_nodes (statement_id)"
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    # 3. Create the cascade triggers (they replace the FK-driven cascade
    # we just dropped from when_nodes.link_id).
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS statement_links_delete_cascade_when
        AFTER DELETE ON statement_links
        BEGIN
            DELETE FROM when_nodes
            WHERE link_id = OLD.link_id AND link_kind = 'statement';
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS entity_statement_links_delete_cascade_when
        AFTER DELETE ON entity_statement_links
        BEGIN
            DELETE FROM when_nodes
            WHERE link_id = OLD.link_id AND link_kind = 'entity_statement';
        END
    """)


def _migration_v4_auth_tables(conn: sqlite3.Connection) -> None:
    """Create the `users`, `mcp_tokens`, `invites` tables.

    The CREATE TABLE statements live in `SCHEMA` (store.py) and have
    already run by the time this migration fires — `store.migrate()`
    executes SCHEMA first, then the runner. So this function is a pure
    version bump on legacy DBs (the tables exist via SCHEMA's CREATE
    TABLE IF NOT EXISTS) and a no-op on fresh DBs (which fast-forward
    past every migration). Kept as an explicit entry so the version
    history reflects every schema event uniformly."""
    pass


def _migration_v5_derived_mentions(conn: sqlite3.Connection) -> None:
    """Schema support for DERIVED mentions.

    Adds, for legacy DBs (fresh DBs get all of this from SCHEMA's
    CREATE ... IF NOT EXISTS, which `store.migrate()` runs first):
      - `names.generated_from_name_id` — links an auto-generated plural
        to its source name.
      - `statement_mentions_name` index — reverse lookup the dirty-queue
        worker needs (all statements mentioning a given name).
      - `mention_recompute_queue` — durable async recompute queue.
      - `pending_mentions` — suspect-match review queue.

    The tables/index use IF NOT EXISTS so this is safe whether or not
    SCHEMA ran first. The ADD COLUMN and the statement_mentions index are
    guarded on table existence — `store.migrate()` runs SCHEMA first so
    both exist in real use, but the runner-only migration tests build
    partial legacy schemas that may omit them (same defensive posture as
    v2/v3 with `when_nodes`).
    """
    if _has_table(conn, "names"):
        _ensure_column(
            conn, "names", "generated_from_name_id", "TEXT REFERENCES names(id)"
        )
    if _has_table(conn, "statement_mentions"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS statement_mentions_name "
            "ON statement_mentions (name_id)"
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mention_recompute_queue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            statement_id TEXT REFERENCES statements(id),
            scan_text    TEXT,
            enqueued_at  TEXT NOT NULL,
            claimed_at   TEXT,
            CHECK ((statement_id IS NULL) <> (scan_text IS NULL))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS mention_recompute_queue_open "
        "ON mention_recompute_queue (id) WHERE claimed_at IS NULL"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_mentions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            statement_id TEXT NOT NULL REFERENCES statements(id),
            name_id      TEXT NOT NULL REFERENCES names(id),
            created_at   TEXT NOT NULL,
            approved_at  TEXT,
            approved_by  TEXT,
            rejected_at  TEXT,
            rejected_by  TEXT,
            UNIQUE (statement_id, name_id),
            CHECK (approved_at IS NULL OR rejected_at IS NULL)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS pending_mentions_statement "
        "ON pending_mentions (statement_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS pending_mentions_name ON pending_mentions (name_id)"
    )

    # Backfill on upgrade: a legacy (pre-v5) DB carries hand-asserted
    # statement_mentions the matcher would not reproduce. Enqueue every
    # existing statement so the background worker re-derives them from text on
    # first boot (each recompute DELETE-then-reinserts that statement's rows,
    # so stale links are replaced and suspects queued). Fresh DBs never reach
    # this function (they fast-forward past it), so this only fires on a real
    # upgrade. scripts/backfill_derived_mentions.py does the same eagerly for
    # operators who want it finished before serving traffic.
    if _has_table(conn, "statements"):
        from datetime import datetime, timezone

        t = datetime.now(timezone.utc)
        now = f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"
        conn.execute(
            "INSERT INTO mention_recompute_queue (statement_id, enqueued_at) "
            "SELECT id, ? FROM statements",
            (now,),
        )


def _migration_v6_nocase_names(conn: sqlite3.Connection) -> None:
    """Make name identity case-insensitive.

    `names.text` becomes UNIQUE COLLATE NOCASE, so "Checklist" and
    "checklist" are one name and a case-variant `upsert_entity` resolves
    to the existing entity instead of minting a duplicate. Before the
    constraint can hold, existing case-variant rows are merged:

    1. Group name rows by `lower(text)` (the same ASCII fold NOCASE
       applies). Each group keeps one row — human-authored over
       generated plural, then oldest. The dropped rows'
       `statement_mentions` move to the keeper (duplicates collapse),
       their `pending_mentions` and vector mappings are removed (the
       enqueued recompute below regenerates suspects against the
       keeper), and `generated_from_name_id` references are repointed.
    2. An entity left with zero names is absorbed into the entity that
       kept its name: `entity_links` and `entity_statement_links` rows
       are repointed (self-loops and duplicates dropped — when_nodes of
       dropped rows cascade via trigger), a missing description is
       adopted from it, and the empty entity is deleted. An absorb
       target always keeps at least one name, so it is never itself
       empty and chains cannot form.
    3. `names` is rebuilt with the NOCASE constraint (rename-and-copy,
       as in v2/v3).

    Statements that mentioned a dropped name are enqueued for mention
    recompute so their derived rows settle against the merged names."""
    if not _has_table(conn, "names"):
        return
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='names'"
    ).fetchone()
    if "NOCASE" in ((ddl["sql"] or "").upper()):
        return

    affected, absorb = _v6_merge_variant_names(conn)

    for eid, target in absorb.items():
        if (
            conn.execute(
                "SELECT 1 FROM names WHERE entity_id = ? LIMIT 1", (eid,)
            ).fetchone()
            is not None
        ):
            continue  # kept other names; it stays a distinct entity
        _v6_absorb_entity(conn, eid, target)

    if affected and _has_table(conn, "mention_recompute_queue"):
        from datetime import datetime, timezone

        t = datetime.now(timezone.utc)
        now = f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"
        conn.executemany(
            "INSERT INTO mention_recompute_queue (statement_id, enqueued_at) "
            "VALUES (?, ?)",
            [(sid, now) for sid in sorted(affected)],
        )

    _v6_rebuild_names_nocase(conn)


def _v6_merge_variant_names(
    conn: sqlite3.Connection,
) -> tuple[set[str], dict[str, str]]:
    """v6 step 1: collapse case-variant name rows onto one keeper each.
    Returns `(statement_ids needing mention recompute, entity that lost a
    name -> entity that kept it)`."""
    rows = conn.execute(
        "SELECT id, text, lower(text) AS fold, entity_id, generated_from_name_id, "
        "rowid AS rid FROM names ORDER BY rid"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["fold"], []).append(r)

    mapping: dict[str, str] = {}  # dropped name_id -> keeper name_id
    absorb: dict[str, str] = {}  # entity that lost a name -> entity that kept it
    for group in groups.values():
        if len(group) < 2:
            continue
        keeper = min(
            group,
            key=lambda r: (r["generated_from_name_id"] is not None, r["rid"]),
        )
        for r in group:
            if r["id"] == keeper["id"]:
                continue
            mapping[r["id"]] = keeper["id"]
            if r["entity_id"] != keeper["entity_id"]:
                absorb.setdefault(r["entity_id"], keeper["entity_id"])

    affected: set[str] = set()
    for dropped_id, keeper_id in mapping.items():
        if _has_table(conn, "statement_mentions"):
            affected.update(
                r["statement_id"]
                for r in conn.execute(
                    "SELECT statement_id FROM statement_mentions WHERE name_id = ?",
                    (dropped_id,),
                )
            )
            conn.execute(
                "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) "
                "SELECT statement_id, ? FROM statement_mentions WHERE name_id = ?",
                (keeper_id, dropped_id),
            )
            conn.execute(
                "DELETE FROM statement_mentions WHERE name_id = ?", (dropped_id,)
            )
        if _has_table(conn, "pending_mentions"):
            # A statement can be reachable ONLY through a pending row (a
            # suspect match has no statement_mentions row until approved)
            # — collect it too, or deleting the pending row would erase
            # the review item without the recompute that recreates it
            # against the keeper.
            affected.update(
                r["statement_id"]
                for r in conn.execute(
                    "SELECT statement_id FROM pending_mentions WHERE name_id = ?",
                    (dropped_id,),
                )
            )
            conn.execute(
                "DELETE FROM pending_mentions WHERE name_id = ?", (dropped_id,)
            )
        if _has_table(conn, "name_vector_ids"):
            conn.execute("DELETE FROM name_vector_ids WHERE name_id = ?", (dropped_id,))
        conn.execute(
            "UPDATE names SET generated_from_name_id = ? "
            "WHERE generated_from_name_id = ?",
            (keeper_id, dropped_id),
        )
    conn.execute(
        "UPDATE names SET generated_from_name_id = NULL "
        "WHERE generated_from_name_id = id"
    )
    conn.executemany("DELETE FROM names WHERE id = ?", [(nid,) for nid in mapping])
    return affected, absorb


def _v6_absorb_entity(conn: sqlite3.Connection, eid: str, target: str) -> None:
    """v6 step 2: fold a now-nameless entity into the entity that kept
    its name — links repointed (self-loops and duplicates dropped, the
    dropped rows' when_nodes cascade via trigger), a missing description
    adopted, the empty entity deleted."""
    if _has_table(conn, "entity_links"):
        for r in conn.execute(
            "SELECT rowid AS rid, from_entity_id, to_entity_id, link_type "
            "FROM entity_links WHERE from_entity_id = ? OR to_entity_id = ?",
            (eid, eid),
        ).fetchall():
            new_from = target if r["from_entity_id"] == eid else r["from_entity_id"]
            new_to = target if r["to_entity_id"] == eid else r["to_entity_id"]
            duplicate = (
                new_from == new_to
                or conn.execute(
                    "SELECT 1 FROM entity_links WHERE from_entity_id = ? "
                    "AND to_entity_id = ? AND link_type = ?",
                    (new_from, new_to, r["link_type"]),
                ).fetchone()
                is not None
            )
            if duplicate:
                conn.execute("DELETE FROM entity_links WHERE rowid = ?", (r["rid"],))
            else:
                conn.execute(
                    "UPDATE entity_links SET from_entity_id = ?, to_entity_id = ? "
                    "WHERE rowid = ?",
                    (new_from, new_to, r["rid"]),
                )
    if _has_table(conn, "entity_statement_links"):
        for r in conn.execute(
            "SELECT link_id, statement_id, direction, link_type, when_hash "
            "FROM entity_statement_links WHERE entity_id = ?",
            (eid,),
        ).fetchall():
            duplicate = conn.execute(
                "SELECT 1 FROM entity_statement_links WHERE entity_id = ? "
                "AND statement_id = ? AND direction = ? AND link_type = ? "
                "AND when_hash = ?",
                (
                    target,
                    r["statement_id"],
                    r["direction"],
                    r["link_type"],
                    r["when_hash"],
                ),
            ).fetchone()
            if duplicate is not None:
                conn.execute(
                    "DELETE FROM entity_statement_links WHERE link_id = ?",
                    (r["link_id"],),
                )
            else:
                conn.execute(
                    "UPDATE entity_statement_links SET entity_id = ? WHERE link_id = ?",
                    (target, r["link_id"]),
                )
    conn.execute(
        "UPDATE entities SET description = "
        "(SELECT description FROM entities WHERE id = ?) "
        "WHERE id = ? AND (description IS NULL OR description = '')",
        (eid, target),
    )
    conn.execute("DELETE FROM entities WHERE id = ?", (eid,))


def _v6_rebuild_names_nocase(conn: sqlite3.Connection) -> None:
    """v6 step 3: rebuild `names` with the NOCASE unique constraint
    (rename-and-copy, as in v2/v3).

    Unlike v2/v3, DML has already run by the time this executes (the
    variant merge above), so sqlite3's implicit transaction is open —
    and foreign-key pragmas are silent no-ops inside a transaction.
    Commit before turning enforcement OFF (or the DROP below trips FK
    checks from statement_mentions / name_vector_ids / pending_mentions
    rows referencing `names`), and commit again before turning it back
    ON so that pragma isn't swallowed the same way. The early commit is
    safe: if the rebuild then fails, `user_version` is still 5 and
    re-running v6 is harmless — the merge finds nothing left to do and
    the rebuild retries.
    """
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    # Defensive: a previous half-applied migration may have left the
    # scratch table behind.
    conn.execute("DROP TABLE IF EXISTS names_new")
    try:
        conn.execute("""
            CREATE TABLE names_new (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL COLLATE NOCASE UNIQUE,
                entity_id  TEXT NOT NULL REFERENCES entities(id),
                generated_from_name_id TEXT REFERENCES names_new(id),
                created_at TEXT,
                updated_at TEXT,
                created_by TEXT,
                updated_by TEXT
            )
        """)
        cols = ", ".join(
            r["name"] for r in conn.execute("PRAGMA table_info(names)").fetchall()
        )
        conn.execute(f"INSERT INTO names_new ({cols}) SELECT {cols} FROM names")
        conn.execute("DROP TABLE names")
        conn.execute("ALTER TABLE names_new RENAME TO names")
        # Dropping the table drops its indexes, and SCHEMA already ran for
        # this open — recreate what it created, or an upgrading DB loses the
        # entity index until the next process starts.
        conn.execute("CREATE INDEX IF NOT EXISTS names_entity ON names (entity_id)")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migration_v7_kind_link_matrix(conn: sqlite3.Connection) -> None:
    """Create the `kind_link_matrix` table.

    Like v4, a pure version bump: the CREATE TABLE lives in `SCHEMA` and
    `store.migrate()` runs SCHEMA before the runner, so the table already
    exists on legacy and fresh DBs alike. Seeding is deliberately not done
    here — `store.kind_link_matrix.seed_kind_link_matrix` runs after the
    glossaries it derives from, and only while the table is empty."""
    pass


def _migration_v8_link_type_aliases(conn: sqlite3.Connection) -> None:
    """Create the `link_type_aliases` and embedding queue tables.

    Like v7, a pure version bump: the CREATE TABLEs live in `SCHEMA` and
    `store.migrate()` runs SCHEMA before the runner, so the tables already
    exist on legacy and fresh DBs alike. Seeding is deliberately not done
    here — `store.link_type_aliases.seed_link_type_aliases` runs after the
    glossaries, and only while the table is empty."""
    pass


def _migration_v9_alias_direction(conn: sqlite3.Connection) -> None:
    """Add the `direction` column and align the seeded far-side aliases.

    Fresh DBs get the column from SCHEMA and their directions from seeding, so
    an empty or missing table is left alone. On an already-seeded DB every
    `_REVERSE_SEED` row is flipped regardless of provenance — before v9 the
    column did not exist, so no stored direction was ever a curator's choice —
    and a reverse alias the old seed lacked ("is part of") is inserted with an
    embedding job, since seeding never runs again on a non-empty table.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(link_type_aliases)")}
    if not columns:
        return
    if "direction" not in columns:
        conn.execute(
            "ALTER TABLE link_type_aliases "
            "ADD COLUMN direction TEXT NOT NULL DEFAULT 'forward'"
        )
    if conn.execute("SELECT 1 FROM link_type_aliases LIMIT 1").fetchone() is None:
        return

    from mycelium.store.link_type_aliases import _REVERSE_SEED, _now

    # The one reverse alias the pre-v9 seed never carried; an absent row for
    # any other pair means a curator deleted it, which stands.
    new_in_v9 = {("contains", "is part of")}
    now = _now()
    for link_type, alias in sorted(_REVERSE_SEED):
        updated = conn.execute(
            "UPDATE link_type_aliases SET direction = 'reverse' "
            "WHERE link_type = ? AND alias = ?",
            (link_type, alias),
        ).rowcount
        if updated or (link_type, alias) not in new_in_v9:
            continue
        conn.execute(
            "INSERT INTO link_type_aliases "
            "(link_type, alias, provenance, direction, created_at) "
            "VALUES (?, ?, 'seed', 'reverse', ?)",
            (link_type, alias, now),
        )
        conn.execute(
            "INSERT INTO link_type_alias_embed_queue "
            "(link_type, alias, enqueued_at) VALUES (?, ?, ?)",
            (link_type, alias, now),
        )


# Ordered registry. Tuple format: (target_version, migration_fn).
# Migrations are applied in this order; each one bumps `user_version`
# to its target after committing.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_v1_audit_columns),
    (2, _migration_v2_when_not_op),
    (3, _migration_v3_entity_statement_links),
    (4, _migration_v4_auth_tables),
    (5, _migration_v5_derived_mentions),
    (6, _migration_v6_nocase_names),
    (7, _migration_v7_kind_link_matrix),
    (8, _migration_v8_link_type_aliases),
    (9, _migration_v9_alias_direction),
]

CURRENT_VERSION: int = MIGRATIONS[-1][0]


# --- runner ----------------------------------------------------------------


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring `conn` up to the latest schema version. Idempotent: a DB
    already at `CURRENT_VERSION` is a no-op.

    Detects three cases:
    1. **Fresh DB.** `user_version=0` AND the latest schema columns are
       already present (added by `CREATE TABLE IF NOT EXISTS` in
       store.py's SCHEMA). Fast-forward `user_version` without running
       any migration function.
    2. **Legacy DB.** `user_version=0` AND columns are missing. Apply
       every migration from v1 upward.
    3. **Mid-version DB.** `user_version=N` for some 0<N<CURRENT_VERSION.
       Apply migrations with target > N.

    Refuses to run against a DB ahead of this build (user_version >
    CURRENT_VERSION) — that's a downgrade and we can't trust the schema.
    """
    current = _get_user_version(conn)
    if current > CURRENT_VERSION:
        raise RuntimeError(
            f"database schema version {current} is newer than this build's "
            f"latest known version {CURRENT_VERSION}; aborting to avoid running "
            "against an unknown-future schema (downgrade or upgrade the build)"
        )
    if current == 0 and _looks_like_fresh_db(conn):
        _set_user_version(conn, CURRENT_VERSION)
        conn.commit()
        return
    for target, fn in MIGRATIONS:
        if target <= current:
            continue
        fn(conn)
        _set_user_version(conn, target)
        conn.commit()


# --- helpers ---------------------------------------------------------------


def _get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA writes can't be parameterized; the int is sourced from
    # MIGRATIONS so there's no injection surface.
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, type_decl: str
) -> None:
    """Idempotent `ALTER TABLE ADD COLUMN`. Used inside migrations rather
    than at runtime — runtime now trusts `user_version` instead of
    checking every table on every startup."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {r["name"] for r in rows}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_decl}")


def _looks_like_fresh_db(conn: sqlite3.Connection) -> bool:
    """Heuristic for distinguishing a brand-new DB (created by the
    latest SCHEMA, so all current columns already exist) from a legacy
    DB that predates `user_version` tracking.

    We probe one sentinel column from the latest schema: if it's
    present, every other current-version column is present too (they
    were all added by the same SCHEMA statement). If not, the DB is a
    legacy shape that needs migrations.

    The sentinel checks one column added in a representative past
    migration — `entities.created_at` (v1), `when_nodes.link_kind` (v3),
    `names.generated_from_name_id` (v5), and the NOCASE collation on
    `names.text` (v6). A fresh DB will have all of them (created in one
    shot by `SCHEMA`). A legacy DB at any prior version will be missing
    at least one (CREATE TABLE IF NOT EXISTS leaves existing tables
    untouched, so columns added by ALTER TABLE in past migrations are
    absent until the runner adds them; tables introduced by later
    migrations are present only on fresh DBs or on legacy DBs that have
    already been migrated past them)."""

    def _has(table: str, column: str) -> bool:
        return any(
            r["name"] == column
            for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        )

    def _table_sql(table: str) -> str:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return (row["sql"] or "") if row is not None else ""

    return (
        _has("entities", "created_at")
        and _has("when_nodes", "link_kind")
        and _has("names", "generated_from_name_id")
        and "NOCASE" in _table_sql("names").upper()
    )
