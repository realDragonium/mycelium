"""GitHub setup and publishing with fake HTTP and isolated instance storage."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from mycelium import (
    auth,
    github_app,
    github_connect,
    github_connections,
    product_settings,
    prompt_store,
)
from mycelium.docgen import destinations, github_destination

ADMIN = auth.Principal(id="admin", name="Admin", role="admin", type="human")
USER_TOKEN = "github-user-secret-fixture"
APP_TOKEN = "github-installation-secret-fixture"
REPO = {
    "id": 34,
    "name": "handbook",
    "owner": {"login": "acme"},
    "default_branch": "main",
    "permissions": {"push": True},
}
INSTALLATION = {
    "id": 12,
    "app_id": 56,
    "account": {"login": "acme"},
    "permissions": {"contents": "write", "pull_requests": "write"},
}


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "prompts.db"
    conn = prompt_store.connect(path)
    prompt_store.migrate(conn)
    prompt_store.configure(path)
    prompt_store.save(
        conn, type="guideline-set", name="kb-authoring/guidance", text="Write clearly."
    )
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def app_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def app_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_key: rsa.RSAPrivateKey
) -> github_app.AppConfig:
    path = tmp_path / "test-app.pem"
    path.write_bytes(
        app_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    values = {
        "ID": "56",
        "CLIENT_ID": "fixture-client",
        "CLIENT_SECRET": "fixture-client-secret",
        "SLUG": "fixture-app",
        "PRIVATE_KEY_FILE": str(path),
        "CALLBACK_URL": "http://localhost/api/github/callback",
    }
    for name, value in values.items():
        monkeypatch.setenv("MYCELIUM_GITHUB_APP_" + name, value)
    return github_app.AppConfig.load()


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.repository = dict(REPO)
        self.installation = dict(INSTALLATION)
        self.failure: int | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            return httpx.Response(self.failure, text=USER_TOKEN + APP_TOKEN)
        path = request.url.path
        if path == "/login/oauth/access_token":
            return httpx.Response(
                200, json={"access_token": USER_TOKEN, "token_type": "bearer"}
            )
        if path == "/user/installations":
            assert request.headers["authorization"] == "Bearer " + USER_TOKEN
            return httpx.Response(200, json={"installations": [self.installation]})
        if path == "/user/installations/12/repositories":
            return httpx.Response(200, json={"repositories": [self.repository]})
        if path == "/app/installations/12":
            return httpx.Response(200, json=self.installation)
        if path == "/app/installations/12/access_tokens":
            assert json.loads(request.content) == {
                "repository_ids": [34],
                "permissions": {"contents": "write", "pull_requests": "write"},
            }
            return httpx.Response(201, json={"token": APP_TOKEN})
        if path == "/repos/acme/handbook":
            return httpx.Response(200, json=self.repository)
        if path == "/repos/acme/handbook/branches/main":
            return httpx.Response(200, json={"name": "main"})
        raise AssertionError(f"Unexpected GitHub request: {request.method} {path}")


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(
        github_app,
        "client",
        lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


@pytest.fixture
def web(
    db: sqlite3.Connection,
    app_config: github_app.AppConfig,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(github_connect.router)
    app.add_middleware(
        SessionMiddleware,
        secret_key="fixture-session-signing-secret",
        session_cookie="myc_session",
    )

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = ADMIN
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def bad_request(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    monkeypatch.setattr(github_connect, "flows", github_connect.Flows())
    with TestClient(app, base_url="http://localhost", follow_redirects=False) as client:
        yield client


def authorize(
    web: TestClient, *, install: bool = False, installation_id: int = 12
) -> httpx.Response:
    response = web.post("/api/github/start", json={"existing": not install})
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    if install:
        response = web.get(
            "/api/github/setup",
            params={"state": state, "installation_id": installation_id},
        )
        assert response.status_code == 303, response.text
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    return web.get(
        "/api/github/callback", params={"state": state, "code": "fixture-code"}
    )


def connect(web: TestClient) -> str:
    assert authorize(web).status_code == 303
    response = web.post(
        "/api/github/connections",
        json={"installation_id": 12, "repository_id": 34, "base_branch": "main"},
    )
    assert response.status_code == 200, response.text
    return response.json()["name"]


def test_browser_flow_saves_only_verified_repository_metadata(
    web: TestClient, github: FakeGitHub, db: sqlite3.Connection
):
    response = authorize(web, install=True)
    assert (
        response.headers["location"] == "/ui/#/documentation?tab=settings&github=ready"
    )
    assert web.get("/api/github/repositories").json() == [
        {
            "installation_id": 12,
            "repository_id": 34,
            "owner": "acme",
            "repo": "handbook",
            "default_branch": "main",
        }
    ]
    result = web.post(
        "/api/github/connections",
        json={"installation_id": 12, "repository_id": 34, "base_branch": "main"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["name"] == "github-app:56:12:34"
    saved = db.execute("SELECT body_json FROM github_app_connections").fetchone()[0]
    cookie = web.cookies.get("myc_session")
    decoded = base64.b64decode(cookie.split(".")[0]).decode()
    for secret in (USER_TOKEN, APP_TOKEN, "fixture-code", "fixture-client-secret"):
        assert secret not in saved + decoded + result.text
    exchange = next(
        request
        for request in github.requests
        if request.url.path == "/login/oauth/access_token"
    )
    assert "code_verifier=" in exchange.content.decode()


def test_spoofed_installation_and_unwritable_repository_cannot_connect(
    web: TestClient, github: FakeGitHub
):
    assert authorize(web, install=True, installation_id=99).status_code == 303
    assert web.get("/api/github/repositories").json() == []
    assert (
        web.post(
            "/api/github/connections",
            json={"installation_id": 12, "repository_id": 34, "base_branch": "main"},
        ).status_code
        == 400
    )
    github.repository["permissions"] = {"push": False}
    assert authorize(web).status_code == 303
    assert web.get("/api/github/repositories").json() == []


def test_state_is_browser_bound_and_single_use(web: TestClient):
    start = web.post("/api/github/start", json={"existing": True}).json()
    state = parse_qs(urlsplit(start["url"]).query)["state"][0]
    cookie = web.cookies.get("myc_session")
    web.cookies.clear()
    params = {"state": state, "code": "fixture-code"}
    assert web.get("/api/github/callback", params=params).status_code == 400
    web.cookies.clear()
    web.cookies.set("myc_session", cookie)
    assert web.get("/api/github/callback", params=params).status_code == 303
    assert web.get("/api/github/callback", params=params).status_code == 400


def test_flow_expiry_principal_and_phase_are_enforced(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(github_connect.time, "monotonic", lambda: 100)
    flows = github_connect.Flows()
    flow = github_connect.Flow("admin", "browser", "/ui/", 200, "authorize", "verifier")
    key = flows.put(flow)
    for principal, browser, phase in [
        ("other", "browser", "authorize"),
        ("admin", "other", "authorize"),
        ("admin", "browser", "select"),
    ]:
        with pytest.raises(github_app.GitHubError, match="browser session"):
            flows.get(key, principal, browser, phase)
    monkeypatch.setattr(github_connect.time, "monotonic", lambda: 201)
    with pytest.raises(github_app.GitHubError, match="expired"):
        flows.get(key, "admin", "browser", "authorize")


@pytest.mark.parametrize("role", ["reader", "writer", "drafter"])
def test_only_actual_admin_can_connect(
    web: TestClient, monkeypatch: pytest.MonkeyPatch, role: str
):
    from dataclasses import replace

    monkeypatch.setattr(__import__(__name__), "ADMIN", replace(ADMIN, role=role))
    assert web.post("/api/github/start", json={}).status_code == 403
    assert (
        web.post("/api/github/disconnect", json={"name": "anything"}).status_code == 403
    )


def test_start_rejects_cross_origin_and_form_posts(web: TestClient):
    assert (
        web.post(
            "/api/github/start", json={}, headers={"origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert (
        web.post(
            "/api/github/start", content="{}", headers={"content-type": "text/plain"}
        ).status_code
        == 422
    )


def test_disconnection_preserves_identity_and_restore_requires_reconnection(
    web: TestClient, db: sqlite3.Connection, github: FakeGitHub
):
    name = connect(web)
    assert github_connections.access_token(name, "acme", "handbook") == APP_TOKEN
    assert web.post("/api/github/disconnect", json={"name": name}).status_code == 200
    with pytest.raises(github_app.GitHubError, match="disconnected"):
        github_connections.access_token(name, "acme", "handbook")
    assert connect(web) == name
    archived = product_settings.archive(db)
    restored = prompt_store.connect(":memory:")
    prompt_store.migrate(restored)
    product_settings.restore(restored, archived)
    assert not github_connections.resolve(name, restored).enabled
    assert APP_TOKEN not in archived.model_dump_json()
    restored.close()


def test_repository_replacement_and_revocation_block_publishing(
    web: TestClient, github: FakeGitHub
):
    name = connect(web)
    github.repository["id"] = 999
    with pytest.raises(github_app.GitHubError, match="renamed or replaced"):
        github_connections.access_token(name, "acme", "handbook")
    github.failure = 403
    with pytest.raises(github_app.GitHubError, match="access is unavailable") as error:
        github_connections.access_token(name, "acme", "handbook")
    assert APP_TOKEN not in str(error.value)


def test_app_connection_settings_and_research_boundary(web: TestClient):
    name = connect(web)
    destination = product_settings.DestinationSettings(
        name="docs",
        owner="acme",
        repo="handbook",
        base_branch="main",
        path_template="docs/{slug}.md",
        binding=name,
    )
    product_settings.validate_secrets(
        product_settings.DocumentationSettings(destinations=(destination,))
    )
    config = destination.destination()
    assert config.settings == {
        "owner": "acme",
        "repo": "handbook",
        "base_branch": "main",
        "host": "github.com",
        "connection": name,
    }
    with pytest.raises(ValueError, match="different repository"):
        destination.model_copy(update={"repo": "other"}).destination()
    source = product_settings.SourceSettings(
        name="docs", owner="acme", repo="handbook", binding=name
    )
    with pytest.raises(ValueError, match="documentation only"):
        product_settings.validate_secrets(
            product_settings.SourcesSettings(sources=(source,))
        )


def test_jwt_is_signed_and_short_lived(app_config: github_app.AppConfig):
    token = github_app.app_jwt(app_config, 1000)
    header, body, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    assert claims == {"iat": 940, "exp": 1540, "iss": "fixture-client"}
    key = serialization.load_pem_private_key(
        app_config.private_key_file.read_bytes(), None
    )
    assert isinstance(key, rsa.RSAPrivateKey)
    key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=="),
        f"{header}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_app_token_flows_through_document_read_and_pr_delivery(web: TestClient):
    from test_document_destinations import _blob_id, _document, _responses

    name = connect(web)
    config = destinations.DestinationConfig(
        "docs",
        "github",
        "docs/{slug}.md",
        {
            "owner": "acme",
            "repo": "handbook",
            "base_branch": "docs-main",
            "connection": name,
        },
    )
    requests, handler = _responses()
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        result = github_destination.deliver(config, _document(), client=transport)
        assert result.reference.startswith("https://github.com/acme/handbook/pull/")

    assert all(
        request.headers["authorization"] == "Bearer " + APP_TOKEN
        for request in requests
    )
    body = "# Saved GitHub document\n"

    def read_response(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer " + APP_TOKEN
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(body.encode()).decode(),
                "sha": _blob_id(body),
            },
        )

    with httpx.Client(transport=httpx.MockTransport(read_response)) as transport:
        current = github_destination.read(
            config, "docs/saved.md", "gdc_123", "configuring-sso", client=transport
        )
    assert current.body == body


def test_pending_installation_permissions_do_not_hide_other_repositories(
    app_config: github_app.AppConfig,
):
    blocked = {
        **INSTALLATION,
        "id": 98,
        "permissions": {"contents": "read", "pull_requests": "read"},
    }
    fake = FakeGitHub()

    def response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/installations":
            return httpx.Response(200, json={"installations": [blocked, INSTALLATION]})
        return fake.handle(request)

    with httpx.Client(transport=httpx.MockTransport(response)) as transport:
        choices = github_app.GitHubClient(transport, app_config).repositories(
            USER_TOKEN, None
        )
    assert [item.repository_id for item in choices] == [34]


def test_published_document_keeps_connection_branch_and_path_after_settings_change(
    web: TestClient,
):
    from mycelium import docs_store

    name = connect(web)
    target = product_settings.DestinationSettings(
        name="docs",
        owner="acme",
        repo="handbook",
        base_branch="main",
        path_template="docs/{slug}.md",
        binding=name,
    )
    configured = target.destination()
    docs = docs_store.connect(":memory:")
    docs_store.migrate(docs)
    document_id = docs_store.upsert_document(
        docs,
        slug="policy",
        title="Policy",
        body="First",
        guideline_set="kb-authoring",
        document_type="reference",
        statement_ids=[],
    )
    docs_store.record_delivery(
        docs,
        document_id,
        destination="docs",
        path="docs/policy.md",
        reference="https://github.com/acme/handbook/pull/1",
        content_revision="1" * 40,
        target=destinations.target_identity(configured),
        revision=1,
        binding=name,
    )
    product_settings.save(
        product_settings.SaveSettings(
            revision=0,
            settings=product_settings.DocumentationSettings(
                destinations=(
                    target.model_copy(
                        update={
                            "base_branch": "other",
                            "path_template": "elsewhere/{slug}.md",
                        }
                    ),
                )
            ),
        ),
        ADMIN,
    )
    row = docs_store.get_document(docs, document_id)
    assert row is not None
    restored, binding = destinations.publishing_destination(row, "docs")
    assert binding == name
    assert restored.path_template == "docs/policy.md"
    assert github_destination.GitHubConfig.parse(restored).base_branch == "main"
    github_connections.disconnect(name)
    with pytest.raises(destinations.DestinationError, match="disconnected"):
        github_destination.read(restored, "docs/policy.md", document_id, "policy")
    docs.close()
