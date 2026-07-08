"""SQLite persistence for entities, names, statements, mentions, and links.

Single-writer. No concurrency safety. The substrate trusts the writer.

Names are first-class: every entity reference flows through a name, and
statement_mentions records which name a statement used (not just which
entity). This preserves enough information to merge entities or split a
name off into its own entity later without losing provenance.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import mentions

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


def _now() -> str:
    """ISO-8601 UTC timestamp with millisecond precision and trailing Z."""
    t = datetime.now(timezone.utc)
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"


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
    `target_kind` mirrors the table (statement, annotation, entity, name,
    statement_link, entity_link, statement_annotation, entity_annotation).
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

-- Annotations are typed, embedded propositions about statements or
-- entities that aren't themselves event/state/capability claims.
-- Same `(text + embedding + mentions)` shape as a statement, but
-- multi-attached via statement_annotations / entity_annotations
-- (a single permission rule can govern many events).
--
-- `kind` is the deliberate, first-class discriminator — parallel to
-- statements.kind, but discriminating by *purpose of note* rather
-- than shape of claim. Starting vocabulary (open — grow as needed,
-- same posture as statement kinds and link types):
--   definition — what something is (concept, term, role)
--   default    — the implicit value or behavior when nothing overrides
--   example    — a concrete instance illustrating a statement or entity
--   note       — design rationale, caveat, or other context
-- The substrate enforces only that kind is non-null; it does not lock
-- the vocabulary or impose grammatical rules per kind (annotations
-- discriminate by purpose, not phrasing).
--
-- Annotations survive deletion of any statement they were attached
-- to; orphans are tolerated and cleaned up by an explicit user action,
-- never as a side-effect.
CREATE TABLE IF NOT EXISTS annotations (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);
CREATE TABLE IF NOT EXISTS annotation_vector_ids (
    annotation_id TEXT PRIMARY KEY REFERENCES annotations(id),
    vector_id     INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS statement_annotations (
    statement_id  TEXT NOT NULL REFERENCES statements(id),
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    created_at    TEXT,
    created_by    TEXT,
    PRIMARY KEY (statement_id, annotation_id)
);
CREATE TABLE IF NOT EXISTS entity_annotations (
    entity_id     TEXT NOT NULL REFERENCES entities(id),
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    created_at    TEXT,
    created_by    TEXT,
    PRIMARY KEY (entity_id, annotation_id)
);
CREATE TABLE IF NOT EXISTS annotation_mentions (
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    name_id       TEXT NOT NULL REFERENCES names(id),
    PRIMARY KEY (annotation_id, name_id)
);

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
    from . import migrations

    conn.executescript(SCHEMA)
    migrations.apply_migrations(conn)
    if has_history(conn):
        conn.executescript(HISTORY_SCHEMA)
    seed_glossaries(conn)
    conn.commit()


# --- glossary seed data ----------------------------------------------------
# Source-of-truth dicts used to populate the glossary tables on first
# run. After seeding, the DB is authoritative — UI edits write back to
# the tables, not to these dicts. `INSERT OR IGNORE` makes re-seeding a
# no-op for any row that already exists; deleted entries do not get
# resurrected.

_STATEMENT_KIND_SEED: dict[str, tuple[str, str]] = {
    "event": (
        "Something happening — an atomic occurrence in the product "
        "(creation, submission, rejection, dispatch).",
        "Discrete things that fire, succeed, or are rejected. Use "
        "action-as-subject phrasing ('an invite is submitted'), with "
        "the actor in `mentions` unless the actor's identity is itself "
        "the claim (in which case use `capability`).",
    ),
    "state": (
        "A genuinely persisting, observable condition of a named "
        "entity — enum values, configuration flags, or conditions at a "
        "decision point.",
        "Enum/status values ('Sent' on Participant Status), config "
        "flags ('Auto result sharing enabled' on Company), or "
        "observable missing-input conditions ('No name on the invite' "
        "on Invite). Often referenced as `when` leaves on conditional "
        "edges. Do NOT use for derived/computed conditions or "
        "internal-mechanism steps.",
    ),
    "capability": (
        "A modal claim about what is possible — 'X can do Y'. Warranted "
        "only when the actor's identity or permission boundary is itself "
        "the claim, or when it anchors a `governed-by` rule tree.",
        "Authoring an event already implies the action is possible. "
        "Reach for `capability` when the point of the statement is who "
        "is allowed, what is gated, or which rule decomposition this "
        "modal anchors. Otherwise prefer `event`.",
    ),
    "rule": (
        "A deterministic, non-contingent claim — formula, default, "
        "enumeration, or bound that holds the same way across all "
        "instances and moments.",
        "Definitional or computational claims ('match level is one "
        "of: Low, Medium, High, Extra High'; 'match score equals "
        "construct points plus intelligence contribution minus red "
        "flag penalties'). Apply the contingency test: if the same "
        "claim could be otherwise for a specific entity or at a "
        "specific time, it is a `state`, not a `rule`.",
    ),
    "property": (
        "A slot on an entity that holds a value — short noun-phrase "
        "label, not a sentence. 'Email', 'Vacancy ID', 'Match score'.",
        "When the meaningful question is *what value* rather than "
        "*does this hold*. User-supplied configuration values, "
        "user-supplied event inputs, or derived/computed values. "
        "Anchored to its entity via `mentions`. Reach for this "
        "instead of packing inputs into event text.",
    ),
    "procedure": (
        "The named root of a how-to guide. 'How to configure Recruitee "
        "automation for a vacancy.' Composes `action`s, `property` "
        "inputs, and optional `check`s into a runnable script.",
        "Authoring prescriptive content: a guide the user (or an "
        "agent) executes to accomplish something. Anchors to a "
        "`capability` via `teaches`. The body is composed via "
        "`contains` / `next` to actions, and `requires` / `accepts` "
        "to property inputs.",
    ),
    "action": (
        "A step the user performs that modifies the system. 'Click "
        "the Save button.' Anchors to a descriptive `event` via "
        "`performs`.",
        "Single UI interactions inside a procedure or diagnostic "
        "flow: clicks, navigations, entries, sends. Each action is "
        "its own statement; the procedure `contains` them or chains "
        "them via `next`.",
    ),
    "check": (
        "A verification step for a diagnostic agent — observing the "
        "system without changing it. 'Verify the user's authentication "
        "provider matches the login method.'",
        "Diagnostic flows where a step inspects rather than mutates. "
        "Anchors to a `state` via `verifies`. Branches with "
        "`on-success` / `on-failure` or links to a `cause` via "
        "`confirms` / `refutes`.",
    ),
    "cause": (
        "A named failure mode worth investigating. 'User is attempting "
        "password login on a social-only account.'",
        "Roots of a diagnostic tree. Optionally anchors to a `state` "
        "via `violates` when the failure mode is 'a required state "
        "isn't met'. Free-standing when the failure is environmental, "
        "historical, referential, or compound.",
    ),
}

_STATEMENT_LINK_TYPE_SEED: dict[str, str] = {
    "contains": (
        "Sub-step inside the same process. Target only makes sense as "
        "part of the parent (e.g. 'The write pipeline executes' contains "
        "'The extraction agent runs')."
    ),
    "triggers": (
        "A *separate* downstream process fires as a consequence. Target "
        "stands on its own clock (e.g. 'An invite is created' triggers "
        "'A notification email is sent')."
    ),
    "establishes": (
        "Source produces a resulting state. Multiple statements can each "
        "`establishes` the same state — the state becomes the convergence "
        "point. No intermediate events: if event A causes state S, link "
        "A → establishes → S directly; do not create an intermediate "
        "event whose only purpose is to establish S."
    ),
    "enables": (
        "Source unlocks target's capability without directly invoking it "
        "(e.g. 'Embeddings are generated' enables 'Vector search returns "
        "ranked results'). Do NOT use for condition states — a state "
        "referenced in a `when` expression on an edge must not also have "
        "an `enables` link to the same target."
    ),
    "requires": (
        "Two uses: (1) target must hold for source to fire, usually "
        "paired with a `when` clause when the prerequisite is itself a "
        "statement; (2) source consumes the target `property` as a "
        "mandatory input in this context."
    ),
    "accepts": (
        "Source consumes the target `property` as an *optional* input "
        "in this context. The same property record is referenced from a "
        "`requires` edge elsewhere — optionality is per-edge, not "
        "per-property."
    ),
    "varies-by": (
        "Source's behavior depends on target as a parameter — shapes "
        "*how* source plays out, not *whether* it fires."
    ),
    "configures": (
        "Source parameterises target before target fires. Use sparingly; "
        "`contains` is often cleaner."
    ),
    "replaces": (
        "Source supersedes target. Almost always with a `when` clause — "
        "'replaces under condition C'."
    ),
    "restricts": (
        "Source limits target's operation. Use when the limit is itself "
        "a *statement* (a kill-switch, a feature flag)."
    ),
    "proceeds": (
        "Sequential hand-off in the same flow. A proceeds to B means B "
        "is the immediate next step after A in a continuous sequence — "
        "neither a contained sub-step (`contains`) nor an independently-"
        "fired downstream process (`triggers`). Use when A's completion "
        "naturally flows into B without a causal gap."
    ),
    "fallback-to": (
        "Ordered priority chain. A fallback-to B means B applies only "
        "when A does not. Forms a linear chain; first applicable option "
        "wins. Distinct from `cases` (enumeration over a named value "
        "set) and `composes` (grouping without ordering)."
    ),
    "governed-by": (
        "The rule that determines how a capability works. Typically: "
        "capability → governed-by → top-level rule."
    ),
    "composes": (
        "Sub-formula or sub-rule; together the composed statements "
        "specify the parent. Carry `when`-conditions on these edges for "
        "conditional applicability. Not the same as `cases`."
    ),
    "cases": (
        "Enumerated branches over a named, finite value set only "
        "(match levels, construct types, etc.). Each edge points to one "
        "branch. Do NOT use for continuous predicates — use a "
        "`when`-condition on a `composes` edge instead."
    ),
    "valued-by": (
        "The source statement's value is derived by the target rule. "
        "Typically: state → valued-by → rule. Do NOT use when the value "
        "is configured or input directly."
    ),
    "supersedes": "Versioning: source replaces target.",
    "teaches": (
        "Procedure → capability. Anchors a how-to guide to the "
        "capability it teaches the user to exercise. Every `procedure` "
        "should `teaches` exactly one capability."
    ),
    "performs": (
        "Action → event. The user step models this product event — the "
        "descriptive thing that actually happens when the user "
        "performs the step. Anchors the prescriptive action to the "
        "descriptive layer."
    ),
    "verifies": (
        "Check → state. The diagnostic check inspects whether this "
        "state currently holds, without changing the system. Anchors "
        "the check to the descriptive condition being observed."
    ),
    "violates": (
        "Cause → state. The failure mode corresponds to a required "
        "state not holding. Optional anchor: a cause may also be "
        "free-standing (environmental, historical, referential, or "
        "compound) and need no `violates` link."
    ),
    "obtained-by": (
        "Property → action or procedure. How the user finds or "
        "produces this value. Empty for values the user types directly "
        "or for derived/computed values."
    ),
    "next": (
        "Linear sequence between prescriptive steps. A `next` B means "
        "B follows A. Use for action→action and check→check chains. "
        "Distinct from descriptive `proceeds` (which connects events)."
    ),
    "on-success": (
        "Branch after a check or action on its success path. Source's "
        "success outcome leads to target. Pair with `on-failure` for "
        "the complementary branch."
    ),
    "on-failure": (
        "Branch after a check or action on its failure path. Source's "
        "failure outcome leads to target. Pair with `on-success` for "
        "the complementary branch."
    ),
    "confirms": (
        "Check → cause. If this check passes, this cause is the issue. "
        "Used in diagnostic trees to link verification steps to the "
        "failure modes they identify."
    ),
    "refutes": (
        "Check → cause. If this check passes, this cause is *not* the "
        "issue. Used in diagnostic trees to rule causes out."
    ),
    "resolves": (
        "Action → cause. This action fixes the situation when the "
        "cause applies. Used to attach remediation steps to diagnosed "
        "failure modes."
    ),
}

_ENTITY_LINK_TYPE_SEED: dict[str, str] = {
    "contains": (
        "Parent → member. Structural composition between long-lived "
        "entities (e.g. parent corp → subsidiary, category → member). "
        "Same top-down direction as statement links: parent is the source."
    ),
    "replaces": (
        "Source entity supersedes target entity (e.g. one provider replacing another)."
    ),
    "sub-type": (
        "Source is a specialization of target. Reads 'source is a "
        "sub-type of target' (e.g. Ubeeo is a sub-type of ATS, "
        "hard_skill_german_language is a sub-type of Hard Skill). "
        "Parent / general category at the target end."
    ),
    "has": (
        "Source has the target as a component, attribute, or related "
        "object. Generic ownership/composition relation between long-"
        "lived entities when neither `contains` (strict structural "
        "membership) nor `sub-type` (specialization) fits."
    ),
    "uses": (
        "Source depends on or makes use of target. Behavioural "
        "dependency between long-lived entities — distinct from "
        "structural composition (`contains`) and specialization "
        "(`sub-type`)."
    ),
}


def seed_glossaries(conn: sqlite3.Connection) -> None:
    """Populate glossary tables from seed data. Idempotent — uses
    `INSERT OR IGNORE`, so existing rows are never overwritten and a
    re-seed cannot resurrect rows the user has deleted via the UI."""
    now = _now()
    for kind, (description, when_to_use) in _STATEMENT_KIND_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO statement_kind_glossary "
            "(kind, description, when_to_use, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, description, when_to_use, now, _actor),
        )
    for link_type, description in _STATEMENT_LINK_TYPE_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO statement_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, _actor),
        )
    for link_type, description in _ENTITY_LINK_TYPE_SEED.items():
        conn.execute(
            "INSERT OR IGNORE INTO entity_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, _actor),
        )


# --- glossary CRUD ---------------------------------------------------------


def list_statement_kind_glossary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, description, when_to_use FROM statement_kind_glossary "
        "ORDER BY kind"
    ).fetchall()


def get_statement_kind_glossary(
    conn: sqlite3.Connection, kind: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT kind, description, when_to_use FROM statement_kind_glossary "
        "WHERE kind = ?",
        (kind,),
    ).fetchone()


def upsert_statement_kind_glossary(
    conn: sqlite3.Connection,
    kind: str,
    description: str,
    when_to_use: str | None,
) -> None:
    existing = get_statement_kind_glossary(conn, kind)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO statement_kind_glossary "
            "(kind, description, when_to_use, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, description, when_to_use, now, _actor),
        )
    else:
        conn.execute(
            "UPDATE statement_kind_glossary "
            "SET description = ?, when_to_use = ?, updated_at = ?, updated_by = ? "
            "WHERE kind = ?",
            (description, when_to_use, now, _actor, kind),
        )
    conn.commit()


def delete_statement_kind_glossary(conn: sqlite3.Connection, kind: str) -> None:
    conn.execute("DELETE FROM statement_kind_glossary WHERE kind = ?", (kind,))
    conn.commit()


def list_statement_link_type_glossary(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT link_type, description FROM statement_link_type_glossary "
        "ORDER BY link_type"
    ).fetchall()


def get_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT link_type, description FROM statement_link_type_glossary "
        "WHERE link_type = ?",
        (link_type,),
    ).fetchone()


def upsert_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str, description: str
) -> None:
    existing = get_statement_link_type_glossary(conn, link_type)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO statement_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, _actor),
        )
    else:
        conn.execute(
            "UPDATE statement_link_type_glossary "
            "SET description = ?, updated_at = ?, updated_by = ? "
            "WHERE link_type = ?",
            (description, now, _actor, link_type),
        )
    conn.commit()


def delete_statement_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> None:
    conn.execute(
        "DELETE FROM statement_link_type_glossary WHERE link_type = ?",
        (link_type,),
    )
    conn.commit()


def list_entity_link_type_glossary(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT link_type, description FROM entity_link_type_glossary "
        "ORDER BY link_type"
    ).fetchall()


def get_entity_link_type_glossary(
    conn: sqlite3.Connection, link_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT link_type, description FROM entity_link_type_glossary "
        "WHERE link_type = ?",
        (link_type,),
    ).fetchone()


def upsert_entity_link_type_glossary(
    conn: sqlite3.Connection, link_type: str, description: str
) -> None:
    existing = get_entity_link_type_glossary(conn, link_type)
    now = _now()
    if existing is None:
        conn.execute(
            "INSERT INTO entity_link_type_glossary "
            "(link_type, description, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (link_type, description, now, _actor),
        )
    else:
        conn.execute(
            "UPDATE entity_link_type_glossary "
            "SET description = ?, updated_at = ?, updated_by = ? "
            "WHERE link_type = ?",
            (description, now, _actor, link_type),
        )
    conn.commit()


def delete_entity_link_type_glossary(conn: sqlite3.Connection, link_type: str) -> None:
    conn.execute(
        "DELETE FROM entity_link_type_glossary WHERE link_type = ?",
        (link_type,),
    )
    conn.commit()


def count_statements_by_kind(conn: sqlite3.Connection, kind: str) -> int:
    """Used by list_statement_kinds to compute `in_use`."""
    row = conn.execute(
        "SELECT COUNT(*) FROM statements WHERE kind = ?", (kind,)
    ).fetchone()
    return int(row[0]) if row else 0


# --- entities ---------------------------------------------------------------


def create_entity(conn: sqlite3.Connection, description: str | None) -> str:
    entity_id = f"ent_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO entities (id, description, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (entity_id, description, _now(), _actor),
    )
    _record(
        conn,
        "create",
        "entity",
        entity_id,
        after=_row_dict(get_entity_by_id(conn, entity_id)),
    )
    conn.commit()
    return entity_id


def get_entity_by_id(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, description, created_at, updated_at, created_by, updated_by "
        "FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()


def update_entity_description(
    conn: sqlite3.Connection, entity_id: str, description: str | None
) -> None:
    before = _row_dict(get_entity_by_id(conn, entity_id))
    conn.execute(
        "UPDATE entities SET description = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (description, _now(), _actor, entity_id),
    )
    _record(
        conn,
        "update",
        "entity",
        entity_id,
        before=before,
        after=_row_dict(get_entity_by_id(conn, entity_id)),
    )
    conn.commit()


def delete_entity(conn: sqlite3.Connection, entity_id: str) -> None:
    """Caller is responsible for ensuring no names point at this entity."""
    before = _row_dict(get_entity_by_id(conn, entity_id))
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
    if before is not None:
        _record(conn, "delete", "entity", entity_id, before=before)
    conn.commit()


# --- names ------------------------------------------------------------------


def create_name(
    conn: sqlite3.Connection,
    text: str,
    entity_id: str,
    generated_from_name_id: str | None = None,
) -> str:
    """Create a name row. `generated_from_name_id` marks it as an
    auto-generated plural derived from another name (see
    `mycelium.plurals`); NULL means human-authored."""
    name_id = f"nam_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO names (id, text, entity_id, generated_from_name_id, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name_id, text, entity_id, generated_from_name_id, _now(), _actor),
    )
    _record(
        conn,
        "create",
        "name",
        name_id,
        after=_row_dict(get_name_by_id(conn, name_id)),
    )
    conn.commit()
    return name_id


def get_generated_children(conn: sqlite3.Connection, name_id: str) -> list[sqlite3.Row]:
    """Names auto-generated from `name_id` (its regular plural). Used to
    keep generated plurals in lockstep with their source on delete/rename/
    move."""
    return conn.execute(
        "SELECT id, text, entity_id FROM names WHERE generated_from_name_id = ?",
        (name_id,),
    ).fetchall()


def get_name_by_text(conn: sqlite3.Connection, text: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, text, entity_id, generated_from_name_id, "
        "created_at, updated_at, created_by, updated_by "
        "FROM names WHERE text = ?",
        (text,),
    ).fetchone()


def get_name_by_id(conn: sqlite3.Connection, name_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, text, entity_id, generated_from_name_id, "
        "created_at, updated_at, created_by, updated_by "
        "FROM names WHERE id = ?",
        (name_id,),
    ).fetchone()


def get_names_by_entity(conn: sqlite3.Connection, entity_id: str) -> list[sqlite3.Row]:
    """All names attached to an entity, sorted by text alphabetically."""
    return conn.execute(
        "SELECT id, text FROM names WHERE entity_id = ? ORDER BY text",
        (entity_id,),
    ).fetchall()


def list_entities(
    conn: sqlite3.Connection,
    prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Entities with their alphabetically-first name. Optional case-
    insensitive prefix filter on that name."""
    if prefix:
        rows = conn.execute(
            """
            SELECT e.id AS id, e.description AS description,
                   MIN(n.text) AS primary_name
            FROM entities e
            LEFT JOIN names n ON n.entity_id = e.id
            GROUP BY e.id
            HAVING primary_name LIKE ? COLLATE NOCASE
            ORDER BY primary_name
            LIMIT ? OFFSET ?
            """,
            (prefix + "%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT e.id AS id, e.description AS description,
                   MIN(n.text) AS primary_name
            FROM entities e
            LEFT JOIN names n ON n.entity_id = e.id
            GROUP BY e.id
            ORDER BY primary_name
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return rows


def list_statements(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
    entity_id: str | None = None,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Statements in insertion order (rowid ascending).

    When `entity_id` is given, restricts to statements mentioning any
    name attached to that entity. DISTINCT collapses statements that
    mention multiple aliases of the same entity to a single row. When
    `kind` is given, restricts to statements of that kind.
    """
    where: list[str] = []
    args: list[Any] = []
    if entity_id is not None:
        # Filter goes through the join below. Mark with a sentinel.
        pass
    if kind is not None:
        where.append("b.kind = ?")
        args.append(kind)
    kind_clause = (" AND " + " AND ".join(where)) if where else ""

    if entity_id is None:
        # No join needed; plain table scan with optional kind filter.
        sql = "SELECT id, kind, text FROM statements"
        kargs: list[Any] = []
        if kind is not None:
            sql += " WHERE kind = ?"
            kargs.append(kind)
        sql += " ORDER BY rowid LIMIT ? OFFSET ?"
        kargs.extend([limit, offset])
        return conn.execute(sql, kargs).fetchall()
    return conn.execute(
        f"""
        SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid
        FROM statements b
        JOIN statement_mentions bm ON bm.statement_id = b.id
        JOIN names n             ON n.id           = bm.name_id
        WHERE n.entity_id = ?{kind_clause}
        ORDER BY rid
        LIMIT ? OFFSET ?
        """,
        (entity_id, *args, limit, offset),
    ).fetchall()


def count_entities(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]


def _grep_match(case_sensitive: bool) -> tuple[str, Callable[[str], str]]:
    """Returns (sql_predicate_template, param_transform) for a literal
    substring match. Uses SQLite's `instr` so glob/regex chars in the
    query are matched literally without escape gymnastics. Case
    folding is via `lower(...)` on both sides."""
    if case_sensitive:
        return ("instr({col}, ?) > 0", lambda q: q)
    return ("instr(lower({col}), ?) > 0", lambda q: q.lower())


def grep_statements(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Statements whose `text` contains `query` as a literal substring.
    Insertion order. Optional case sensitivity, entity, and kind filters."""
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    kind_extra = " AND kind = ?" if kind is not None and entity_id is None else ""
    kind_extra_join = (
        " AND b.kind = ?" if kind is not None and entity_id is not None else ""
    )
    if entity_id is None:
        args: list[Any] = [needle]
        if kind is not None:
            args.append(kind)
        args.extend([limit, offset])
        return conn.execute(
            f"SELECT id, kind, text, rowid AS rid FROM statements "
            f"WHERE {predicate.format(col='text')}{kind_extra} "
            f"ORDER BY rowid LIMIT ? OFFSET ?",
            args,
        ).fetchall()
    args = [entity_id, needle]
    if kind is not None:
        args.append(kind)
    args.extend([limit, offset])
    return conn.execute(
        f"SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n              ON n.id           = bm.name_id "
        f"WHERE n.entity_id = ? AND {predicate.format(col='b.text')}{kind_extra_join} "
        f"ORDER BY rid LIMIT ? OFFSET ?",
        args,
    ).fetchall()


def grep_statements_via_mentions(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Statements that mention an entity whose *name* (any alias)
    contains `query` as a literal substring. The statement's own text
    is irrelevant — this is the alias-aware companion to
    `grep_statements`.

    The query is matched against every name of every mentioned entity,
    so a statement mentioning "Selection Flow" surfaces when the query
    is "tree" if that entity carries "tree" as an alias.

    A statement matching via multiple aliases / entities shows up once
    (DISTINCT on statement id). Ordered by insertion (rowid)."""
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    extra = " AND b.kind = ?" if kind else ""
    args: list[Any] = [needle]
    if kind:
        args.append(kind)
    # Two joins on names: n1 binds the mention to an entity (via the
    # name actually used in the mention), n2 walks every alias of that
    # entity. We match the substring against n2 so any alias counts.
    return conn.execute(
        f"SELECT DISTINCT b.id, b.kind, b.text, b.rowid AS rid "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n1 ON n1.id = bm.name_id "
        f"JOIN names n2 ON n2.entity_id = n1.entity_id "
        f"WHERE {predicate.format(col='n2.text')}{extra} "
        f"ORDER BY rid",
        args,
    ).fetchall()


def count_grep_statements(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    predicate, transform = _grep_match(case_sensitive)
    needle = transform(query)
    if entity_id is None:
        if kind is None:
            return conn.execute(
                f"SELECT COUNT(*) AS n FROM statements WHERE {predicate.format(col='text')}",
                (needle,),
            ).fetchone()["n"]
        return conn.execute(
            f"SELECT COUNT(*) AS n FROM statements "
            f"WHERE {predicate.format(col='text')} AND kind = ?",
            (needle, kind),
        ).fetchone()["n"]
    extra = " AND b.kind = ?" if kind is not None else ""
    args: list[Any] = [entity_id, needle]
    if kind is not None:
        args.append(kind)
    return conn.execute(
        f"SELECT COUNT(DISTINCT b.id) AS n "
        f"FROM statements b "
        f"JOIN statement_mentions bm ON bm.statement_id = b.id "
        f"JOIN names n              ON n.id           = bm.name_id "
        f"WHERE n.entity_id = ? AND {predicate.format(col='b.text')}{extra}",
        args,
    ).fetchone()["n"]


def grep_annotations(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    statement_id: str | None = None,
    entity_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Annotations whose `text` contains `query` as a literal substring."""
    predicate, transform = _grep_match(case_sensitive)
    where = [predicate.format(col="text")]
    args: list[Any] = [transform(query)]
    if statement_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM statement_annotations WHERE statement_id = ?)"
        )
        args.append(statement_id)
    if entity_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM entity_annotations WHERE entity_id = ?)"
        )
        args.append(entity_id)
    if kind is not None:
        where.append("kind = ?")
        args.append(kind)
    sql = (
        "SELECT id, kind, text FROM annotations "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY rowid LIMIT ? OFFSET ?"
    )
    args.extend([limit, offset])
    return conn.execute(sql, args).fetchall()


