"""`MYCELIUM_ALLOWED_EMAIL_DOMAINS`: only people with an email in an allowed
domain may use the service, whichever way they arrive."""

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

import test_oauth as oauth_flow
from mycelium import auth, auth_store, embed, store
from mycelium.server import runtime

ISSUER = "https://issuer"


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "Example.com, @corp.test")
    monkeypatch.delenv("MYCELIUM_JIT_DOMAINS", raising=False)
    monkeypatch.delenv("MYCELIUM_BOOTSTRAP_ADMIN_EMAIL", raising=False)


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = auth_store.connect(":memory:")
    auth_store.migrate(conn)
    return conn


def _login(conn, email, *, subject="sub-1", verified=True):
    return auth.find_or_create_user(
        conn,
        issuer=ISSUER,
        subject=subject,
        email=email,
        email_verified=verified,
        name="Someone",
    )


def _invite(conn, email: str) -> None:
    admin = auth.create_user(conn, name="Admin", role="admin", type="service")
    auth.create_invite(conn, email=email, role="writer", invited_by=admin)


def _user_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# --- the domain match itself -------------------------------------------------


@pytest.mark.parametrize(
    ("email", "allowed"),
    [
        ("alice@example.com", True),
        ("Alice@EXAMPLE.com", True),
        ("bob@corp.test", True),
        ("mallory@evil-example.com", False),
        ("mallory@example.com.evil.test", False),
        ("carol@sub.example.com", False),
        ("not-an-email", False),
        (None, False),
    ],
)
def test_domain_match_is_exact_and_case_insensitive(policy, email, allowed):
    assert auth.email_domain_allowed(email) is allowed


def test_unset_policy_allows_everyone(monkeypatch):
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.delenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", raising=False)
    assert auth.email_domain_allowed("anyone@anywhere.test")


def test_auth_off_ignores_the_policy(monkeypatch):
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "example.com")
    assert auth.email_domain_allowed("anyone@anywhere.test")


def test_service_accounts_are_not_judged_by_email(policy):
    assert not auth.blocked_by_domain_policy("service", None)
    assert auth.blocked_by_domain_policy("human", None)
    assert auth.blocked_by_domain_policy("human", "a@evil-example.com")


def test_a_jit_domain_outside_the_allowed_list_refuses_to_start(policy, monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com, partner.test")
    with pytest.raises(RuntimeError, match=r"partner\.test"):
        auth.check_domain_policy()
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    auth.check_domain_policy()


# --- OIDC login --------------------------------------------------------------


def test_subject_match_is_refused_for_a_user_from_before_the_policy(
    policy, conn, monkeypatch
):
    monkeypatch.delenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS")
    auth.create_user(
        conn,
        name="Old",
        role="writer",
        type="human",
        email="old@outside.test",
        oidc_issuer=ISSUER,
        oidc_subject="sub-old",
    )
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "example.com")
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "old@outside.test", subject="sub-old")


def test_subject_match_needs_the_idp_email_to_be_allowed_and_verified(policy, conn):
    auth.create_user(
        conn,
        name="Alice",
        role="writer",
        type="human",
        email="alice@example.com",
        oidc_issuer=ISSUER,
        oidc_subject="sub-a",
    )
    assert _login(conn, "alice@example.com", subject="sub-a") is not None
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "alice@example.com", subject="sub-a", verified=False)
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "alice@elsewhere.test", subject="sub-a")


def test_email_match_on_a_lookalike_domain_is_refused_without_binding(policy, conn):
    uid = auth.create_user(
        conn, name="Look", role="writer", type="human", email="x@evil-example.com"
    )
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "x@evil-example.com")
    row = conn.execute("SELECT oidc_subject FROM users WHERE id = ?", (uid,)).fetchone()
    assert row["oidc_subject"] is None


def test_an_invite_outside_the_policy_is_not_consumed(policy, conn, monkeypatch):
    monkeypatch.delenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS")
    _invite(conn, "guest@outside.test")
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "example.com")
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "guest@outside.test")
    assert _user_count(conn) == 1
    assert len(auth.list_invites(conn)) == 1


def test_the_bootstrap_admin_must_be_in_an_allowed_domain(policy, conn, monkeypatch):
    monkeypatch.setenv("MYCELIUM_BOOTSTRAP_ADMIN_EMAIL", "root@outside.test")
    with pytest.raises(auth.EmailDomainNotAllowed):
        _login(conn, "root@outside.test")
    assert _user_count(conn) == 0


def test_jit_and_invites_still_work_inside_the_policy(policy, conn, monkeypatch):
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.com")
    assert _login(conn, "new@example.com", subject="s1") is not None
    _invite(conn, "inv@corp.test")
    assert _login(conn, "inv@corp.test", subject="s2") is not None


