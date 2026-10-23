"""Just-in-time provisioning: pre-registered email domains.

These exercise `auth.find_or_create_user` directly against an in-memory
auth DB so we can assert provisioning decisions without standing up the
full OIDC dance. The precedence rules (invite > bootstrap > JIT) and the
invite-only default are the high-value cases.
"""

import sqlite3

import pytest

from mycelium import auth, auth_store, oidc


def _conn() -> sqlite3.Connection:
    conn = auth_store.connect(":memory:")
    auth_store.migrate(conn)
    return conn


def _role_of(conn: sqlite3.Connection, user_id: str) -> str:
    return conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()[
        "role"
    ]


def _find(conn, email="alice@example.com", subject="sub-1", email_verified=True):
    return auth.find_or_create_user(
        conn,
        issuer="https://issuer",
        subject=subject,
        email=email,
        email_verified=email_verified,
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


# An identity provider with open signup (Auth0's default database connection)
# lets anyone register any address without proving they own it. Such an
# unverified email must not reach anything keyed on email.


def test_unverified_email_cannot_take_over_an_existing_account(monkeypatch):
    conn = _conn()
    victim = auth.create_user(
        conn, name="Admin", role="admin", type="human", email="admin@example.com"
    )
    assert _find(conn, email="admin@example.com", subject="google|1") == victim

    assert (
        _find(conn, email="admin@example.com", subject="db|2", email_verified=False)
        is None
    )
    bound = conn.execute(
        "SELECT oidc_subject FROM users WHERE id = ?", (victim,)
    ).fetchone()["oidc_subject"]
    assert bound == "google|1"


def test_unverified_email_cannot_claim_bootstrap_admin_or_invite(monkeypatch):
    monkeypatch.setenv("MYCELIUM_BOOTSTRAP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    conn = _conn()
    conn.execute(
        "INSERT INTO invites (id, email, role, token, created_at) "
        "VALUES ('inv-1', 'alice@example.com', 'writer', 'tok-1', ?)",
        (auth._now(),),
    )
    for email in ("owner@example.com", "alice@example.com", "bob@example.com"):
        assert _find(conn, email=email, email_verified=False) is None
    assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_a_bound_subject_signs_in_without_a_verified_email(monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    conn = _conn()
    uid = _find(conn)
    assert uid is not None
    assert _find(conn, email_verified=False) == uid


@pytest.mark.parametrize(
    ("claim", "verified"),
    [(None, True), (True, True), ("true", True), (False, False), ("false", False)],
)
def test_email_verified_claim(claim, verified):
    claims = {} if claim is None else {"email_verified": claim}
    assert oidc.email_verified(claims) is verified