def count_grep_annotations(
    conn: sqlite3.Connection,
    query: str,
    case_sensitive: bool = False,
    statement_id: str | None = None,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    predicate, transform = _grep_match(case_sensitive)
    where = [predicate.format(col="text")]
    args: list[Any] = [transform(query)]
    if statement_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM statement_annotations WHERE statement_id = ?)"
        )
        args.append(statement_id)
    if entity_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM entity_annotations WHERE entity_id = ?)"
        )
        args.append(entity_id)
    if kind is not None:
        where.append("kind = ?")
        args.append(kind)
    sql = "SELECT COUNT(*) AS n FROM annotations WHERE " + " AND ".join(where)
    return conn.execute(sql, args).fetchone()["n"]


def count_statements(
    conn: sqlite3.Connection,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    if entity_id is None:
        if kind is None:
            return conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()["n"]
        return conn.execute(
            "SELECT COUNT(*) AS n FROM statements WHERE kind = ?", (kind,)
        ).fetchone()["n"]
    extra = " AND b.kind = ?" if kind is not None else ""
    args: list[Any] = [entity_id]
    if kind is not None:
        args.append(kind)
    return conn.execute(
        f"""
        SELECT COUNT(DISTINCT b.id) AS n
        FROM statements b
        JOIN statement_mentions bm ON bm.statement_id = b.id
        JOIN names n             ON n.id           = bm.name_id
        WHERE n.entity_id = ?{extra}
        """,
        args,
    ).fetchone()["n"]


def reassign_names(
    conn: sqlite3.Connection, from_entity_id: str, to_entity_id: str
) -> int:
    """Move every name from one entity to another. Returns rows affected."""
    affected = conn.execute(
        "SELECT id FROM names WHERE entity_id = ?", (from_entity_id,)
    ).fetchall()
    befores = {r["id"]: _row_dict(get_name_by_id(conn, r["id"])) for r in affected}
    cur = conn.execute(
        "UPDATE names SET entity_id = ?, updated_at = ?, updated_by = ? "
        "WHERE entity_id = ?",
        (to_entity_id, _now(), _actor, from_entity_id),
    )
    for nid, before in befores.items():
        _record(
            conn,
            "update",
            "name",
            nid,
            before=before,
            after=_row_dict(get_name_by_id(conn, nid)),
            context={"reason": "reassign_names", "from_entity_id": from_entity_id},
        )
    conn.commit()
    return cur.rowcount


def set_name_entity(conn: sqlite3.Connection, name_id: str, entity_id: str) -> None:
    before = _row_dict(get_name_by_id(conn, name_id))
    conn.execute(
        "UPDATE names SET entity_id = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (entity_id, _now(), _actor, name_id),
    )
    _record(
        conn,
        "update",
        "name",
        name_id,
        before=before,
        after=_row_dict(get_name_by_id(conn, name_id)),
        context={"reason": "set_name_entity"},
    )
    conn.commit()


def rename_name(conn: sqlite3.Connection, name_id: str, new_text: str) -> None:
    """Change a name's `text` in place without changing its id or its
    entity binding. Statements and annotations that mentioned this name
    keep pointing at the same name_id and start rendering under the new
    text.

    Raises ValueError if the name_id is unknown, or if the new text is
    already used by a different name (caller should use `merge_entities`
    or `move_name` to resolve such a clash before retrying)."""
    row = conn.execute(
        "SELECT entity_id, text FROM names WHERE id = ?", (name_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"name {name_id!r} does not exist")
    if row["text"] == new_text:
        return
    clash = conn.execute(
        "SELECT id, entity_id FROM names WHERE text = ?", (new_text,)
    ).fetchone()
    if clash is not None and clash["id"] != name_id:
        raise ValueError(
            f"name text {new_text!r} is already used by name {clash['id']!r} "
            f"on entity {clash['entity_id']!r}; "
            "use merge_entities or move_name to resolve"
        )
    before = _row_dict(get_name_by_id(conn, name_id))
    conn.execute(
        "UPDATE names SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (new_text, _now(), _actor, name_id),
    )
    _record(
        conn,
        "update",
        "name",
        name_id,
        before=before,
        after=_row_dict(get_name_by_id(conn, name_id)),
        context={"reason": "rename_name"},
    )
    conn.commit()


# --- statements --------------------------------------------------------------


def create_statement(conn: sqlite3.Connection, kind: str, text: str) -> str:
    statement_id = f"stm_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO statements (id, kind, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (statement_id, kind, text, _now(), _actor),
    )
    _record(
        conn,
        "create",
        "statement",
        statement_id,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    conn.commit()
    return statement_id


def get_statement(conn: sqlite3.Connection, statement_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, kind, text, created_at, updated_at, created_by, updated_by "
        "FROM statements WHERE id = ?",
        (statement_id,),
    ).fetchone()


def update_statement(
    conn: sqlite3.Connection, statement_id: str, kind: str, text: str
) -> None:
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET kind = ?, text = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (kind, text, _now(), _actor, statement_id),
    )
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    conn.commit()


def update_statement_text(
    conn: sqlite3.Connection, statement_id: str, text: str
) -> None:
    """Update only the text — used by `replace_text`, which never touches kind."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (text, _now(), _actor, statement_id),
    )
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    conn.commit()


def update_statement_kind(
    conn: sqlite3.Connection, statement_id: str, kind: str
) -> None:
    """Update only the kind — used by `patch_statement` when text is unchanged.

    Avoids touching `text` (and thus the embedding) when the caller is
    only re-classifying a statement."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "UPDATE statements SET kind = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (kind, _now(), _actor, statement_id),
    )
    _record(
        conn,
        "update",
        "statement",
        statement_id,
        before=before,
        after=_row_dict(get_statement(conn, statement_id)),
    )
    conn.commit()


