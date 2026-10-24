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

import pytest

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


def test_migrate_unscopes_principals_and_logs_each(caplog):
    from mycelium import auth_store

    conn = _seed_old_db(Path(":memory:"))
    for table in ("users", "mcp_tokens", "oauth_codes"):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN audience_id TEXT")
    conn.execute("UPDATE users SET audience_id = 'external' WHERE id = 'u2'")
    conn.execute("UPDATE mcp_tokens SET audience_id = 'external' WHERE id = 't1'")

    with caplog.at_level("WARNING", logger="mycelium.auth"):
        auth_store.migrate(conn)

    for table in ("users", "mcp_tokens", "oauth_codes"):
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "audience_id" not in columns
    assert [r["id"] for r in conn.execute("SELECT id FROM users ORDER BY id")] == [
        "u1",
        "u2",
    ]
    assert [r.getMessage().split()[:2] for r in caplog.records] == [
        ["users", "u2"],
        ["mcp_tokens", "t1"],
    ]


def test_migrate_turns_askers_into_readers_and_logs_the_count(caplog):
    from mycelium import auth_store

    conn = _seed_old_db(Path(":memory:"))
    auth_store.migrate(conn)
    conn.execute("UPDATE users SET role = 'asker' WHERE id = 'u2'")
    conn.execute(
        "INSERT INTO mcp_tokens (id, user_id, name, prefix, hash, scope, created_at, "
        "client_id) VALUES ('t2', 'u2', 'oauth', 'def456', 'sha2', 'asker', "
        "'2026-01-02', 'c1')"
    )
    conn.execute("UPDATE invites SET role = 'asker'")

    with caplog.at_level("WARNING", logger="mycelium.auth"):
        auth_store.migrate(conn)

    assert conn.execute("SELECT role FROM users WHERE id = 'u2'").fetchone()[0] == (
        "reader"
    )
    assert conn.execute("SELECT scope FROM mcp_tokens WHERE id = 't2'").fetchone()[
        0
    ] == ("reader")
    assert conn.execute("SELECT role FROM invites").fetchone()[0] == "reader"
    assert [r.getMessage() for r in caplog.records] == [
        "1 users with the retired asker role now have reader",
        "1 mcp_tokens with the retired asker role now have reader",
        "1 invites with the retired asker role now have reader",
    ]


@pytest.mark.parametrize("table", ["users", "mcp_tokens", "invites"])
def test_failed_copy_rolls_back_rebuild_and_can_be_retried(table):
    from mycelium import auth_store

    conn = _seed_old_db(Path(":memory:"))
    conn.execute("PRAGMA foreign_keys = ON")
    before_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
    ).fetchone()["sql"]
    before_rows = [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]

    def deny_copy(action, name, _column, _database, _trigger):
        if action == sqlite3.SQLITE_INSERT and name == f"{table}_new":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    try:
        conn.set_authorizer(deny_copy)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            auth_store._drop_role_check(conn)
        conn.set_authorizer(None)
        assert not conn.in_transaction
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name GLOB '*_new'"
            ).fetchall()
            == []
        )
        assert (
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()["sql"]
            == before_sql
        )
        assert [
            tuple(row) for row in conn.execute(f"SELECT * FROM {table}")
        ] == before_rows

        auth_store.migrate(conn)
        assert [
            tuple(row) for row in conn.execute(f"SELECT * FROM {table}")
        ] == before_rows
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert auth_store._drop_role_check(conn) is False
    finally:
        conn.close()
