"""Auth database — separate SQLite file from the substrate.

Identity (users, tokens, invites, OAuth clients/codes) lives here so
the substrate file can be swapped, restored from backup, or wiped
without affecting who can log in or what tokens are valid.

The file lives at `<data_dir>/auth.db` alongside `main.db` and
`history.db`. Foreign keys inside this file are honored (PRAGMA
foreign_keys=ON); there are no FKs *across* files because SQLite
doesn't support cross-database FKs anyway, which is exactly the
property we want — the substrate has zero schema dependencies on
identity.

Why a single in-file schema with no migrations? The auth schema is
new (introduced in this same change), so there's no legacy shape to
migrate from. If the schema needs to evolve later we can adopt the
same `user_version` + migration-runner pattern that `store.py` uses.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


AUTH_SCHEMA = """
-- Identities. Humans authenticate via OIDC (oidc_issuer + oidc_subject
-- populated); service accounts represent third-party agents and have
-- NULL oidc fields, only tokens. `role` gates write/admin actions;
-- per-token scope can only narrow it, never widen.
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL CHECK (type IN ('human', 'service')),
    email         TEXT,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,  -- free-form; valid roles live in code (auth.Role), not the DB
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    oidc_issuer   TEXT,
    oidc_subject  TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    last_login_at TEXT,
    UNIQUE (oidc_issuer, oidc_subject),
    UNIQUE (email)
);

-- Registered OAuth clients (typically Claude Desktop / Claude Code,
-- one row per install). Created via /register (RFC 7591 Dynamic Client
-- Registration). No client_secret column on purpose — we only accept
-- public clients with PKCE, matching the MCP spec's posture for native
-- / desktop clients.
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id     TEXT PRIMARY KEY,
    client_name   TEXT,
    redirect_uris TEXT NOT NULL,   -- JSON array of allowed redirect URIs
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);

-- Opaque bearer tokens. The raw secret is shown once at creation;
-- only the sha256 hash is persisted. `prefix` is the visible-in-UI
-- identifier (myc_<prefix>_<secret>) so a user can recognize a token
-- in a list without ever seeing the secret again.
--
-- OAuth-issued tokens record which registered client minted them and
-- (optionally) when they expire. Manually-minted tokens leave both
-- NULL — they're long-lived and tied only to the user.
CREATE TABLE IF NOT EXISTS mcp_tokens (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL UNIQUE,
    hash         TEXT NOT NULL,
    scope        TEXT NOT NULL,  -- free-form; narrowed against the owner's role in code
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT,
    client_id    TEXT REFERENCES oauth_clients(client_id) ON DELETE SET NULL,
    expires_at   TEXT
);
CREATE INDEX IF NOT EXISTS mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX IF NOT EXISTS mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX IF NOT EXISTS mcp_tokens_client ON mcp_tokens (client_id);

-- Admin-generated invites that bind an email to a role. First OIDC
-- login from the bound email consumes the invite (accepted_at
-- populated).
CREATE TABLE IF NOT EXISTS invites (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL,  -- free-form; see auth.Role
    token       TEXT NOT NULL UNIQUE,
    invited_by  TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    accepted_at TEXT,
    accepted_by TEXT REFERENCES users(id)
);