# --- vector id mapping ------------------------------------------------------


def next_vector_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(vector_id), -1) + 1 AS next FROM statement_vector_ids"
    ).fetchone()
    return int(row["next"])


def set_vector_id(conn: sqlite3.Connection, statement_id: str, vector_id: int) -> None:
    conn.execute(
        "INSERT INTO statement_vector_ids (statement_id, vector_id) VALUES (?, ?)",
        (statement_id, vector_id),
    )
    conn.commit()


def get_vector_id(conn: sqlite3.Connection, statement_id: str) -> int | None:
    row = conn.execute(
        "SELECT vector_id FROM statement_vector_ids WHERE statement_id = ?",
        (statement_id,),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def get_statement_id_by_vector_id(
    conn: sqlite3.Connection, vector_id: int
) -> str | None:
    row = conn.execute(
        "SELECT statement_id FROM statement_vector_ids WHERE vector_id = ?",
        (vector_id,),
    ).fetchone()
    return row["statement_id"] if row else None


# --- name vector_id mapping ------------------------------------------------


def next_name_vector_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(vector_id), -1) + 1 AS next FROM name_vector_ids"
    ).fetchone()
    return int(row["next"])


def set_name_vector_id(conn: sqlite3.Connection, name_id: str, vector_id: int) -> None:
    conn.execute(
        "INSERT INTO name_vector_ids (name_id, vector_id) VALUES (?, ?)",
        (name_id, vector_id),
    )
    conn.commit()


def get_name_vector_id(conn: sqlite3.Connection, name_id: str) -> int | None:
    row = conn.execute(
        "SELECT vector_id FROM name_vector_ids WHERE name_id = ?",
        (name_id,),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def get_name_id_by_vector_id(conn: sqlite3.Connection, vector_id: int) -> str | None:
    row = conn.execute(
        "SELECT name_id FROM name_vector_ids WHERE vector_id = ?",
        (vector_id,),
    ).fetchone()
    return row["name_id"] if row else None


def delete_name_vector_mapping(conn: sqlite3.Connection, name_id: str) -> None:
    conn.execute("DELETE FROM name_vector_ids WHERE name_id = ?", (name_id,))
    conn.commit()


def list_all_names(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT id, text, entity_id FROM names").fetchall())


# --- mentions ---------------------------------------------------------------


def replace_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> None:
    conn.execute(
        "DELETE FROM statement_mentions WHERE statement_id = ?", (statement_id,)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        [(statement_id, nid) for nid in name_ids],
    )
    conn.commit()


def get_mentions(conn: sqlite3.Connection, statement_id: str) -> list[sqlite3.Row]:
    """Returns rows with name_id, name (text), and entity_id."""
    return conn.execute(
        "SELECT n.id AS name_id, n.text AS name, n.entity_id "
        "FROM statement_mentions bm "
        "JOIN names n ON n.id = bm.name_id "
        "WHERE bm.statement_id = ?",
        (statement_id,),
    ).fetchall()


def add_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> int:
    """Append mentions idempotently. Returns rows actually inserted —
    pre-existing (statement_id, name_id) pairs are silently skipped."""
    if not name_ids:
        return 0
    cur = conn.executemany(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        [(statement_id, nid) for nid in name_ids],
    )
    conn.commit()
    return cur.rowcount


def remove_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> int:
    """Remove the listed mention rows. Missing rows are silently skipped.
    Returns rows actually deleted."""
    if not name_ids:
        return 0
    placeholders = ",".join("?" * len(name_ids))
    cur = conn.execute(
        f"DELETE FROM statement_mentions "
        f"WHERE statement_id = ? AND name_id IN ({placeholders})",
        [statement_id, *name_ids],
    )
    conn.commit()
    return cur.rowcount


# --- derived mentions -------------------------------------------------------
#
# Mentions are not asserted; they are derived from statement text by the
# pure matcher in `mycelium.mentions`. The functions below are the only
# writers of `statement_mentions` and `pending_mentions` in normal
# operation — the sync statement-upsert path, the async recompute worker,
# and the one-shot backfill all funnel through `derive_mentions`.


def build_name_index(conn: sqlite3.Connection) -> dict[str, list[mentions.IndexedName]]:
    """Compile every name/alias into a matcher index. Built once per
    statement-write, per worker drain, or per backfill — never cached on
    the connection, so it always reflects the latest names."""
    rows = list_all_names(conn)
    return mentions.build_index((r["id"], r["entity_id"], r["text"]) for r in rows)


def _replace_mentions_nocommit(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> None:
    conn.execute(
        "DELETE FROM statement_mentions WHERE statement_id = ?", (statement_id,)
    )
    if name_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) "
            "VALUES (?, ?)",
            [(statement_id, nid) for nid in name_ids],
        )


def _sync_pending_nocommit(
    conn: sqlite3.Connection,
    statement_id: str,
    suspect_name_ids: list[str],
    keep_name_ids: list[str],
) -> None:
    """Re-queue a statement's suspect occurrences.

    Approved occurrences in `keep_name_ids` are left untouched — their
    decision and the materialized mention persist, because a human approval
    is asserted truth, not a re-derivable guess. Every other pending row for
    the statement is dropped, and each still-matching suspect that isn't
    already approved is re-inserted as a fresh OPEN row. So open and rejected
    occurrences carry no memory — a suspect that still matches is always
    re-surfaced for review (the 'keep it dumb' rule); only explicit approvals
    survive a recompute."""
    keep = set(keep_name_ids)
    for r in conn.execute(
        "SELECT name_id FROM pending_mentions WHERE statement_id = ?",
        (statement_id,),
    ).fetchall():
        if r["name_id"] not in keep:
            conn.execute(
                "DELETE FROM pending_mentions WHERE statement_id = ? AND name_id = ?",
                (statement_id, r["name_id"]),
            )
    now = _now()
    for nid in suspect_name_ids:
        if nid in keep:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO pending_mentions "
            "(statement_id, name_id, created_at) VALUES (?, ?, ?)",
            (statement_id, nid, now),
        )


