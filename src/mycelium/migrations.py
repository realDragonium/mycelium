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


# Ordered registry. Tuple format: (target_version, migration_fn).
# Migrations are applied in this order; each one bumps `user_version`
# to its target after committing.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_v1_audit_columns),
    (2, _migration_v2_when_not_op),
    (3, _migration_v3_entity_statement_links),
    (4, _migration_v4_auth_tables),
    (5, _migration_v5_derived_mentions),
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
    and `names.generated_from_name_id` (v5). A fresh DB will have all
    three (created in one shot by `SCHEMA`). A legacy DB at any prior
    version will be missing at least one (CREATE TABLE IF NOT EXISTS
    leaves existing tables untouched, so columns added by ALTER TABLE in
    past migrations are absent until the runner adds them; tables
    introduced by later migrations are present only on fresh DBs or on
    legacy DBs that have already been migrated past them)."""

    def _has(table: str, column: str) -> bool:
        return any(
            r["name"] == column
            for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        )

    def _has_table(table: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )

    return (
        _has("entities", "created_at")
        and _has("when_nodes", "link_kind")
        and _has("names", "generated_from_name_id")
    )