def test_a_refusal_logs_the_domain_but_not_the_address(policy, conn, caplog):
    with caplog.at_level(logging.INFO, logger="mycelium.auth"):
        with pytest.raises(auth.EmailDomainNotAllowed):
            _login(conn, "secret.person@outside.test")
    refusals = [r.getMessage() for r in caplog.records]
    assert len(refusals) == 1
    assert "outside.test" in refusals[0]
    assert "secret.person" not in refusals[0]


# --- existing sessions and tokens ---------------------------------------------


def test_a_session_ends_once_the_users_domain_is_no_longer_allowed(
    policy, conn, monkeypatch
):
    inside = auth.create_user(
        conn, name="In", role="writer", type="human", email="in@example.com"
    )
    outside = auth.create_user(
        conn, name="Out", role="writer", type="human", email="out@outside.test"
    )
    assert auth.resolve_session_user(conn, inside) is not None
    assert auth.resolve_session_user(conn, outside) is None
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "corp.test")
    assert auth.resolve_session_user(conn, inside) is None


def test_a_token_is_judged_by_its_owners_email(policy, conn):
    inside = auth.create_user(
        conn, name="In", role="writer", type="human", email="in@example.com"
    )
    outside = auth.create_user(
        conn, name="Out", role="writer", type="human", email="out@evil-example.com"
    )
    service = auth.create_user(conn, name="ci", role="writer", type="service")
    tokens = {
        uid: auth.issue_token(conn, user_id=uid, name="t", scope="writer")[0]
        for uid in (inside, outside, service)
    }
    assert auth.resolve_token(conn, tokens[inside]) is not None
    assert auth.resolve_token(conn, tokens[outside]) is None
    assert auth.resolve_token(conn, tokens[service]) is not None


# --- HTTP: invites, the users screen and OAuth ----------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch, policy):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    runtime._ctx = None
    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    with TestClient(app) as c:
        yield c


def _admin_headers() -> dict[str, str]:
    conn = runtime._auth_db()
    with store.transaction(conn):
        uid = auth.create_user(
            conn, name="Admin", role="admin", type="human", email="admin@example.com"
        )
        raw, _ = auth.issue_token(conn, user_id=uid, name="t", scope="admin")
    return {"Authorization": f"Bearer {raw}"}


def test_inviting_an_address_outside_the_allowed_domains_is_refused(client):
    h = _admin_headers()
    r = client.post(
        "/api/admin/invites", json={"email": "x@evil-example.com"}, headers=h
    )
    assert r.status_code == 400
    assert "evil-example.com" in r.json()["detail"]
    r = client.post("/api/admin/invites", json={"email": "x@example.com"}, headers=h)
    assert r.status_code == 200


def test_the_users_screen_marks_who_the_domain_policy_blocks(client):
    h = _admin_headers()
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.create_user(
            conn, name="Out", role="reader", type="human", email="o@outside.test"
        )
        auth.create_user(conn, name="ci", role="writer", type="service")
    users = client.get("/api/admin/users", headers=h).json()["users"]
    blocked = {u["name"]: u["blocked_by_domain_policy"] for u in users}
    assert blocked == {"Admin": False, "Out": True, "ci": False}


def _block_admin_domain() -> None:
    conn = runtime._auth_db()
    with store.transaction(conn):
        conn.execute("UPDATE users SET email = 'admin@evil-example.com'")


def test_oauth_code_exchange_refuses_a_user_blocked_since_consent(client):
    raw = _admin_headers()["Authorization"].removeprefix("Bearer ")
    consent, client_id, verifier = oauth_flow._consent(client, admin_bearer=raw)
    _block_admin_domain()
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(consent.headers["location"]).query)["code"][0]
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:6274/cb",
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert r.json()["error"] == "invalid_grant"


def test_oauth_refresh_refuses_a_user_blocked_since_the_grant(client):
    raw = _admin_headers()["Authorization"].removeprefix("Bearer ")
    r, client_id, _, _ = oauth_flow._full_flow(client, admin_bearer=raw)
    _block_admin_domain()
    r = oauth_flow._refresh(client, r.json()["refresh_token"], client_id)
    assert r.json()["error"] == "invalid_grant"


def test_oauth_authorize_refuses_a_user_outside_the_allowed_domains(client):
    conn = runtime._auth_db()
    with store.transaction(conn):
        uid = auth.create_user(
            conn, name="Out", role="writer", type="human", email="o@outside.test"
        )
        raw, _ = auth.issue_token(conn, user_id=uid, name="t", scope="writer")
    reg = client.post(
        "/register",
        json={"client_name": "c", "redirect_uris": ["http://localhost:6274/cb"]},
    ).json()
    r = client.get(
        "/authorize",
        params={
            "client_id": reg["client_id"],
            "redirect_uri": "http://localhost:6274/cb",
            "response_type": "code",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "scope": "mcp",
        },
        headers={"Authorization": f"Bearer {raw}"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("/auth/login")