def derive_mentions(
    conn: sqlite3.Connection,
    statement_id: str,
    text: str,
    index: dict[str, list[mentions.IndexedName]],
    *,
    commit: bool = True,
) -> mentions.MatchResult:
    """Run the matcher over `text` and materialize the result.

    Distinctive matches become `statement_mentions` rows. Suspect matches go
    to the `pending_mentions` review queue. A previously-APPROVED suspect
    whose name still matches the text is preserved — its decision stands and
    its materialized mention is re-asserted — so an unrelated recompute (a
    name change elsewhere, a typo fix) never silently destroys a human's
    review work. Open and rejected suspects carry no memory and are re-queued
    fresh (the 'keep it dumb' rule). Returns the raw `MatchResult`.

    `commit=False` lets the recompute worker batch many statements into one
    transaction and commit per chunk (cooperative chunking under the single
    SQLite writer)."""
    result = mentions.match_text(text, index)
    auto_ids = [m.name_id for m in result.mentions]
    suspect_ids = [s.name_id for s in result.suspects]
    approved = {
        r["name_id"]
        for r in conn.execute(
            "SELECT name_id FROM pending_mentions "
            "WHERE statement_id = ? AND approved_at IS NOT NULL",
            (statement_id,),
        ).fetchall()
    }
    keep_approved = [nid for nid in suspect_ids if nid in approved]
    _replace_mentions_nocommit(conn, statement_id, auto_ids + keep_approved)
    _sync_pending_nocommit(conn, statement_id, suspect_ids, keep_approved)
    if commit:
        conn.commit()
    return result


def clear_derived_for_statement(
    conn: sqlite3.Connection, statement_id: str, *, commit: bool = True
) -> int:
    """Remove a statement's derived rows so the statement can be deleted:
    its `statement_mentions`, its `pending_mentions`, and any queued
    recompute jobs (all FK statements(id) under RESTRICT). Returns the
    number of mention rows removed."""
    removed = conn.execute(
        "DELETE FROM statement_mentions WHERE statement_id = ?", (statement_id,)
    ).rowcount
    conn.execute("DELETE FROM pending_mentions WHERE statement_id = ?", (statement_id,))
    conn.execute(
        "DELETE FROM mention_recompute_queue WHERE statement_id = ?", (statement_id,)
    )
    if commit:
        conn.commit()
    return removed


def statements_mentioning_name(conn: sqlite3.Connection, name_id: str) -> list[str]:
    """All statement ids that currently mention `name_id` (via the reverse
    index). Used to find recompute targets when a name's binding changes."""
    return [
        r["statement_id"]
        for r in conn.execute(
            "SELECT statement_id FROM statement_mentions WHERE name_id = ?",
            (name_id,),
        ).fetchall()
    ]


def all_statement_ids(conn: sqlite3.Connection) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM statements").fetchall()]


