"""SQLite persistence for entities, names, statements, mentions, and links.

Writes are serialized per connection through `transaction()` — the process
shares one connection per database across request threads, and the unit of
work that handles an external request owns the transaction (helpers never
commit; see the transaction-ownership section below).

Names are first-class: every entity reference flows through a name, and
statement_mentions records which name a statement used (not just which
entity). This preserves enough information to merge entities or split a
name off into its own entity later without losing provenance.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import timestamps

# --- audit context ----------------------------------------------------------
#
# Every write stamps `created_at` / `updated_at` (ISO-8601 UTC) and, when an
# actor is set, `created_by` / `updated_by`. The substrate is single-writer,
# so a module-level current actor is sufficient — when auth lands, the
# server sets this from the connection's principal at the start of each
# call and clears it at the end. Until then it stays None and the *_by
# columns remain NULL.

_actor: str | None = None


def set_actor(actor: str | None) -> None:
    """Set the current actor for subsequent writes. None clears it."""
    global _actor
    _actor = actor


def get_actor() -> str | None:
    return _actor


# --- transaction ownership ---------------------------------------------------
#
# One rule everywhere: helpers never commit — the code handling an external
# unit of work (an MCP tool call, an HTTP request, a worker drain pass) owns
# the transaction and wraps it in `transaction(conn)`. That makes each unit
# of work atomic (a failure rolls the whole thing back instead of leaving a
# half-applied cascade on the connection), and it makes commit timing visible
# at the call site instead of buried per-helper.
#
# The context manager also serializes writers: the process shares one
# connection per database across FastAPI's request threadpool, so two
# concurrent requests could otherwise interleave statements inside each
# other's transactions. Each connection gets one reentrant lock; nested
# `transaction()` blocks on the same connection join the outer transaction
# (only the outermost block commits or rolls back).

# Keyed by id(conn) — sqlite3.Connection is not weak-referenceable. Entries
# are never removed: a process holds a handful of long-lived connections, an
# RLock is tiny, and a recycled id would only ever find an unlocked lock and
# a zero depth (transaction() always restores both on exit).
_txn_locks: dict[int, threading.RLock] = {}
_txn_depth: dict[int, int] = {}
_txn_registry_lock = threading.Lock()


def _txn_lock(conn: sqlite3.Connection) -> threading.RLock:
    with _txn_registry_lock:
        return _txn_locks.setdefault(id(conn), threading.RLock())


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Own the write transaction for one unit of work.

    Acquires the connection's write lock, yields, and commits on success
    or rolls back on exception. Reentrant on the same connection: an inner
    block joins the outer transaction and the outermost block decides.
    """
    with _txn_lock(conn):
        depth = _txn_depth.get(id(conn), 0)
        _txn_depth[id(conn)] = depth + 1
        try:
            yield conn
        except BaseException:
            if depth == 0:
                conn.rollback()
            raise
        else:
            if depth == 0:
                conn.commit()
        finally:
            _txn_depth[id(conn)] = depth


def _now() -> str:
    """ISO-8601 UTC timestamp with millisecond precision and trailing Z.

    Thin alias for the canonical `timestamps.now()`; kept so substrate
    modules can keep calling the package-local `_now`."""
    return timestamps.now()