-- Short-lived authorization codes for the OAuth Authorization Code
-- + PKCE flow. `code_challenge` is verified against the verifier on
-- exchange at /token. Used rows are kept (used_at populated) so
-- replay attempts produce an explicit 'already used' error; pruning
-- is left to a periodic cleanup.
CREATE TABLE IF NOT EXISTS oauth_codes (
    code                  TEXT PRIMARY KEY,
    client_id             TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri          TEXT NOT NULL,
    code_challenge        TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL CHECK (code_challenge_method IN ('S256', 'plain')),
    scope                 TEXT,
    created_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    used_at               TEXT
);
CREATE INDEX IF NOT EXISTS oauth_codes_expiry ON oauth_codes (expires_at);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the auth DB. Same convention as `store.connect`:
    `check_same_thread=False` because uvicorn workers reuse the
    connection across requests, and `row_factory=Row` for dict-style
    access. FKs are enforced so cascade-on-user-delete works."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Create / update tables. Idempotent (CREATE TABLE IF NOT EXISTS).

    Also drops the legacy CHECK on the role/scope columns if an existing DB
    still has it. Roles are free-form TEXT now — the valid set lives in code
    (auth.Role), so adding a role never needs a DB migration. SQLite can't
    ALTER a CHECK in place, so we rebuild the affected tables (users,
    mcp_tokens, invites) preserving every row.
    """
    conn.executescript(AUTH_SCHEMA)
    rebuilt = _drop_role_check(conn)
    if rebuilt:
        # Rebuild dropped explicit indexes along with the old table;
        # re-running the schema script restores them (all CREATE INDEX
        # statements are IF NOT EXISTS, so this is a no-op for fresh DBs).
        conn.executescript(AUTH_SCHEMA)
    conn.commit()


def _drop_role_check(conn: sqlite3.Connection) -> bool:
    """Drop the legacy CHECK constraint on the role-bearing columns
    (users.role, mcp_tokens.scope, invites.role). Returns True iff any
    rebuild ran.

    Roles are free-form TEXT now: the valid set lives in code (auth.Role),
    so adding a role never touches the DB. Existing DBs created with the old
    `CHECK (role IN (...))` are rebuilt without it. Detection is a substring
    check on `sqlite_master.sql` for the column's role/scope CHECK — present
    means the old form, absent means already free-form. Idempotent: a fresh
    DB written from AUTH_SCHEMA has no such CHECK.
    """
    # (table, new-schema body — same as AUTH_SCHEMA but standalone, used
    # to recreate the table under a temp name during rebuild).
    rebuilds = {
        "users": """
            CREATE TABLE users_new (
                id            TEXT PRIMARY KEY,
                type          TEXT NOT NULL CHECK (type IN ('human', 'service')),
                email         TEXT,
                name          TEXT NOT NULL,
                role          TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
                oidc_issuer   TEXT,
                oidc_subject  TEXT,
                created_at    TEXT NOT NULL,
                created_by    TEXT,
                last_login_at TEXT,
                UNIQUE (oidc_issuer, oidc_subject),
                UNIQUE (email)
            )
        """,
        "mcp_tokens": """
            CREATE TABLE mcp_tokens_new (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                prefix       TEXT NOT NULL UNIQUE,
                hash         TEXT NOT NULL,
                scope        TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at   TEXT,
                client_id    TEXT REFERENCES oauth_clients(client_id) ON DELETE SET NULL,
                expires_at   TEXT
            )
        """,
        "invites": """
            CREATE TABLE invites_new (
                id          TEXT PRIMARY KEY,
                email       TEXT NOT NULL,
                role        TEXT NOT NULL,
                token       TEXT NOT NULL UNIQUE,
                invited_by  TEXT REFERENCES users(id),
                created_at  TEXT NOT NULL,
                expires_at  TEXT,
                accepted_at TEXT,
                accepted_by TEXT REFERENCES users(id)
            )
        """,
    }
    any_rebuilt = False
    # FKs must be OFF for the swap, can't be toggled inside a tx, and
    # the rebuild itself runs inside a single BEGIN…COMMIT so a crash
    # mid-migration leaves the old table intact.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for table, new_ddl in rebuilds.items():
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
                (table,),
            ).fetchone()
            if row is None:
                continue  # fresh DB — schema script already created it
            current_sql = row["sql"] or ""
            marker = "CHECK (scope IN" if table == "mcp_tokens" else "CHECK (role IN"
            if marker not in current_sql:
                continue  # already free-form (no role/scope CHECK)
            cols = [
                c["name"]
                for c in conn.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            col_list = ", ".join(cols)
            conn.execute("BEGIN")
            try:
                conn.executescript(new_ddl)
                conn.execute(
                    f"INSERT INTO {table}_new ({col_list}) SELECT {col_list} FROM {table}"
                )
                conn.execute(f"DROP TABLE {table}")
                conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
                # Sanity check: surfaces FK breakage before we commit.
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(
                        f"auth migration broke foreign keys after rebuilding {table}: {broken}"
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            any_rebuilt = True
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return any_rebuilt