def all_statements_with_text(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """(id, text) for every statement. Used by the recompute worker's scan
    pass and by the backfill."""
    return conn.execute("SELECT id, text FROM statements").fetchall()


# --- mention recompute queue (drained by mention_worker) --------------------


def enqueue_recompute_statements(
    conn: sqlite3.Connection, statement_ids: Iterable[str], *, commit: bool = True
) -> None:
    """Mark statements dirty: their derivable mentions may have changed
    because a name they reference moved, was deleted, or its representative
    shifted. Idempotent in effect — duplicate rows just recompute twice."""
    rows = [(sid, _now()) for sid in dict.fromkeys(statement_ids)]
    if rows:
        conn.executemany(
            "INSERT INTO mention_recompute_queue (statement_id, enqueued_at) "
            "VALUES (?, ?)",
            rows,
        )
    if commit:
        conn.commit()


def enqueue_recompute_scan(
    conn: sqlite3.Connection, scan_text: str, *, commit: bool = True
) -> None:
    """Mark that a new/renamed name text became matchable; the worker scans
    statement text for this token-sequence and recomputes every statement
    that now contains it."""
    conn.execute(
        "INSERT INTO mention_recompute_queue (scan_text, enqueued_at) VALUES (?, ?)",
        (scan_text, _now()),
    )
    if commit:
        conn.commit()


def claim_recompute_batch(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Claim up to `limit` unclaimed queue rows (stamp claimed_at) and
    return them. Claiming and reading happen in one transaction so two
    workers (or a restart mid-drain) can't double-process — though there is
    only ever one worker."""
    rows = conn.execute(
        "SELECT id, statement_id, scan_text FROM mention_recompute_queue "
        "WHERE claimed_at IS NULL ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    if rows:
        now = _now()
        conn.executemany(
            "UPDATE mention_recompute_queue SET claimed_at = ? WHERE id = ?",
            [(now, r["id"]) for r in rows],
        )
        conn.commit()
    return rows


def delete_recompute_rows(
    conn: sqlite3.Connection, ids: Iterable[int], *, commit: bool = True
) -> None:
    ids = list(ids)
    if ids:
        conn.executemany(
            "DELETE FROM mention_recompute_queue WHERE id = ?",
            [(i,) for i in ids],
        )
    if commit:
        conn.commit()


def reset_claimed_recompute(conn: sqlite3.Connection) -> None:
    """Un-claim every claimed-but-undeleted row. Run once on worker startup
    so a drain interrupted by a crash/restart is retried rather than
    stranded."""
    conn.execute(
        "UPDATE mention_recompute_queue SET claimed_at = NULL WHERE claimed_at IS NOT NULL"
    )
    conn.commit()


def count_open_recompute(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM mention_recompute_queue WHERE claimed_at IS NULL"
        ).fetchone()[0]
    )


# --- pending mentions (suspect-match review queue) --------------------------
#
# Never exposed through MCP. The website reviews these; approving inserts
# the real statement_mentions row.


def list_pending_mentions(
    conn: sqlite3.Connection,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Hydrated suspect occurrences for review. `status` is open /
    approved / rejected / all. Each row carries the statement text and the
    suspect name so a reviewer can judge the occurrence in context."""
    where = {
        "open": "WHERE p.approved_at IS NULL AND p.rejected_at IS NULL",
        "approved": "WHERE p.approved_at IS NOT NULL",
        "rejected": "WHERE p.rejected_at IS NOT NULL",
        "all": "",
    }.get(status, "WHERE p.approved_at IS NULL AND p.rejected_at IS NULL")
    return conn.execute(
        f"""
        SELECT p.id AS id, p.statement_id, p.name_id, p.created_at,
               p.approved_at, p.rejected_at,
               n.text AS name, n.entity_id AS entity_id,
               s.text AS statement_text, s.kind AS statement_kind
        FROM pending_mentions p
        JOIN names n      ON n.id = p.name_id
        JOIN statements s ON s.id = p.statement_id
        {where}
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()


def get_pending_mention(
    conn: sqlite3.Connection, pending_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, statement_id, name_id, approved_at, rejected_at "
        "FROM pending_mentions WHERE id = ?",
        (pending_id,),
    ).fetchone()


def approve_pending_mention(conn: sqlite3.Connection, pending_id: int) -> bool:
    """Approve a suspect occurrence: stamp approved_at and materialize the
    real mention. No-op (returns False) if already resolved or unknown."""
    row = get_pending_mention(conn, pending_id)
    if row is None or row["approved_at"] is not None or row["rejected_at"] is not None:
        return False
    conn.execute(
        "UPDATE pending_mentions SET approved_at = ?, approved_by = ? WHERE id = ?",
        (_now(), _actor, pending_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        (row["statement_id"], row["name_id"]),
    )
    _record(
        conn,
        "link",
        "statement_mention",
        f"{row['statement_id']}|{row['name_id']}",
        context={"reason": "approve_pending_mention", "pending_id": pending_id},
    )
    conn.commit()
    return True


def reject_pending_mention(conn: sqlite3.Connection, pending_id: int) -> bool:
    """Reject a suspect occurrence: stamp rejected_at, write no mention.
    No-op (returns False) if already resolved or unknown."""
    row = get_pending_mention(conn, pending_id)
    if row is None or row["approved_at"] is not None or row["rejected_at"] is not None:
        return False
    conn.execute(
        "UPDATE pending_mentions SET rejected_at = ?, rejected_by = ? WHERE id = ?",
        (_now(), _actor, pending_id),
    )
    conn.commit()
    return True


def count_pending_mentions(conn: sqlite3.Connection, status: str = "open") -> int:
    where = {
        "open": "WHERE approved_at IS NULL AND rejected_at IS NULL",
        "approved": "WHERE approved_at IS NOT NULL",
        "rejected": "WHERE rejected_at IS NOT NULL",
        "all": "",
    }.get(status, "WHERE approved_at IS NULL AND rejected_at IS NULL")
    return int(
        conn.execute(f"SELECT COUNT(*) FROM pending_mentions {where}").fetchone()[0]
    )


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


# --- links: write path ------------------------------------------------------


def _hash_for(expr: dict[str, Any] | None) -> str:
    """Local thin wrapper to keep store.py's link callers from each
    importing when_expression. Returns the canonical hash, or HASH_NONE
    for an unconditional link."""
    from . import when_expression as we

    return we.hash_canonical(expr)


def _canonical_for(expr: dict[str, Any] | None) -> dict[str, Any] | None:
    if expr is None:
        return None
    from . import when_expression as we

    return we.canonicalize(expr)


def _insert_one_link(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    link_type: str,
    when: dict[str, Any] | None,
) -> int | None:
    """Insert one link row + its when_nodes tree. Returns the new
    link_id, or None if a row with the same (from, to, link_type,
    when_hash) already existed."""
    canonical = _canonical_for(when)
    when_hash = _hash_for(canonical)
    cur = conn.execute(
        "INSERT OR IGNORE INTO statement_links "
        "(from_statement_id, to_statement_id, link_type, when_hash, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (from_id, to_id, link_type, when_hash, _now(), _actor),
    )
    if not cur.rowcount:
        return None
    link_id = cur.lastrowid
    if canonical is not None:
        _insert_when_tree(conn, link_id, canonical)
    _record(
        conn,
        "link",
        "statement_link",
        str(link_id),
        after={
            "link_id": link_id,
            "from_id": from_id,
            "to_id": to_id,
            "link_type": link_type,
            "when": canonical,
        },
    )
    return link_id


def _record_statement_link_delete(
    conn: sqlite3.Connection, link_id: int, reason: str | None = None
) -> None:
    """Capture a link's current shape for an unlink event. Must be called
    BEFORE the row is deleted, since it reads the row and its when-tree."""
    row = conn.execute(
        "SELECT link_id, from_statement_id, to_statement_id, link_type, "
        "       when_hash, created_at, created_by "
        "FROM statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return
    tree = _load_when_tree(conn, link_id)
    _record(
        conn,
        "unlink",
        "statement_link",
        str(link_id),
        before={
            "link_id": row["link_id"],
            "from_id": row["from_statement_id"],
            "to_id": row["to_statement_id"],
            "link_type": row["link_type"],
            "when": tree,
            "created_at": row["created_at"],
            "created_by": row["created_by"],
        },
        context={"reason": reason} if reason else None,
    )


def replace_links(
    conn: sqlite3.Connection,
    statement_id: str,
    links: list[tuple[str, str, dict[str, Any] | None]],
) -> None:
    """Replace this statement's outgoing edges wholesale. Each link is
    `(to_statement_id, link_type, when_expression | None)`. when_nodes
    rows cascade away when statement_links rows are deleted."""
    existing = conn.execute(
        "SELECT link_id FROM statement_links WHERE from_statement_id = ?",
        (statement_id,),
    ).fetchall()
    for r in existing:
        _record_statement_link_delete(conn, r["link_id"], reason="replace_links")
    conn.execute(
        "DELETE FROM statement_links WHERE from_statement_id = ?", (statement_id,)
    )
    for to_id, link_type, when in links:
        _insert_one_link(conn, statement_id, to_id, link_type, when)
    conn.commit()


def insert_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, dict[str, Any] | None]],
) -> int:
    """Insert (from, to, link_type, when_expression?) edges. Returns rows
    actually inserted — pre-existing edges (matched on the four-tuple
    `(from, to, link_type, when_hash)`) are silently skipped."""
    if not edges:
        return 0
    inserted = 0
    for from_id, to_id, link_type, when in edges:
        if _insert_one_link(conn, from_id, to_id, link_type, when) is not None:
            inserted += 1
    conn.commit()
    return inserted


def delete_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, dict[str, Any] | None]],
) -> int:
    """Delete specific (from, to, link_type, when_expression?) edges by
    their canonical hash. Returns rows actually removed; missing edges
    are silently skipped. ON DELETE CASCADE drops the when_nodes rows."""
    if not edges:
        return 0
    removed = 0
    for from_id, to_id, link_type, when in edges:
        when_hash = _hash_for(when)
        matching = conn.execute(
            "SELECT link_id FROM statement_links "
            "WHERE from_statement_id = ? AND to_statement_id = ? "
            "AND link_type = ? AND when_hash = ?",
            (from_id, to_id, link_type, when_hash),
        ).fetchall()
        for r in matching:
            _record_statement_link_delete(conn, r["link_id"])
        cur = conn.execute(
            "DELETE FROM statement_links "
            "WHERE from_statement_id = ? AND to_statement_id = ? "
            "AND link_type = ? AND when_hash = ?",
            (from_id, to_id, link_type, when_hash),
        )
        removed += cur.rowcount
    conn.commit()
    return removed


# --- links: read path -------------------------------------------------------


def get_links(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Outgoing edges of `statement_id` as
    `(to_statement_id, link_type, when_expression | None)` tuples."""
    rows = conn.execute(
        "SELECT link_id, to_statement_id, link_type FROM statement_links "
        "WHERE from_statement_id = ? ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    return [
        (r["to_statement_id"], r["link_type"], _load_when_tree(conn, r["link_id"]))
        for r in rows
    ]


def get_incoming_links(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Statements that link TO `statement_id`. Returns
    `(from_statement_id, link_type, when_expression | None)`."""
    rows = conn.execute(
        "SELECT link_id, from_statement_id, link_type FROM statement_links "
        "WHERE to_statement_id = ? ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    return [
        (r["from_statement_id"], r["link_type"], _load_when_tree(conn, r["link_id"]))
        for r in rows
    ]


def links_referencing_statement(
    conn: sqlite3.Connection,
    statement_id: str,
    *,
    link_kind: str = "statement",
) -> list[int]:
    """Every link_id whose when-tree mentions `statement_id` as a leaf,
    scoped to one link table (default: statement_links). Indexed lookup
    against `when_nodes(link_kind, statement_id)`. Used by cascade
    detection and by rewrite-on-merge."""
    rows = conn.execute(
        "SELECT DISTINCT link_id FROM when_nodes "
        "WHERE statement_id = ? AND link_kind = ?",
        (statement_id, link_kind),
    ).fetchall()
    return [r["link_id"] for r in rows]


def get_when_references(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Every statement-link edge whose `when` tree references
    `statement_id` as a leaf, fully hydrated. Returns
    `[(from_statement_id, to_statement_id, link_type, when_tree)]`.

    Empty list when the statement is not used as a condition anywhere.
    Entity-statement edges that condition on this statement surface via
    `get_entity_statement_when_references` instead.
    """
    rows = conn.execute(
        "SELECT DISTINCT sl.link_id, sl.from_statement_id, "
        "       sl.to_statement_id, sl.link_type "
        "FROM when_nodes wn "
        "JOIN statement_links sl ON sl.link_id = wn.link_id "
        "WHERE wn.statement_id = ? AND wn.link_kind = 'statement'",
        (statement_id,),
    ).fetchall()
    return [
        (
            r["from_statement_id"],
            r["to_statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"]),
        )
        for r in rows
    ]


# --- links: merge support ---------------------------------------------------


def merge_mentions_into(conn: sqlite3.Connection, from_id: str, into_id: str) -> int:
    """Move all mention rows from `from_id` onto `into_id`, deduped on
    name_id. Returns rows actually inserted (excluding dupes that were
    already on `into_id`). Removes `from_id`'s mention rows."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) "
        "SELECT ?, name_id FROM statement_mentions WHERE statement_id = ?",
        (into_id, from_id),
    )
    inserted = cur.rowcount
    conn.execute("DELETE FROM statement_mentions WHERE statement_id = ?", (from_id,))
    conn.commit()
    return inserted


def _move_link_endpoint(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    new_from: str | None = None,
    new_to: str | None = None,
    rewrite_when_leaves: tuple[str, str] | None = None,
) -> None:
    """Apply endpoint moves and/or when-leaf rewrites to a single link.
    On hash collision with an existing link (same from/to/link_type/hash
    after rewrite), drop the rewriting link — the existing one absorbs
    it. when_nodes auto-cascades away with the link.
    """
    from . import when_expression as we

    row = conn.execute(
        "SELECT from_statement_id, to_statement_id, link_type "
        "FROM statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return

    new_from_id = new_from if new_from is not None else row["from_statement_id"]
    new_to_id = new_to if new_to is not None else row["to_statement_id"]

    tree = _load_when_tree(conn, link_id)
    if rewrite_when_leaves is not None and tree is not None:
        old_id, replacement_id = rewrite_when_leaves
        tree = we.substitute_leaves(
            tree, lambda x: replacement_id if x == old_id else x
        )

    canonical = _canonical_for(tree)
    new_hash = _hash_for(canonical)

    # Self-loop after move: drop.
    if new_from_id == new_to_id:
        _record_statement_link_delete(conn, link_id, reason="merge_self_loop")
        conn.execute("DELETE FROM statement_links WHERE link_id = ?", (link_id,))
        return

    # Check for collision with an existing distinct link.
    existing = conn.execute(
        "SELECT link_id FROM statement_links "
        "WHERE from_statement_id = ? AND to_statement_id = ? "
        "AND link_type = ? AND when_hash = ? AND link_id != ?",
        (new_from_id, new_to_id, row["link_type"], new_hash, link_id),
    ).fetchone()
    if existing is not None:
        # The destination shape already exists; drop our row.
        _record_statement_link_delete(conn, link_id, reason="merge_absorbed")
        conn.execute("DELETE FROM statement_links WHERE link_id = ?", (link_id,))
        return

    # Apply the move + hash; rebuild the when-tree if the canonical
    # shape may have changed.
    before_tree = _load_when_tree(conn, link_id)
    before_payload = {
        "link_id": link_id,
        "from_id": row["from_statement_id"],
        "to_id": row["to_statement_id"],
        "link_type": row["link_type"],
        "when": before_tree,
    }
    conn.execute(
        "UPDATE statement_links SET from_statement_id = ?, to_statement_id = ?, "
        "when_hash = ? WHERE link_id = ?",
        (new_from_id, new_to_id, new_hash, link_id),
    )
    if rewrite_when_leaves is not None:
        conn.execute(
            "DELETE FROM when_nodes WHERE link_id = ? AND link_kind = 'statement'",
            (link_id,),
        )
        if canonical is not None:
            _insert_when_tree(conn, link_id, canonical)
    _record(
        conn,
        "update",
        "statement_link",
        str(link_id),
        before=before_payload,
        after={
            "link_id": link_id,
            "from_id": new_from_id,
            "to_id": new_to_id,
            "link_type": row["link_type"],
            "when": canonical,
        },
        context={"reason": "move_link_endpoint"},
    )


def merge_outgoing_links_into(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Move all outgoing links of `from_id` so they originate from
    `into_id`. Self-loops drop. Hash collisions absorb into the existing
    link. when_statement_id leaves equal to `from_id` rewrite to `into_id`
    on the way through. Returns the count of moved links (post-collision
    deduplication)."""
    rows = conn.execute(
        "SELECT link_id FROM statement_links WHERE from_statement_id = ?",
        (from_id,),
    ).fetchall()
    moved = 0
    for r in rows:
        before = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        _move_link_endpoint(
            conn,
            r["link_id"],
            new_from=into_id,
            rewrite_when_leaves=(from_id, into_id),
        )
        after = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        if before and after:
            moved += 1
    conn.commit()
    return moved


def merge_incoming_links_into(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Move all incoming links to `from_id` so they target `into_id`.
    Self-loops drop. Hash collisions absorb into the existing link.
    when_statement_id leaves equal to `from_id` rewrite to `into_id`
    on the way through."""
    rows = conn.execute(
        "SELECT link_id FROM statement_links WHERE to_statement_id = ?",
        (from_id,),
    ).fetchall()
    moved = 0
    for r in rows:
        before = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        _move_link_endpoint(
            conn,
            r["link_id"],
            new_to=into_id,
            rewrite_when_leaves=(from_id, into_id),
        )
        after = conn.execute(
            "SELECT 1 FROM statement_links WHERE link_id = ?", (r["link_id"],)
        ).fetchone()
        if before and after:
            moved += 1
    conn.commit()
    return moved


def rewrite_when_references(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Rewrite every link's when-tree, replacing leaves referencing
    `from_id` with `into_id`. Each rewritten link is re-canonicalized,
    re-hashed, and stored back; on hash collision with an existing link,
    the rewriting row is dropped (the destination already exists).

    Returns the number of links whose when-tree actually contained a
    reference to from_id (= the number processed, before any drops)."""
    link_ids = links_referencing_statement(conn, from_id)
    for lid in link_ids:
        _move_link_endpoint(conn, lid, rewrite_when_leaves=(from_id, into_id))
    conn.commit()
    return len(link_ids)


def delete_statement(conn: sqlite3.Connection, statement_id: str) -> None:
    """Delete a statement record and its vector_id mapping. Caller must
    ensure no statement_mentions or statement_links still reference it —
    FK enforcement will reject otherwise."""
    before = _row_dict(get_statement(conn, statement_id))
    conn.execute(
        "DELETE FROM statement_vector_ids WHERE statement_id = ?", (statement_id,)
    )
    conn.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
    if before is not None:
        _record(conn, "delete", "statement", statement_id, before=before)
    conn.commit()


def list_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM statement_links ORDER BY link_type"
    ).fetchall()
    return [r["link_type"] for r in rows]


def count_statement_links_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-type counts for the statement_links table. Returns a dict
    `{link_type: count}`. Types with zero rows are absent from the dict
    — callers default to 0."""
    rows = conn.execute(
        "SELECT link_type, COUNT(*) AS n FROM statement_links GROUP BY link_type"
    ).fetchall()
    return {r["link_type"]: int(r["n"]) for r in rows}


def count_entity_links_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-type counts for the entity_links table. Same shape as
    `count_statement_links_by_type`."""
    rows = conn.execute(
        "SELECT link_type, COUNT(*) AS n FROM entity_links GROUP BY link_type"
    ).fetchall()
    return {r["link_type"]: int(r["n"]) for r in rows}


def count_statements_by_kind_all(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-kind counts for the statements table. Returns `{kind: count}`."""
    rows = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM statements GROUP BY kind"
    ).fetchall()
    return {r["kind"]: int(r["n"]) for r in rows}


# --- entity-to-entity links ------------------------------------------------


def insert_entity_links(
    conn: sqlite3.Connection, edges: list[tuple[str, str, str]]
) -> int:
    """Insert (from_entity, to_entity, link_type) edges. Returns rows
    actually inserted — pre-existing edges (matched on the triple via
    the PK) are silently skipped."""
    if not edges:
        return 0
    now, actor = _now(), _actor
    inserted = 0
    for f, t, lt in edges:
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (f, t, lt, now, actor),
        )
        if cur.rowcount:
            inserted += 1
            _record(
                conn,
                "link",
                "entity_link",
                f"{f}|{t}|{lt}",
                after={
                    "from_entity_id": f,
                    "to_entity_id": t,
                    "link_type": lt,
                    "created_at": now,
                    "created_by": actor,
                },
            )
    conn.commit()
    return inserted


def delete_entity_links(
    conn: sqlite3.Connection, edges: list[tuple[str, str, str]]
) -> int:
    """Delete specific (from_entity, to_entity, link_type) edges.
    Returns rows actually removed — missing edges silently skipped."""
    if not edges:
        return 0
    removed = 0
    for f, t, lt in edges:
        row = conn.execute(
            "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
            "FROM entity_links "
            "WHERE from_entity_id = ? AND to_entity_id = ? AND link_type = ?",
            (f, t, lt),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            "DELETE FROM entity_links "
            "WHERE from_entity_id = ? AND to_entity_id = ? AND link_type = ?",
            (f, t, lt),
        )
        removed += 1
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{f}|{t}|{lt}",
            before=_row_dict(row),
        )
    conn.commit()
    return removed


def get_entity_links_outgoing(
    conn: sqlite3.Connection, entity_id: str
) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT to_entity_id, link_type FROM entity_links WHERE from_entity_id = ?",
        (entity_id,),
    ).fetchall()
    return [(r["to_entity_id"], r["link_type"]) for r in rows]


def get_entity_links_incoming(
    conn: sqlite3.Connection, entity_id: str
) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT from_entity_id, link_type FROM entity_links WHERE to_entity_id = ?",
        (entity_id,),
    ).fetchall()
    return [(r["from_entity_id"], r["link_type"]) for r in rows]


def list_entity_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM entity_links ORDER BY link_type"
    ).fetchall()
    return [r["link_type"] for r in rows]


# --- entity↔statement links ------------------------------------------------
# Mixed-endpoint edges. Same `link_type` vocabulary and `when` semantics
# as statement_links — the caller-facing API is uniform across both kinds.
# Internally they live in their own table so endpoint typing stays clean
# (always exactly one entity + one statement; `direction` records which
# side is the source).


def _insert_one_entity_statement_link(
    conn: sqlite3.Connection,
    entity_id: str,
    statement_id: str,
    direction: str,
    link_type: str,
    when: dict[str, Any] | None,
) -> int | None:
    """Insert one entity↔statement link row + its when_nodes tree.
    Returns the new link_id, or None if a row with the same
    (entity, statement, direction, link_type, when_hash) already existed."""
    canonical = _canonical_for(when)
    when_hash = _hash_for(canonical)
    cur = conn.execute(
        "INSERT OR IGNORE INTO entity_statement_links "
        "(entity_id, statement_id, direction, link_type, when_hash, "
        " created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_id, statement_id, direction, link_type, when_hash, _now(), _actor),
    )
    if not cur.rowcount:
        return None
    link_id = cur.lastrowid
    if canonical is not None:
        _insert_when_tree(conn, link_id, canonical, link_kind="entity_statement")
    _record(
        conn,
        "link",
        "entity_statement_link",
        str(link_id),
        after={
            "link_id": link_id,
            "entity_id": entity_id,
            "statement_id": statement_id,
            "direction": direction,
            "link_type": link_type,
            "when": canonical,
        },
    )
    return link_id


def _record_entity_statement_link_delete(
    conn: sqlite3.Connection, link_id: int, reason: str | None = None
) -> None:
    """Capture an entity↔statement link's current shape for an unlink
    event. Must be called BEFORE the row is deleted."""
    row = conn.execute(
        "SELECT link_id, entity_id, statement_id, direction, link_type, "
        "       when_hash, created_at, created_by "
        "FROM entity_statement_links WHERE link_id = ?",
        (link_id,),
    ).fetchone()
    if row is None:
        return
    tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
    _record(
        conn,
        "unlink",
        "entity_statement_link",
        str(link_id),
        before={
            "link_id": row["link_id"],
            "entity_id": row["entity_id"],
            "statement_id": row["statement_id"],
            "direction": row["direction"],
            "link_type": row["link_type"],
            "when": tree,
            "created_at": row["created_at"],
            "created_by": row["created_by"],
        },
        context={"reason": reason} if reason else None,
    )


def insert_entity_statement_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, str, dict[str, Any] | None]],
) -> int:
    """Insert (entity_id, statement_id, direction, link_type,
    when_expression?) edges. Returns rows actually inserted — pre-existing
    edges (matched on the five-tuple via the UNIQUE constraint) are
    silently skipped. `direction` is 'es' (entity→statement) or 'se'
    (statement→entity)."""
    if not edges:
        return 0
    inserted = 0
    for entity_id, statement_id, direction, link_type, when in edges:
        if (
            _insert_one_entity_statement_link(
                conn, entity_id, statement_id, direction, link_type, when
            )
            is not None
        ):
            inserted += 1
    conn.commit()
    return inserted


def delete_entity_statement_links(
    conn: sqlite3.Connection,
    edges: list[tuple[str, str, str, str, dict[str, Any] | None]],
) -> int:
    """Delete specific entity↔statement edges by their canonical hash.
    Returns rows actually removed; missing edges are silently skipped.
    The cascade trigger on `entity_statement_links` cleans up when_nodes
    rows."""
    if not edges:
        return 0
    removed = 0
    for entity_id, statement_id, direction, link_type, when in edges:
        when_hash = _hash_for(when)
        matching = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (entity_id, statement_id, direction, link_type, when_hash),
        ).fetchall()
        for r in matching:
            _record_entity_statement_link_delete(conn, r["link_id"])
        cur = conn.execute(
            "DELETE FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (entity_id, statement_id, direction, link_type, when_hash),
        )
        removed += cur.rowcount
    conn.commit()
    return removed


def get_entity_statement_links_for_entity(
    conn: sqlite3.Connection, entity_id: str
) -> tuple[
    list[tuple[str, str, dict[str, Any] | None]],
    list[tuple[str, str, dict[str, Any] | None]],
]:
    """Return `(outgoing, incoming)` for `entity_id` in the
    entity↔statement table.

    `outgoing` are edges where this entity is the source (direction='es'):
    each tuple is `(to_statement_id, link_type, when | None)`.
    `incoming` are edges where this entity is the target (direction='se'):
    each tuple is `(from_statement_id, link_type, when | None)`."""
    outgoing_rows = conn.execute(
        "SELECT link_id, statement_id, link_type FROM entity_statement_links "
        "WHERE entity_id = ? AND direction = 'es' ORDER BY link_id",
        (entity_id,),
    ).fetchall()
    incoming_rows = conn.execute(
        "SELECT link_id, statement_id, link_type FROM entity_statement_links "
        "WHERE entity_id = ? AND direction = 'se' ORDER BY link_id",
        (entity_id,),
    ).fetchall()
    outgoing = [
        (
            r["statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in outgoing_rows
    ]
    incoming = [
        (
            r["statement_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in incoming_rows
    ]
    return outgoing, incoming


def get_entity_statement_links_for_statement(
    conn: sqlite3.Connection, statement_id: str
) -> tuple[
    list[tuple[str, str, dict[str, Any] | None]],
    list[tuple[str, str, dict[str, Any] | None]],
]:
    """Return `(outgoing, incoming)` for `statement_id` in the
    entity↔statement table.

    `outgoing` are edges where the statement is the source (direction='se'):
    each tuple is `(to_entity_id, link_type, when | None)`.
    `incoming` are edges where the statement is the target (direction='es'):
    each tuple is `(from_entity_id, link_type, when | None)`."""
    outgoing_rows = conn.execute(
        "SELECT link_id, entity_id, link_type FROM entity_statement_links "
        "WHERE statement_id = ? AND direction = 'se' ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    incoming_rows = conn.execute(
        "SELECT link_id, entity_id, link_type FROM entity_statement_links "
        "WHERE statement_id = ? AND direction = 'es' ORDER BY link_id",
        (statement_id,),
    ).fetchall()
    outgoing = [
        (
            r["entity_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in outgoing_rows
    ]
    incoming = [
        (
            r["entity_id"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in incoming_rows
    ]
    return outgoing, incoming


def get_entity_statement_when_references(
    conn: sqlite3.Connection, statement_id: str
) -> list[tuple[str, str, str, str, dict[str, Any] | None]]:
    """Every entity↔statement edge whose `when` tree references
    `statement_id` as a leaf, fully hydrated. Each tuple is
    `(entity_id, statement_id, direction, link_type, when_tree)`.

    Empty list when the statement is not used as a condition on any
    entity↔statement edge."""
    rows = conn.execute(
        "SELECT DISTINCT esl.link_id, esl.entity_id, esl.statement_id, "
        "       esl.direction, esl.link_type "
        "FROM when_nodes wn "
        "JOIN entity_statement_links esl ON esl.link_id = wn.link_id "
        "WHERE wn.statement_id = ? AND wn.link_kind = 'entity_statement'",
        (statement_id,),
    ).fetchall()
    return [
        (
            r["entity_id"],
            r["statement_id"],
            r["direction"],
            r["link_type"],
            _load_when_tree(conn, r["link_id"], link_kind="entity_statement"),
        )
        for r in rows
    ]


def rewrite_entity_statement_when_references(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """Rewrite every entity↔statement link's when-tree, replacing leaves
    referencing `from_id` (a statement) with `into_id`. Hash collisions
    drop the rewriting row. Mirrors `rewrite_when_references` for the
    statement_links table."""
    from . import when_expression as we

    link_ids = links_referencing_statement(conn, from_id, link_kind="entity_statement")
    for link_id in link_ids:
        row = conn.execute(
            "SELECT entity_id, statement_id, direction, link_type "
            "FROM entity_statement_links WHERE link_id = ?",
            (link_id,),
        ).fetchone()
        if row is None:
            continue
        tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
        if tree is None:
            continue
        tree = we.substitute_leaves(tree, lambda x: into_id if x == from_id else x)
        canonical = _canonical_for(tree)
        new_hash = _hash_for(canonical)

        # Collision with an existing row?
        existing = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ? AND link_id != ?",
            (
                row["entity_id"],
                row["statement_id"],
                row["direction"],
                row["link_type"],
                new_hash,
                link_id,
            ),
        ).fetchone()
        if existing is not None:
            _record_entity_statement_link_delete(conn, link_id, reason="merge_absorbed")
            conn.execute(
                "DELETE FROM entity_statement_links WHERE link_id = ?",
                (link_id,),
            )
            continue

        before_tree = _load_when_tree(conn, link_id, link_kind="entity_statement")
        before_payload = {
            "link_id": link_id,
            "entity_id": row["entity_id"],
            "statement_id": row["statement_id"],
            "direction": row["direction"],
            "link_type": row["link_type"],
            "when": before_tree,
        }
        conn.execute(
            "UPDATE entity_statement_links SET when_hash = ? WHERE link_id = ?",
            (new_hash, link_id),
        )
        conn.execute(
            "DELETE FROM when_nodes "
            "WHERE link_id = ? AND link_kind = 'entity_statement'",
            (link_id,),
        )
        if canonical is not None:
            _insert_when_tree(conn, link_id, canonical, link_kind="entity_statement")
        _record(
            conn,
            "update",
            "entity_statement_link",
            str(link_id),
            before=before_payload,
            after={
                "link_id": link_id,
                "entity_id": row["entity_id"],
                "statement_id": row["statement_id"],
                "direction": row["direction"],
                "link_type": row["link_type"],
                "when": canonical,
            },
            context={"reason": "rewrite_when_references"},
        )
    conn.commit()
    return len(link_ids)


def rewrite_entity_statement_endpoints(
    conn: sqlite3.Connection, from_entity_id: str, into_entity_id: str
) -> None:
    """Used by `merge_entities`. Rewrites every entity↔statement link
    whose `entity_id == from_entity_id` to point at `into_entity_id`.
    Hash/collision behavior mirrors `rewrite_entity_link_endpoints`:
    on UNIQUE conflict the rewriting row is dropped (the destination
    already exists). when_nodes rows cascade via the AFTER DELETE
    trigger."""
    rows = conn.execute(
        "SELECT link_id, statement_id, direction, link_type, when_hash "
        "FROM entity_statement_links WHERE entity_id = ?",
        (from_entity_id,),
    ).fetchall()
    for r in rows:
        existing = conn.execute(
            "SELECT link_id FROM entity_statement_links "
            "WHERE entity_id = ? AND statement_id = ? AND direction = ? "
            "AND link_type = ? AND when_hash = ?",
            (
                into_entity_id,
                r["statement_id"],
                r["direction"],
                r["link_type"],
                r["when_hash"],
            ),
        ).fetchone()
        if existing is not None:
            _record_entity_statement_link_delete(
                conn, r["link_id"], reason="merge_absorbed"
            )
            conn.execute(
                "DELETE FROM entity_statement_links WHERE link_id = ?",
                (r["link_id"],),
            )
            continue
        before = {
            "link_id": r["link_id"],
            "entity_id": from_entity_id,
            "statement_id": r["statement_id"],
            "direction": r["direction"],
            "link_type": r["link_type"],
            "when_hash": r["when_hash"],
        }
        conn.execute(
            "UPDATE entity_statement_links SET entity_id = ? WHERE link_id = ?",
            (into_entity_id, r["link_id"]),
        )
        _record(
            conn,
            "update",
            "entity_statement_link",
            str(r["link_id"]),
            before=before,
            after={**before, "entity_id": into_entity_id},
            context={"reason": "rewrite_entity_statement_endpoints"},
        )
    conn.commit()


def list_entity_statement_link_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT link_type FROM entity_statement_links ORDER BY link_type"
    ).fetchall()
    return [r["link_type"] for r in rows]


# --- annotations ------------------------------------------------------------


def create_annotation(conn: sqlite3.Connection, kind: str, text: str) -> str:
    annotation_id = f"ann_{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO annotations (id, kind, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (annotation_id, kind, text, _now(), _actor),
    )
    _record(
        conn,
        "create",
        "annotation",
        annotation_id,
        after=_row_dict(get_annotation(conn, annotation_id)),
    )
    conn.commit()
    return annotation_id


def get_annotation(conn: sqlite3.Connection, annotation_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, kind, text, created_at, updated_at, created_by, updated_by "
        "FROM annotations WHERE id = ?",
        (annotation_id,),
    ).fetchone()


def update_annotation(
    conn: sqlite3.Connection, annotation_id: str, kind: str, text: str
) -> None:
    before = _row_dict(get_annotation(conn, annotation_id))
    conn.execute(
        "UPDATE annotations SET kind = ?, text = ?, updated_at = ?, updated_by = ? "
        "WHERE id = ?",
        (kind, text, _now(), _actor, annotation_id),
    )
    _record(
        conn,
        "update",
        "annotation",
        annotation_id,
        before=before,
        after=_row_dict(get_annotation(conn, annotation_id)),
    )
    conn.commit()


def list_annotations(
    conn: sqlite3.Connection,
    statement_id: str | None = None,
    entity_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Annotations in insertion order. Filters: `statement_id` restricts
    to annotations attached to that statement; `entity_id` restricts to
    annotations attached to that entity; `kind` restricts to that kind.
    All combine with AND."""
    where = []
    args: list[Any] = []
    if statement_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM statement_annotations WHERE statement_id = ?)"
        )
        args.append(statement_id)
    if entity_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM entity_annotations WHERE entity_id = ?)"
        )
        args.append(entity_id)
    if kind is not None:
        where.append("kind = ?")
        args.append(kind)
    sql = "SELECT id, kind, text FROM annotations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return conn.execute(sql, args).fetchall()


