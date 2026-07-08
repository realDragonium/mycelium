"""Auth-store migration tests.

Roles are free-form TEXT — the valid set lives in code (auth.Role), not the DB.
Legacy DBs carried a CHECK constraint on users.role, mcp_tokens.scope, and
invites.role; SQLite can't ALTER a CHECK in place, so `auth_store.migrate`
detects those old schemas and rebuilds the three tables (dropping the CHECK)
preserving rows + FKs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# The pre-drafter schema, transcribed verbatim from the prior auth_store.py.
# We seed a DB with this and then run migrate() to assert the rebuild flips
# the CHECK constraints without losing rows.
_OLD_SCHEMA = """
CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL CHECK (type IN ('human', 'service')),
    email         TEXT,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('reader', 'writer', 'admin')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    oidc_issuer   TEXT,
    oidc_subject  TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    last_login_at TEXT,
    UNIQUE (oidc_issuer, oidc_subject),
    UNIQUE (email)
);
CREATE TABLE oauth_clients (
    client_id     TEXT PRIMARY KEY,
    client_name   TEXT,
    redirect_uris TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);
CREATE TABLE mcp_tokens (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL UNIQUE,
    hash         TEXT NOT NULL,
    scope        TEXT NOT NULL CHECK (scope IN ('reader', 'writer', 'admin')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT,
    client_id    TEXT REFERENCES oauth_clients(client_id) ON DELETE SET NULL,
    expires_at   TEXT
);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE TABLE invites (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('reader', 'writer', 'admin')),
    token       TEXT NOT NULL UNIQUE,
    invited_by  TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    accepted_at TEXT,
    accepted_by TEXT REFERENCES users(id)
);
CREATE TABLE oauth_codes (
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
"""


def _seed_old_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA)
    # Seed representative rows so we can confirm migrate preserves data
    # and FK references survive the rebuild.
    conn.execute(
        "INSERT INTO users (id, type, name, role, status, created_at) "
        "VALUES ('u1', 'human', 'Alice', 'admin', 'active', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, type, name, role, status, created_at) "
        "VALUES ('u2', 'service', 'Bot', 'writer', 'active', '2026-01-02')"
    )
    conn.execute(
        "INSERT INTO oauth_clients (client_id, redirect_uris, created_at) "
        "VALUES ('c1', '[]', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO mcp_tokens (id, user_id, name, prefix, hash, scope, created_at) "
        "VALUES ('t1', 'u1', 'tok', 'abc123', 'sha', 'admin', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO invites (id, email, role, token, invited_by, created_at) "
        "VALUES ('i1', 'b@x.test', 'writer', 'invtok', 'u1', '2026-01-01')"
    )
    conn.commit()
    return conn


def test_migrate_drops_role_check_and_preserves_rows(tmp_path):
    """Seed an old-schema (CHECK-constrained) DB, run migrate, confirm the
    CHECK is gone — an arbitrary new role inserts — and original rows survive."""
    from mycelium import auth_store

    db_path = tmp_path / "auth.db"
    seed = _seed_old_db(db_path)
    seed.close()

    conn = auth_store.connect(db_path)
    auth_store.migrate(conn)

    # A role in NO enum (not even 'drafter') now inserts — proof roles are
    # free-form and adding one never needs a DB change. The old CHECK would
    # have rejected this with IntegrityError.
    conn.execute(
        "INSERT INTO users (id, type, name, role, status, created_at) "
        "VALUES ('u3', 'service', 'Analyst', 'analyst', 'active', '2026-05-26')"
    )
    conn.execute(
        "INSERT INTO mcp_tokens (id, user_id, name, prefix, hash, scope, created_at) "
        "VALUES ('t2', 'u3', 'tok-a', 'def456', 'sha2', 'analyst', '2026-05-26')"
    )
    conn.execute(
        "INSERT INTO invites (id, email, role, token, invited_by, created_at) "
        "VALUES ('i2', 'd@x.test', 'analyst', 'invtok2', 'u1', '2026-05-26')"
    )
    conn.commit()

    # Pre-existing rows are untouched.
    rows = conn.execute("SELECT id, role FROM users ORDER BY id").fetchall()
    assert [(r["id"], r["role"]) for r in rows] == [
        ("u1", "admin"),
        ("u2", "writer"),
        ("u3", "analyst"),
    ]
    tok = conn.execute(
        "SELECT user_id, scope FROM mcp_tokens WHERE id = 't1'"
    ).fetchone()
    assert tok["user_id"] == "u1" and tok["scope"] == "admin"

    # FKs survived the rebuild — invited_by still resolves.
    inv = conn.execute(
        "SELECT i.role, u.name FROM invites i JOIN users u ON u.id = i.invited_by WHERE i.id = 'i1'"
    ).fetchone()
    assert inv["role"] == "writer" and inv["name"] == "Alice"

    # Indexes restored.
    idx = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='mcp_tokens'"
        ).fetchall()
    }
    assert "mcp_tokens_user" in idx and "mcp_tokens_hash" in idx


def test_migrate_is_idempotent(tmp_path):
    """Second migrate() on an already-wide DB is a no-op (no rebuild)."""
    from mycelium import auth_store

    db_path = tmp_path / "auth.db"
    conn = auth_store.connect(db_path)
    auth_store.migrate(conn)  # fresh DB — wide from the start
    # Snapshot the user-table SQL; migrate again; confirm unchanged.
    before = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()["sql"]
    auth_store.migrate(conn)
    after = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()["sql"]
    assert before == after


def test_migrate_on_fresh_db_has_no_role_check(tmp_path):
    from mycelium import auth_store

    conn = auth_store.connect(tmp_path / "auth.db")
    auth_store.migrate(conn)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()["sql"]
    assert "CHECK (role IN" not in sql  # role is free-form TEXT
