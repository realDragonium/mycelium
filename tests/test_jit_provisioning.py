"""Just-in-time provisioning: pre-registered email domains.

These exercise `auth.find_or_create_user` directly against an in-memory
auth DB so we can assert provisioning decisions without standing up the
full OIDC dance. The precedence rules (invite > bootstrap > JIT) and the
invite-only default are the high-value cases.
"""

import sqlite3

from mycelium import auth, auth_store


def _conn() -> sqlite3.Connection:
    conn = auth_store.connect(":memory:")
    auth_store.migrate(conn)
    return conn


def _role_of(conn: sqlite3.Connection, user_id: str) -> str:
    return conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()[
        "role"
    ]


def _find(conn, email="alice@example.com", subject="sub-1"):
    return auth.find_or_create_user(
        conn,
        issuer="https://issuer",
        subject=subject,
        email=email,
        name="Alice",
    )


def test_jit_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MYCELIUM_JIT_DOMAINS", raising=False)
    conn = _conn()
    # No invite, no bootstrap, no JIT domains → invite-only, refused.
    assert _find(conn) is None
    assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_jit_provisions_allowlisted_domain(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    monkeypatch.delenv("MYCELIUM_JIT_DEFAULT_ROLE", raising=False)
    conn = _conn()
    uid = _find(conn)
    assert uid is not None
    # Default role is reader when MYCELIUM_JIT_DEFAULT_ROLE is unset.
    assert _role_of(conn, uid) == "reader"


def test_jit_refuses_unlisted_domain(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    conn = _conn()
    assert _find(conn, email="mallory@evil.com") is None


def test_jit_default_role_is_configurable(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DEFAULT_ROLE", "writer")
    conn = _conn()
    uid = _find(conn)
    assert uid is not None
    assert _role_of(conn, uid) == "writer"


def test_jit_invalid_default_role_refuses(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DEFAULT_ROLE", "superuser")
    conn = _conn()
    # Misconfigured role → refuse rather than guess a privilege level.
    assert _find(conn) is None


def test_jit_domain_parsing_tolerant(monkeypatch):
    # Leading '@', surrounding whitespace, mixed case, multiple entries.
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", " @Internal.org , Example.COM ")
    conn = _conn()
    uid = _find(conn, email="bob@example.com")
    assert uid is not None
    uid2 = _find(conn, email="carol@internal.org", subject="sub-2")
    assert uid2 is not None


def test_invite_takes_precedence_over_jit(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DEFAULT_ROLE", "reader")
    conn = _conn()
    # An active invite for the same email grants writer; the JIT default
    # (reader) must not override it.
    conn.execute(
        "INSERT INTO invites (id, email, role, token, created_at) "
        "VALUES ('inv-1', 'alice@example.com', 'writer', 'tok-1', ?)",
        (auth._now(),),
    )
    conn.commit()
    uid = _find(conn)
    assert uid is not None
    assert _role_of(conn, uid) == "writer"
    # Invite was consumed, not left dangling.
    accepted = conn.execute(
        "SELECT accepted_by FROM invites WHERE id = 'inv-1'"
    ).fetchone()["accepted_by"]
    assert accepted == uid


def test_existing_user_unaffected_by_jit(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DEFAULT_ROLE", "reader")
    conn = _conn()
    # Pre-existing admin with this email keeps their role on next login;
    # JIT only ever creates, never downgrades.
    existing = auth.create_user(
        conn,
        name="Alice",
        role="admin",
        type="human",
        email="alice@example.com",
    )
    conn.commit()
    uid = _find(conn)
    assert uid == existing
    assert _role_of(conn, uid) == "admin"