def count_annotations(
    conn: sqlite3.Connection,
    statement_id: str | None = None,
    entity_id: str | None = None,
    kind: str | None = None,
) -> int:
    where = []
    args: list[Any] = []
    if statement_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM statement_annotations WHERE statement_id = ?)"
        )
        args.append(statement_id)
    if entity_id is not None:
        where.append(
            "id IN (SELECT annotation_id FROM entity_annotations WHERE entity_id = ?)"
        )
        args.append(entity_id)
    if kind is not None:
        where.append("kind = ?")
        args.append(kind)
    sql = "SELECT COUNT(*) AS n FROM annotations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return conn.execute(sql, args).fetchone()["n"]


def list_annotation_kinds(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT kind FROM annotations ORDER BY kind"
    ).fetchall()
    return [r["kind"] for r in rows]


def delete_annotation_record(conn: sqlite3.Connection, annotation_id: str) -> None:
    """Delete annotation + its vector_id mapping. Caller must clear the
    join + mention rows first; FK enforcement otherwise rejects."""
    before = _row_dict(get_annotation(conn, annotation_id))
    conn.execute(
        "DELETE FROM annotation_vector_ids WHERE annotation_id = ?",
        (annotation_id,),
    )
    conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    if before is not None:
        _record(conn, "delete", "annotation", annotation_id, before=before)
    conn.commit()