# --- history recording ------------------------------------------------------
#
# Every state-changing write records an event into the attached `history` DB
# (a separate file from the working DB). The recording happens at the
# store-helper boundary, not via SQL triggers, because triggers can't tell
# `merge_statements` apart from a plain UPDATE — but the store helpers
# carry intent (rename vs. set_entity vs. reassign). Both the data write
# and the history INSERT share one transaction, so an audit log cannot
# diverge from the working DB even if the process crashes between them.
#
# When no history DB is attached (`connect(..., history_path=None)`),
# `_record` is a no-op — tests that don't care can skip it for free.


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _record(
    conn: sqlite3.Connection,
    op: str,
    target_kind: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Append one event to history.history_events. No-op when no history
    DB is attached. Called inside store-helper write paths after the
    main write but before commit, so both records land in the same
    transaction.

    `op` values: create / update / delete / link / unlink / attach / detach.
    `target_kind` mirrors the table (statement, entity, name,
    statement_link, entity_link).
    `target_id` is the row id (or composite "a|b|c" for join tables).
    """
    if not has_history(conn):
        return
    conn.execute(
        "INSERT INTO history.history_events "
        "(at, actor, op, target_kind, target_id, before_json, after_json, context_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(),
            _actor,
            op,
            target_kind,
            target_id,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            json.dumps(context) if context is not None else None,
        ),
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    description TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);

-- `kind` discriminates by the shape of claim the text makes. Starting
-- vocabulary (open — grow as needed, same posture as link types):
--   event      — something happening (present-tense action)
--   state      — a condition holding (is / has / remains)
--   capability — a modal claim (can / may / is able to)
-- The substrate enforces only that kind is non-null; it does not lock
-- the vocabulary, and it does not enforce kind-edge compatibility
-- (e.g., that `triggers` is only between events). Trust the writer.
CREATE TABLE IF NOT EXISTS statements (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS statement_vector_ids (
    statement_id TEXT PRIMARY KEY REFERENCES statements(id),
    vector_id   INTEGER NOT NULL UNIQUE
);

-- `generated_from_name_id` marks an auto-generated regular plural and
-- links it to the singular name it was derived from. NULL means a
-- human-authored name (canonical or alias). Generated plurals are
-- cleaned up / regenerated when their source name is deleted or renamed
-- in app code (no FK cascade — the self-reference can't express it
-- cleanly and we want explicit control). They are ordinary name rows in
-- every other respect, so the exact-match matcher treats them uniformly.
CREATE TABLE IF NOT EXISTS names (
    id         TEXT PRIMARY KEY,
    text       TEXT NOT NULL UNIQUE,
    entity_id  TEXT NOT NULL REFERENCES entities(id),
    generated_from_name_id TEXT REFERENCES names(id),
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS name_vector_ids (
    name_id   TEXT PRIMARY KEY REFERENCES names(id),
    vector_id INTEGER NOT NULL UNIQUE
);

-- statement_mentions are DERIVED, not asserted: the matcher in
-- `mycelium.mentions` scans a statement's text for entity names/aliases
-- and materializes one row per mentioned entity (the representative name
-- the matcher chose). No caller sets these directly. The reverse index
-- supports the dirty-queue worker, which on a name/entity change must find
-- every statement currently mentioning a given name to recompute it.
CREATE TABLE IF NOT EXISTS statement_mentions (
    statement_id TEXT NOT NULL REFERENCES statements(id),
    name_id     TEXT NOT NULL REFERENCES names(id),
    PRIMARY KEY (statement_id, name_id)
);
CREATE INDEX IF NOT EXISTS statement_mentions_name ON statement_mentions (name_id);

-- Statement-to-statement directed edges. The `when_hash` column is the
-- SHA-256 hex of the canonicalized when expression, or the literal
-- sentinel "NONE" for unconditional links — keeping the column NOT NULL
-- lets the UNIQUE constraint do its job (SQLite treats NULLs as distinct
-- under UNIQUE, which would otherwise allow duplicate unconditional
-- links between the same endpoints). The when expression itself lives
-- in `when_nodes`, one row per tree node; an unconditional link has zero
-- rows there.
CREATE TABLE IF NOT EXISTS statement_links (
    link_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_statement_id TEXT NOT NULL REFERENCES statements(id),
    to_statement_id   TEXT NOT NULL REFERENCES statements(id),
    link_type         TEXT NOT NULL,
    when_hash         TEXT NOT NULL,
    created_at        TEXT,
    created_by        TEXT,
    UNIQUE (from_statement_id, to_statement_id, link_type, when_hash)
);

-- Tree storage for `when` expressions. Each row is a node. Internal
-- nodes have `op` set ("and" | "or" | "not") and `statement_id` NULL.
-- Leaves have `statement_id` set and `op` NULL. The CHECK constraint
-- enforces exactly one of the two columns. The root of a link's tree
-- is the node with parent_id = NULL; other nodes nest under it via
-- parent_id. `link_kind` discriminates which link table `link_id`
-- belongs to: 'statement' for statement_links, 'entity_statement' for
-- entity_statement_links. We can't express a conditional FK in SQLite,
-- so the link tables don't FK here — cascade-on-link-delete is enforced
-- in app code (delete the when_nodes rows when the owning link goes
-- away). ON DELETE RESTRICT on statement_id makes deleting a statement
-- referenced anywhere in a when-tree fail loudly — the writer must
-- rewrite or remove the references first.
CREATE TABLE IF NOT EXISTS when_nodes (
    node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id     INTEGER NOT NULL,
    link_kind   TEXT NOT NULL DEFAULT 'statement',
    parent_id   INTEGER REFERENCES when_nodes(node_id) ON DELETE CASCADE,
    op          TEXT,
    statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
    child_index INTEGER NOT NULL,
    CHECK ((op IS NULL) <> (statement_id IS NULL)),
    CHECK (op IS NULL OR op IN ('and', 'or', 'not')),
    CHECK (link_kind IN ('statement', 'entity_statement'))
);
CREATE INDEX IF NOT EXISTS when_nodes_link_id     ON when_nodes (link_kind, link_id);
CREATE INDEX IF NOT EXISTS when_nodes_statement_id ON when_nodes (statement_id);

-- Entity-to-entity directed edges with an open `link_type` vocabulary.
-- Use case: a parent corporation `contains` its subsidiaries; a product
-- is a `kind-of` something more abstract; two providers `replace` each
-- other; etc. Distinct from statement_links because the domain is
-- different — entities are the long-lived hubs, statements are the
-- atomic facts. Mentions still flow through names, not these edges.
CREATE TABLE IF NOT EXISTS entity_links (
    from_entity_id TEXT NOT NULL REFERENCES entities(id),
    to_entity_id   TEXT NOT NULL REFERENCES entities(id),
    link_type      TEXT NOT NULL,
    created_at     TEXT,
    created_by     TEXT,
    PRIMARY KEY (from_entity_id, to_entity_id, link_type)
);

-- Mixed entity↔statement directed edges. Same vocabulary and `when`
-- semantics as statement_links — externally, callers see a single uniform
-- link API where endpoints may be statements or entities. We keep a
-- separate table (rather than overloading statement_links) because
-- endpoints are strongly typed by column: exactly one entity and one
-- statement per row, with `direction` recording which side is the source.
--   direction = 'es' → entity is the source, statement is the target
--   direction = 'se' → statement is the source, entity is the target
-- `when_hash` mirrors statement_links; its tree lives in `when_nodes`
-- under `link_kind = 'entity_statement'`.
CREATE TABLE IF NOT EXISTS entity_statement_links (
    link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id    TEXT NOT NULL REFERENCES entities(id),
    statement_id TEXT NOT NULL REFERENCES statements(id),
    direction    TEXT NOT NULL CHECK (direction IN ('es', 'se')),
    link_type    TEXT NOT NULL,
    when_hash    TEXT NOT NULL,
    created_at   TEXT,
    created_by   TEXT,
    UNIQUE (entity_id, statement_id, direction, link_type, when_hash)
);
CREATE INDEX IF NOT EXISTS entity_statement_links_entity
    ON entity_statement_links (entity_id);
CREATE INDEX IF NOT EXISTS entity_statement_links_statement
    ON entity_statement_links (statement_id);

-- Triggers replace the FK-driven cascade we used to have on
-- `when_nodes.link_id`. The FK had to go (the column is polymorphic
-- now), so each link table fires its own AFTER DELETE trigger that
-- scopes the cleanup by `link_kind`.
CREATE TRIGGER IF NOT EXISTS statement_links_delete_cascade_when
AFTER DELETE ON statement_links
BEGIN
    DELETE FROM when_nodes
    WHERE link_id = OLD.link_id AND link_kind = 'statement';
END;

CREATE TRIGGER IF NOT EXISTS entity_statement_links_delete_cascade_when
AFTER DELETE ON entity_statement_links
BEGIN
    DELETE FROM when_nodes
    WHERE link_id = OLD.link_id AND link_kind = 'entity_statement';
END;

-- Vocabulary glossaries — DB-backed catalogs that document the
-- meaning of each statement `kind`, statement-link `link_type`, and
-- entity-link `link_type` value in use. The MCP / HTTP read tools
-- (list_statement_kinds, list_link_types, list_entity_link_types)
-- read from these tables; the website provides a CRUD surface so
-- definitions can be updated without a redeploy. Seeded on first
-- run from `_STATEMENT_KIND_SEED` / `_STATEMENT_LINK_TYPE_SEED` /
-- `_ENTITY_LINK_TYPE_SEED` below — `INSERT OR IGNORE`, so existing
-- rows are never overwritten by a re-seed.
CREATE TABLE IF NOT EXISTS statement_kind_glossary (
    kind        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    when_to_use TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
CREATE TABLE IF NOT EXISTS statement_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
CREATE TABLE IF NOT EXISTS entity_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);

-- Note: authentication tables (users, mcp_tokens, invites,
-- oauth_clients, oauth_codes) live in a SEPARATE SQLite file managed
-- by `auth_store.py`. The split lets you swap the substrate DB
-- (entities, statements, knowledge) without affecting identity or
-- tokens. See `auth_store.AUTH_SCHEMA`.

-- Reports filed by callers (humans or agents) flagging something
-- they noticed needs attention in the substrate — a missing topic,
-- a contradiction, an unclear claim. Body is free-form text; if the
-- reporter wants to reference an entity or statement, they include
-- it in the text.
--
-- No status column: a row is "open" while both resolved_at and
-- dismissed_at are NULL; "resolved" once resolved_at is set;
-- "dismissed" once dismissed_at is set. The CHECK prevents marking a
-- row both resolved AND dismissed — the two are mutually exclusive
-- terminal states. `created_by` / `resolved_by` / `dismissed_by`
-- store principal ids (mirrors the same actor convention as the
-- substrate audit columns).
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id           TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    resolved_at  TEXT,
    resolved_by  TEXT,
    dismissed_at TEXT,
    dismissed_by TEXT,
    CHECK (resolved_at IS NULL OR dismissed_at IS NULL)
);

-- Durable dirty-queue for asynchronous mention recompute. Statement
-- upsert derives mentions synchronously (hot path stays consistent); a
-- name/alias/entity change instead enqueues work here, drained by the
-- background worker in `mycelium.mention_worker` off the event loop. The
-- row commits in the SAME transaction as the change that dirtied it, so a
-- crash between the two can't lose the recompute. Exactly one of
-- `statement_id` / `scan_text` is set:
--   statement_id — recompute this one statement (its derivable names
--                  changed: a name it mentions moved entity, was deleted,
--                  or its representative shifted).
--   scan_text    — a new/renamed name text became matchable; the worker
--                  scans statement text for this token-sequence and
--                  recomputes every statement that now contains it.
-- `claimed_at` is stamped when the worker takes a row, so an interrupted
-- drain is visible and re-claimable on restart.
CREATE TABLE IF NOT EXISTS mention_recompute_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT REFERENCES statements(id),
    scan_text    TEXT,
    enqueued_at  TEXT NOT NULL,
    claimed_at   TEXT,
    CHECK ((statement_id IS NULL) <> (scan_text IS NULL))
);
CREATE INDEX IF NOT EXISTS mention_recompute_queue_open
    ON mention_recompute_queue (id) WHERE claimed_at IS NULL;

-- Review queue for SUSPECT mention matches. Short/common names (see
-- `mentions.is_suspect_name`) are too ambiguous to auto-link, so a match
-- on one is held here for per-occurrence human approval rather than
-- written as a mention. Terminal-timestamp status, mirroring
-- `knowledge_gaps`: open while both approved_at and rejected_at are NULL;
-- approving inserts the real statement_mentions row. On recompute, an
-- APPROVED occurrence whose name still matches is preserved (a human
-- approval is asserted truth, re-asserted, not destroyed); open and
-- rejected occurrences carry no memory and are re-queued fresh if they
-- still match (the deliberately-dumb rule — no text-diffing). Never
-- exposed through MCP. UNIQUE keeps one open decision per (statement, name).
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
);
CREATE INDEX IF NOT EXISTS pending_mentions_statement
    ON pending_mentions (statement_id);
-- name_id is deleted by the name/entity cascade paths (delete_name,
-- delete_entity, plural regeneration) and FK-checked on name delete, so
-- it needs its own index — same as statement_mentions_name.
CREATE INDEX IF NOT EXISTS pending_mentions_name
    ON pending_mentions (name_id);
"""


def connect(
    db_path: Path | str, history_path: Path | str | None = None
) -> sqlite3.Connection:
    """Open the main DB. When `history_path` is given, attach a second
    database file under the schema name `history`. Writes record audit
    events into `history.history_events` in the same transaction as the
    main write — both commit or both roll back.

    Passing `history_path=None` disables history recording entirely;
    used by tests that don't care, and by tools that only read.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enforce the REFERENCES clauses already declared in the schema.
    # This catches dangling-reference bugs at write time without
    # restricting the open vocabulary or single-writer posture.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + a busy timeout let the background mention-recompute worker
    # (its own connection on its own thread) write without colliding with
    # foreground tool-calls: readers never block the writer, and a writer
    # that finds the lock held waits rather than erroring. WAL is also what
    # litestream replication expects. No-op on :memory: DBs (stays memory).
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    if history_path is not None:
        conn.execute("ATTACH DATABASE ? AS history", (str(history_path),))
    return conn


def has_history(conn: sqlite3.Connection) -> bool:
    """True when a history DB is attached to this connection."""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row["name"] == "history":
            return True
    return False


# Schema for the attached history DB. Lives in the `history` schema so
# inserts read as `INSERT INTO history.history_events (...)`. Kept in a
# separate file so the audit log can be archived, truncated, or detached
# without touching the working DB.
HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS history.history_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    actor        TEXT,
    op           TEXT NOT NULL,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    before_json  TEXT,
    after_json   TEXT,
    context_json TEXT
);
CREATE INDEX IF NOT EXISTS history.history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX IF NOT EXISTS history.history_at
    ON history_events (at);
CREATE INDEX IF NOT EXISTS history.history_actor
    ON history_events (actor);
"""


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the substrate's schema up to the latest version.

    Two-step: first apply `SCHEMA` (CREATE TABLE IF NOT EXISTS, which
    fully creates a fresh DB but is a no-op on existing tables); then
    run the versioned migration runner, which catches up legacy DBs and
    fast-forwards fresh ones. See `mycelium.migrations` for details."""
    from .. import migrations
    from . import glossary

    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn)
    if has_history(conn):
        conn.executescript(HISTORY_SCHEMA)
    glossary.seed_glossaries(conn)
    conn.commit()


# --- links: when-tree round-trip helpers -----------------------------------


def _insert_when_tree(
    conn: sqlite3.Connection,
    link_id: int,
    expr: dict[str, Any],
    *,
    link_kind: str = "statement",
) -> int:
    """Insert every node of the (already-canonicalized) `expr` under
    `link_id`. Returns the root node_id. The caller is responsible for
    canonicalizing first; this function preserves whatever shape it
    receives.

    `link_kind` discriminates which link table owns this tree
    ('statement' for statement_links, 'entity_statement' for
    entity_statement_links) — the column is part of how we look the
    tree back up."""
    return _insert_when_node(conn, link_id, None, 0, expr, link_kind=link_kind)


def _insert_when_node(
    conn: sqlite3.Connection,
    link_id: int,
    parent_id: int | None,
    child_index: int,
    expr: dict[str, Any],
    *,
    link_kind: str = "statement",
) -> int:
    if "statement_id" in expr:
        cur = conn.execute(
            "INSERT INTO when_nodes "
            "(link_id, link_kind, parent_id, op, statement_id, child_index) "
            "VALUES (?, ?, ?, NULL, ?, ?)",
            (link_id, link_kind, parent_id, expr["statement_id"], child_index),
        )
        return cur.lastrowid
    cur = conn.execute(
        "INSERT INTO when_nodes "
        "(link_id, link_kind, parent_id, op, statement_id, child_index) "
        "VALUES (?, ?, ?, ?, NULL, ?)",
        (link_id, link_kind, parent_id, expr["op"], child_index),
    )
    node_id = cur.lastrowid
    for i, child in enumerate(expr["of"]):
        _insert_when_node(conn, link_id, node_id, i, child, link_kind=link_kind)
    return node_id


def _load_when_tree(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    link_kind: str = "statement",
) -> dict[str, Any] | None:
    """Reconstruct the when-expression tree for `link_id`, or None if
    the link is unconditional (no when_nodes rows). `link_kind` selects
    which link table the tree belongs to."""
    rows = conn.execute(
        "SELECT node_id, parent_id, op, statement_id, child_index "
        "FROM when_nodes WHERE link_id = ? AND link_kind = ?",
        (link_id, link_kind),
    ).fetchall()
    if not rows:
        return None

    children_by_parent: dict[int | None, list[sqlite3.Row]] = defaultdict(list)
    nodes_by_id: dict[int, sqlite3.Row] = {}
    for r in rows:
        nodes_by_id[r["node_id"]] = r
        children_by_parent[r["parent_id"]].append(r)
    for kids in children_by_parent.values():
        kids.sort(key=lambda r: r["child_index"])

    roots = children_by_parent.get(None, [])
    if len(roots) != 1:
        # Schema invariant: exactly one root per link. Don't crash on
        # corrupted data — return what we can interpret.
        return None
    return _build_when(roots[0]["node_id"], nodes_by_id, children_by_parent)


def _build_when(
    node_id: int,
    nodes_by_id: dict[int, sqlite3.Row],
    children_by_parent: dict[int | None, list[sqlite3.Row]],
) -> dict[str, Any]:
    n = nodes_by_id[node_id]
    if n["statement_id"] is not None:
        return {"statement_id": n["statement_id"]}
    return {
        "op": n["op"],
        "of": [
            _build_when(c["node_id"], nodes_by_id, children_by_parent)
            for c in children_by_parent.get(node_id, [])
        ],
    }