# --- annotation vector_id mapping ------------------------------------------


def next_annotation_vector_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(vector_id), -1) + 1 AS next FROM annotation_vector_ids"
    ).fetchone()
    return int(row["next"])


def set_annotation_vector_id(
    conn: sqlite3.Connection, annotation_id: str, vector_id: int
) -> None:
    conn.execute(
        "INSERT INTO annotation_vector_ids (annotation_id, vector_id) VALUES (?, ?)",
        (annotation_id, vector_id),
    )
    conn.commit()


def get_annotation_vector_id(
    conn: sqlite3.Connection, annotation_id: str
) -> int | None:
    row = conn.execute(
        "SELECT vector_id FROM annotation_vector_ids WHERE annotation_id = ?",
        (annotation_id,),
    ).fetchone()
    return int(row["vector_id"]) if row else None


def get_annotation_id_by_vector_id(
    conn: sqlite3.Connection, vector_id: int
) -> str | None:
    row = conn.execute(
        "SELECT annotation_id FROM annotation_vector_ids WHERE vector_id = ?",
        (vector_id,),
    ).fetchone()
    return row["annotation_id"] if row else None


# --- annotation ↔ statement attachment --------------------------------------


def _record_attach_pair(
    conn: sqlite3.Connection,
    table: str,  # 'statement_annotations' or 'entity_annotations'
    target_kind: str,  # 'statement_annotation' or 'entity_annotation'
    parent_col: str,  # 'statement_id' or 'entity_id'
    parent_id: str,
    annotation_id: str,
    op: str,  # 'attach' or 'detach'
    row_data: dict[str, Any] | None,
    reason: str | None = None,
) -> None:
    payload = {parent_col: parent_id, "annotation_id": annotation_id}
    if row_data is not None:
        payload.update(row_data)
    _record(
        conn,
        op,
        target_kind,
        f"{parent_id}|{annotation_id}",
        before=payload if op == "detach" else None,
        after=payload if op == "attach" else None,
        context={"reason": reason} if reason else None,
    )


def attach_annotations_to_statements(
    conn: sqlite3.Connection, edges: list[tuple[str, str]]
) -> int:
    """Insert (statement_id, annotation_id) pairs idempotently. Returns
    rows actually inserted; pre-existing pairs are silently skipped."""
    if not edges:
        return 0
    now, actor = _now(), _actor
    inserted = 0
    for s, a in edges:
        cur = conn.execute(
            "INSERT OR IGNORE INTO statement_annotations "
            "(statement_id, annotation_id, created_at, created_by) VALUES (?, ?, ?, ?)",
            (s, a, now, actor),
        )
        if cur.rowcount:
            inserted += 1
            _record_attach_pair(
                conn,
                "statement_annotations",
                "statement_annotation",
                "statement_id",
                s,
                a,
                "attach",
                {"created_at": now, "created_by": actor},
            )
    conn.commit()
    return inserted


def detach_annotations_from_statements(
    conn: sqlite3.Connection, edges: list[tuple[str, str]]
) -> int:
    """Delete (statement_id, annotation_id) pairs. Missing pairs silently
    skipped. Returns rows actually deleted."""
    if not edges:
        return 0
    removed = 0
    for s, a in edges:
        row = conn.execute(
            "SELECT created_at, created_by FROM statement_annotations "
            "WHERE statement_id = ? AND annotation_id = ?",
            (s, a),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            "DELETE FROM statement_annotations "
            "WHERE statement_id = ? AND annotation_id = ?",
            (s, a),
        )
        removed += 1
        _record_attach_pair(
            conn,
            "statement_annotations",
            "statement_annotation",
            "statement_id",
            s,
            a,
            "detach",
            _row_dict(row),
        )
    conn.commit()
    return removed


def replace_annotation_attachments(
    conn: sqlite3.Connection,
    annotation_id: str,
    statement_ids: list[str],
) -> None:
    """Reconcile the full set of statements this annotation attaches to.
    Used by upsert_annotation: delete attachments not in the new list,
    insert new ones, leave existing matches alone."""
    existing = conn.execute(
        "SELECT statement_id, created_at, created_by FROM statement_annotations "
        "WHERE annotation_id = ?",
        (annotation_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "statement_annotations",
            "statement_annotation",
            "statement_id",
            r["statement_id"],
            annotation_id,
            "detach",
            _row_dict(r),
            reason="replace_annotation_attachments",
        )
    conn.execute(
        "DELETE FROM statement_annotations WHERE annotation_id = ?",
        (annotation_id,),
    )
    now, actor = _now(), _actor
    for bid in statement_ids:
        cur = conn.execute(
            "INSERT OR IGNORE INTO statement_annotations "
            "(statement_id, annotation_id, created_at, created_by) VALUES (?, ?, ?, ?)",
            (bid, annotation_id, now, actor),
        )
        if cur.rowcount:
            _record_attach_pair(
                conn,
                "statement_annotations",
                "statement_annotation",
                "statement_id",
                bid,
                annotation_id,
                "attach",
                {"created_at": now, "created_by": actor},
                reason="replace_annotation_attachments",
            )
    conn.commit()


def get_annotations_for_statement(
    conn: sqlite3.Connection, statement_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.id, a.kind, a.text FROM annotations a "
        "JOIN statement_annotations ba ON ba.annotation_id = a.id "
        "WHERE ba.statement_id = ? "
        "ORDER BY a.kind, a.rowid",
        (statement_id,),
    ).fetchall()


def get_statements_for_annotation(
    conn: sqlite3.Connection, annotation_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT b.id, b.kind, b.text FROM statements b "
        "JOIN statement_annotations ba ON ba.statement_id = b.id "
        "WHERE ba.annotation_id = ? "
        "ORDER BY b.rowid",
        (annotation_id,),
    ).fetchall()


def clear_statement_annotations(conn: sqlite3.Connection, statement_id: str) -> int:
    """Drop every annotation attachment for this statement. Used by
    delete_statement. Annotations themselves survive — only the join is
    removed. Returns rows deleted."""
    existing = conn.execute(
        "SELECT annotation_id, created_at, created_by FROM statement_annotations "
        "WHERE statement_id = ?",
        (statement_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "statement_annotations",
            "statement_annotation",
            "statement_id",
            statement_id,
            r["annotation_id"],
            "detach",
            _row_dict(r),
            reason="clear_statement_annotations",
        )
    cur = conn.execute(
        "DELETE FROM statement_annotations WHERE statement_id = ?", (statement_id,)
    )
    conn.commit()
    return cur.rowcount


def clear_annotation_attachments(conn: sqlite3.Connection, annotation_id: str) -> None:
    """Drop every statement attachment for this annotation. Used by
    delete_annotation before dropping the annotation itself."""
    existing = conn.execute(
        "SELECT statement_id, created_at, created_by FROM statement_annotations "
        "WHERE annotation_id = ?",
        (annotation_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "statement_annotations",
            "statement_annotation",
            "statement_id",
            r["statement_id"],
            annotation_id,
            "detach",
            _row_dict(r),
            reason="clear_annotation_attachments",
        )
    conn.execute(
        "DELETE FROM statement_annotations WHERE annotation_id = ?",
        (annotation_id,),
    )
    conn.commit()


def merge_statement_annotation_attachments(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """During merge_statements, move every annotation attached to `from`
    to also attach to `into`, deduped on annotation_id. Drops the
    source's attachments. Returns rows actually inserted on the target
    (excluding dupes). Preserves the original attachment's
    created_at/created_by on the migrated row."""
    sources = conn.execute(
        "SELECT annotation_id, created_at, created_by FROM statement_annotations "
        "WHERE statement_id = ?",
        (from_id,),
    ).fetchall()
    inserted = 0
    for r in sources:
        _record_attach_pair(
            conn,
            "statement_annotations",
            "statement_annotation",
            "statement_id",
            from_id,
            r["annotation_id"],
            "detach",
            _row_dict(r),
            reason="merge_statements",
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO statement_annotations "
            "(statement_id, annotation_id, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (into_id, r["annotation_id"], r["created_at"], r["created_by"]),
        )
        if cur.rowcount:
            inserted += 1
            _record_attach_pair(
                conn,
                "statement_annotations",
                "statement_annotation",
                "statement_id",
                into_id,
                r["annotation_id"],
                "attach",
                {"created_at": r["created_at"], "created_by": r["created_by"]},
                reason="merge_statements",
            )
    conn.execute("DELETE FROM statement_annotations WHERE statement_id = ?", (from_id,))
    conn.commit()
    return inserted


# --- annotation ↔ entity attachment ----------------------------------------


def attach_annotations_to_entities(
    conn: sqlite3.Connection, edges: list[tuple[str, str]]
) -> int:
    if not edges:
        return 0
    now, actor = _now(), _actor
    inserted = 0
    for e, a in edges:
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_annotations "
            "(entity_id, annotation_id, created_at, created_by) VALUES (?, ?, ?, ?)",
            (e, a, now, actor),
        )
        if cur.rowcount:
            inserted += 1
            _record_attach_pair(
                conn,
                "entity_annotations",
                "entity_annotation",
                "entity_id",
                e,
                a,
                "attach",
                {"created_at": now, "created_by": actor},
            )
    conn.commit()
    return inserted


def detach_annotations_from_entities(
    conn: sqlite3.Connection, edges: list[tuple[str, str]]
) -> int:
    if not edges:
        return 0
    removed = 0
    for e, a in edges:
        row = conn.execute(
            "SELECT created_at, created_by FROM entity_annotations "
            "WHERE entity_id = ? AND annotation_id = ?",
            (e, a),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            "DELETE FROM entity_annotations WHERE entity_id = ? AND annotation_id = ?",
            (e, a),
        )
        removed += 1
        _record_attach_pair(
            conn,
            "entity_annotations",
            "entity_annotation",
            "entity_id",
            e,
            a,
            "detach",
            _row_dict(row),
        )
    conn.commit()
    return removed


def replace_annotation_entity_attachments(
    conn: sqlite3.Connection,
    annotation_id: str,
    entity_ids: list[str],
) -> None:
    existing = conn.execute(
        "SELECT entity_id, created_at, created_by FROM entity_annotations "
        "WHERE annotation_id = ?",
        (annotation_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "entity_annotations",
            "entity_annotation",
            "entity_id",
            r["entity_id"],
            annotation_id,
            "detach",
            _row_dict(r),
            reason="replace_annotation_entity_attachments",
        )
    conn.execute(
        "DELETE FROM entity_annotations WHERE annotation_id = ?",
        (annotation_id,),
    )
    now, actor = _now(), _actor
    for eid in entity_ids:
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_annotations "
            "(entity_id, annotation_id, created_at, created_by) VALUES (?, ?, ?, ?)",
            (eid, annotation_id, now, actor),
        )
        if cur.rowcount:
            _record_attach_pair(
                conn,
                "entity_annotations",
                "entity_annotation",
                "entity_id",
                eid,
                annotation_id,
                "attach",
                {"created_at": now, "created_by": actor},
                reason="replace_annotation_entity_attachments",
            )
    conn.commit()


def get_annotations_for_entity(
    conn: sqlite3.Connection, entity_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.id, a.kind, a.text FROM annotations a "
        "JOIN entity_annotations ea ON ea.annotation_id = a.id "
        "WHERE ea.entity_id = ? "
        "ORDER BY a.kind, a.rowid",
        (entity_id,),
    ).fetchall()


def get_entities_for_annotation(
    conn: sqlite3.Connection, annotation_id: str
) -> list[sqlite3.Row]:
    """Returns the entities directly attached to this annotation, with
    each entity's alphabetically-first name as `primary_name` for
    display."""
    return conn.execute(
        "SELECT e.id AS id, MIN(n.text) AS primary_name "
        "FROM entities e "
        "JOIN entity_annotations ea ON ea.entity_id = e.id "
        "LEFT JOIN names n          ON n.entity_id  = e.id "
        "WHERE ea.annotation_id = ? "
        "GROUP BY e.id "
        "ORDER BY primary_name",
        (annotation_id,),
    ).fetchall()


def clear_entity_annotations(conn: sqlite3.Connection, entity_id: str) -> int:
    """Drop every annotation attachment for this entity. Used by
    merge_entities. Annotations themselves survive — only the join is
    removed."""
    existing = conn.execute(
        "SELECT annotation_id, created_at, created_by FROM entity_annotations "
        "WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "entity_annotations",
            "entity_annotation",
            "entity_id",
            entity_id,
            r["annotation_id"],
            "detach",
            _row_dict(r),
            reason="clear_entity_annotations",
        )
    cur = conn.execute(
        "DELETE FROM entity_annotations WHERE entity_id = ?", (entity_id,)
    )
    conn.commit()
    return cur.rowcount


def clear_annotation_entity_attachments(
    conn: sqlite3.Connection, annotation_id: str
) -> None:
    """Used by delete_annotation before dropping the annotation itself."""
    existing = conn.execute(
        "SELECT entity_id, created_at, created_by FROM entity_annotations "
        "WHERE annotation_id = ?",
        (annotation_id,),
    ).fetchall()
    for r in existing:
        _record_attach_pair(
            conn,
            "entity_annotations",
            "entity_annotation",
            "entity_id",
            r["entity_id"],
            annotation_id,
            "detach",
            _row_dict(r),
            reason="clear_annotation_entity_attachments",
        )
    conn.execute(
        "DELETE FROM entity_annotations WHERE annotation_id = ?",
        (annotation_id,),
    )
    conn.commit()


def merge_entity_annotation_attachments(
    conn: sqlite3.Connection, from_id: str, into_id: str
) -> int:
    """During merge_entities, move every annotation attached to `from`
    to also attach to `into`, deduped on annotation_id. Drops the
    source's attachments. Returns rows actually inserted on the target.
    Preserves original attachment provenance on the migrated row."""
    sources = conn.execute(
        "SELECT annotation_id, created_at, created_by FROM entity_annotations "
        "WHERE entity_id = ?",
        (from_id,),
    ).fetchall()
    inserted = 0
    for r in sources:
        _record_attach_pair(
            conn,
            "entity_annotations",
            "entity_annotation",
            "entity_id",
            from_id,
            r["annotation_id"],
            "detach",
            _row_dict(r),
            reason="merge_entities",
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_annotations "
            "(entity_id, annotation_id, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (into_id, r["annotation_id"], r["created_at"], r["created_by"]),
        )
        if cur.rowcount:
            inserted += 1
            _record_attach_pair(
                conn,
                "entity_annotations",
                "entity_annotation",
                "entity_id",
                into_id,
                r["annotation_id"],
                "attach",
                {"created_at": r["created_at"], "created_by": r["created_by"]},
                reason="merge_entities",
            )
    conn.execute("DELETE FROM entity_annotations WHERE entity_id = ?", (from_id,))
    conn.commit()
    return inserted


# --- annotation mentions ---------------------------------------------------


def replace_annotation_mentions(
    conn: sqlite3.Connection, annotation_id: str, name_ids: list[str]
) -> None:
    conn.execute(
        "DELETE FROM annotation_mentions WHERE annotation_id = ?",
        (annotation_id,),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO annotation_mentions (annotation_id, name_id) "
        "VALUES (?, ?)",
        [(annotation_id, nid) for nid in name_ids],
    )
    conn.commit()


def get_annotation_mentions(
    conn: sqlite3.Connection, annotation_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT n.id AS name_id, n.text AS name, n.entity_id "
        "FROM annotation_mentions am "
        "JOIN names n ON n.id = am.name_id "
        "WHERE am.annotation_id = ?",
        (annotation_id,),
    ).fetchall()


def clear_annotation_mentions(conn: sqlite3.Connection, annotation_id: str) -> None:
    """Drop every mention this annotation had. Used by delete_annotation
    before dropping the annotation itself."""
    conn.execute(
        "DELETE FROM annotation_mentions WHERE annotation_id = ?",
        (annotation_id,),
    )
    conn.commit()


def get_annotations_mentioning_entity(
    conn: sqlite3.Connection, entity_id: str
) -> list[sqlite3.Row]:
    """Annotations mentioning any name attached to this entity. DISTINCT
    collapses annotations that mention multiple aliases of the same
    entity to a single row."""
    return conn.execute(
        "SELECT DISTINCT a.id, a.kind, a.text FROM annotations a "
        "JOIN annotation_mentions am ON am.annotation_id = a.id "
        "JOIN names n              ON n.id              = am.name_id "
        "WHERE n.entity_id = ? "
        "ORDER BY a.rowid",
        (entity_id,),
    ).fetchall()


def rewrite_entity_link_endpoints(
    conn: sqlite3.Connection, from_entity_id: str, into_entity_id: str
) -> None:
    """Used by merge_entities. Rewrites every entity_link that
    references `from_entity_id` (as either endpoint) to reference
    `into_entity_id` instead, dropping any self-loops the merge would
    create. Without this, FK enforcement would block the source's
    deletion at merge time."""
    # Outgoing rewrites: source as `from`. For history fidelity, walk
    # row-by-row so each move emits an event pair (unlink old shape,
    # link new shape). Preserves original created_at/created_by on the
    # rewritten row — the merged-into row inherits the provenance of
    # the source link rather than being treated as fresh.
    outgoing = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
        "FROM entity_links WHERE from_entity_id = ? AND to_entity_id != ?",
        (from_entity_id, into_entity_id),
    ).fetchall()
    for r in outgoing:
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{r['from_entity_id']}|{r['to_entity_id']}|{r['link_type']}",
            before=_row_dict(r),
            context={"reason": "merge_entities"},
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                into_entity_id,
                r["to_entity_id"],
                r["link_type"],
                r["created_at"],
                r["created_by"],
            ),
        )
        if cur.rowcount:
            _record(
                conn,
                "link",
                "entity_link",
                f"{into_entity_id}|{r['to_entity_id']}|{r['link_type']}",
                after={
                    "from_entity_id": into_entity_id,
                    "to_entity_id": r["to_entity_id"],
                    "link_type": r["link_type"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                },
                context={"reason": "merge_entities"},
            )
    conn.execute("DELETE FROM entity_links WHERE from_entity_id = ?", (from_entity_id,))
    # Incoming rewrites: source as `to`. Same dedupe-merged shape.
    incoming = conn.execute(
        "SELECT from_entity_id, to_entity_id, link_type, created_at, created_by "
        "FROM entity_links WHERE to_entity_id = ? AND from_entity_id != ?",
        (from_entity_id, into_entity_id),
    ).fetchall()
    for r in incoming:
        _record(
            conn,
            "unlink",
            "entity_link",
            f"{r['from_entity_id']}|{r['to_entity_id']}|{r['link_type']}",
            before=_row_dict(r),
            context={"reason": "merge_entities"},
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO entity_links "
            "(from_entity_id, to_entity_id, link_type, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                r["from_entity_id"],
                into_entity_id,
                r["link_type"],
                r["created_at"],
                r["created_by"],
            ),
        )
        if cur.rowcount:
            _record(
                conn,
                "link",
                "entity_link",
                f"{r['from_entity_id']}|{into_entity_id}|{r['link_type']}",
                after={
                    "from_entity_id": r["from_entity_id"],
                    "to_entity_id": into_entity_id,
                    "link_type": r["link_type"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                },
                context={"reason": "merge_entities"},
            )
    conn.execute("DELETE FROM entity_links WHERE to_entity_id = ?", (from_entity_id,))
    conn.commit()
