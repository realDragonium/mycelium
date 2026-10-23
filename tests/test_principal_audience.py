"""A principal scoped to an audience reads only what that audience may see."""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, principal_audience, server, store
from mycelium.ask.substrate import InProcessSubstrate
from mycelium.http.authentication import _is_exempt
from mycelium.server import runtime

SECRET = "internal queue codenamed ZZQUILL"


def _sample(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_every_route_is_scoped_or_refused_to_a_scoped_principal():
    """The audit: every HTTP route is either one the allowlist scopes or one
    a scoped principal is refused, so a route added later is closed until
    someone decides otherwise."""
    from mycelium.http import create_app

    app = create_app()
    tools = {tool.__name__: tool for tool in server.TOOLS}
    reachable: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            path = _sample(route.path)
            if principal_audience.may_reach(method, path, exempt=_is_exempt(path)):
                reachable.add((method, route.path))

    tool_routes = {
        (method, route)
        for method, route in reachable
        if route.strip("/").replace("-", "_") in tools
    }
    assert {route.strip("/").replace("-", "_") for _m, route in tool_routes} == (
        principal_audience.TOOLS
    )
    assert reachable - tool_routes == principal_audience.ROUTES | {
        (method, route)
        for method, route in reachable
        if _is_exempt(_sample(route))
        or route in ("/", "/ui", "/cockpit", "/connect", "/cockpit/{rest:path}")
        or route.startswith("/auth/")
    }


def test_every_tool_is_scoped_or_refused():
    scoped = auth.Principal("u", "U", "reader", "service", audience_id="external")
    for tool in server.TOOLS:
        name = tool.__name__
        if name in principal_audience.TOOLS:
            assert tool._mycelium_required_role in ("asker", "reader")
            principal_audience.check_tool(scoped, name)
        else:
            with pytest.raises(principal_audience.Unavailable):
                principal_audience.check_tool(scoped, name)


def test_scoped_ask_is_offered_only_tools_the_boundary_scopes():
    offered = {spec.name for spec in InProcessSubstrate().tool_specs()}
    assert offered <= principal_audience.TOOLS
    assert principal_audience.TOOLS - offered == {
        "ask",
        "list_generated_documents",
        "get_generated_document",
    }


@pytest.fixture
def auth_db():
    conn = auth_store.connect(":memory:")
    auth_store.migrate(conn)
    yield conn
    conn.close()


def test_a_scoped_token_reads_as_its_audience_and_never_writes(auth_db):
    admin = auth.create_user(auth_db, name="A", role="admin", type="service")
    auth.create_user(auth_db, name="B", role="admin", type="service")
    raw, token_id = auth.issue_token(
        auth_db, user_id=admin, name="bot", scope="admin", audience_id="ext"
    )
    principal = auth.resolve_token(auth_db, raw)
    assert principal is not None
    assert (principal.role, principal.audience_id) == ("reader", "ext")

    auth.set_token_audience(auth_db, token_id, None)
    assert auth.resolve_token(auth_db, raw).role == "admin"

    auth.set_user_audience(auth_db, admin, "other")
    assert auth.resolve_token(auth_db, raw).audience_id == "other"


def test_a_scoped_principal_cannot_mint_its_way_out(auth_db):
    user = auth.create_user(auth_db, name="A", role="writer", type="service")
    scoped = auth.Principal(user, "A", "reader", "service", audience_id="ext")
    raw, _row = auth.mint_own_token(auth_db, principal=scoped, name="n", scope="writer")
    assert auth.resolve_token(auth_db, raw).audience_id == "ext"


def test_the_last_unscoped_admin_cannot_be_scoped(auth_db):
    admin = auth.create_user(auth_db, name="A", role="admin", type="human")
    with pytest.raises(ValueError):
        auth.set_user_audience(auth_db, admin, "ext")


def test_a_domain_blocked_user_is_refused_before_any_scope(auth_db, monkeypatch):
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "example.com")
    user = auth.create_user(
        auth_db, name="A", role="reader", type="human", email="a@elsewhere.test"
    )
    auth.set_user_audience(auth_db, user, "ext")
    raw, _ = auth.issue_token(auth_db, user_id=user, name="t", scope="reader")
    assert auth.resolve_token(auth_db, raw) is None
    assert auth.resolve_session_user(auth_db, user) is None


# --- through the running app, auth on -------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    store.reset_substrate()
    auth_store.reset()
    runtime._ctx = None
    from mycelium import embed

    # One vector for every text: unscoped search would rank every statement.
    monkeypatch.setattr(embed, "embed", lambda text: [1.0] + [0.0] * 767)
    from mycelium.http import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _bearer(role: str, audience_id: str | None = None) -> dict[str, str]:
    conn = runtime._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(
            conn, user_id=user, name="t", scope=role, audience_id=audience_id
        )
    return {"Authorization": f"Bearer {raw}"}


def _corpus(client: TestClient, admin: dict[str, str]) -> tuple[str, str, str]:
    def statement(text: str, links: list[dict[str, str]]) -> str:
        r = client.post(
            "/upsert-statement",
            headers=admin,
            json={
                "kind": "state",
                "text": text,
                "links": links,
                "allow_phrasing_violations": True,
            },
        )
        assert r.status_code == 200, r.text
        return str(r.json()["statement_id"])

    r = client.post(
        "/upsert-entity",
        headers=admin,
        json={"name": "workspace export", "description": f"Runs on the {SECRET}."},
    )
    entity = str(r.json()["entity_id"])
    hidden = statement(f"A workspace export runs on the {SECRET}.", [])
    public = statement(
        "A workspace export downloads as a CSV file.",
        [{"to_id": hidden, "link_type": "requires"}],
    )
    r = client.put(
        f"/api/statements/{public}/audiences",
        headers=admin,
        json={"audiences": ["external-technical"], "reason": "public"},
    )
    assert r.status_code == 200, r.text
    return public, hidden, entity


def test_an_external_token_never_sees_an_internal_statement(client):
    admin = _bearer("admin")
    public, hidden, entity = _corpus(client, admin)
    external = _bearer("admin", "external-technical")
    reads = [
        ("POST", "/search-statements", {"query": "workspace export", "depth": 2}),
        (
            "POST",
            "/search-statements",
            {"query": "workspace export", "decompose": True},
        ),
        ("POST", "/grep-statements", {"query": "ZZQUILL"}),
        ("POST", "/grep-statements", {"query": "workspace"}),
        ("POST", "/list-statements", {}),
        ("POST", "/get-entity", {"id": entity}),
        ("POST", "/list-entities", {}),
        ("POST", "/search-entities", {"query": "workspace export"}),
        ("POST", "/discover-facts", {"texts": ["workspace export"]}),
        (
            "POST",
            "/find-statement-connections",
            {"source": public, "target": "the internal queue"},
        ),
        (
            "POST",
            "/retrieve-context",
            {"query": "workspace export", "names": ["workspace export"]},
        ),
        ("POST", "/find-duplicates", {"threshold": 0.0}),
        ("POST", "/find-entity-duplicates", {"threshold": 0.0}),
        ("POST", "/get-mention-candidates", {"entity_id": entity}),
        ("GET", "/list-link-types", None),
        ("GET", "/list-statement-kinds", None),
        ("GET", "/list-entity-link-types", None),
        ("POST", "/list-link-type-aliases", {}),
        ("GET", "/api/data", None),
        ("GET", "/api/substrate-counts", None),
        ("GET", "/api/history", None),
        ("GET", "/api/documentation/documents", None),
    ]
    unscoped = client.post(
        "/search-statements", headers=admin, json={"query": "workspace export"}
    )
    assert "ZZQUILL" in unscoped.text

    for method, path, body in reads:
        r = client.request(method, path, headers=external, json=body)
        assert r.status_code in (200, 400), (path, r.text)
        assert "ZZQUILL" not in r.text, path
        assert hidden not in r.text, path
    got = client.post(
        "/get-statements", headers=external, json={"ids": [public, hidden]}
    ).json()
    assert [item["id"] for item in got["statements"]] == [public]
    assert got["missing"] == [hidden]

    def counts(headers: dict[str, str]) -> tuple[int, int]:
        n = client.get("/api/substrate-counts", headers=headers).json()
        return n["statements"], n["links"]

    assert counts(admin) == (2, 1)
    assert counts(external) == (1, 0)


def test_an_external_token_is_refused_writes_drafts_and_admin(client):
    admin = _bearer("admin")
    public, _hidden, _entity = _corpus(client, admin)
    external = _bearer("admin", "external-technical")
    refused = [
        ("POST", "/upsert-statement", {"kind": "state", "text": "x", "links": []}),
        ("POST", "/delete-statement", {"id": public}),
        ("POST", "/report-knowledge-gap", {"question": "q"}),
        ("POST", "/list-my-drafts", {}),
        ("POST", "/list-statements", {"draft_id": "drf_x"}),
        ("GET", "/api/admin/users", None),
        ("GET", "/api/drafts", None),
        ("GET", f"/api/statements/{public}/audiences", None),
        ("GET", "/api/knowledge-gaps", None),
        ("GET", "/api/documentation/runs", None),
    ]
    for method, path, body in refused:
        r = client.request(method, path, headers=external, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text)
    assert client.get("/api/me", headers=external).json()["audience"] == {
        "id": "external-technical",
        "name": "External technical",
        "scope": "external",
    }


def test_a_token_scoped_to_a_retired_audience_reads_nothing(client):
    external = _bearer("reader", "no-such-audience")
    r = client.post("/list-statements", headers=external, json={})
    assert r.status_code == 403
    assert client.get("/api/data", headers=external).status_code == 403


def test_scoped_ask_neither_reads_nor_cites_an_internal_statement(client, monkeypatch):
    from mycelium import ai

    admin = _bearer("admin")
    public, hidden, _entity = _corpus(client, admin)
    external = _bearer("admin", "external-technical")
    script = iter(
        [
            [
                ai.ToolUse(
                    id="g", name="grep_statements", input={"query": "workspace"}
                ),
                ai.ToolUse(
                    id="s", name="get_statements", input={"ids": [public, hidden]}
                ),
            ],
            [
                ai.ToolUse(
                    id="a",
                    name="submit_answer",
                    input={
                        "answer": "It downloads as a CSV file.",
                        "confidence": "high",
                        "interpretation": None,
                        "gaps": [],
                        "provenance": ["s1"],
                    },
                )
            ],
        ]
    )
    seen: list[str] = []

    def turn(task, config, *, client=None):
        seen.append(repr(task.messages))
        return ai.ModelResponse(
            content=next(script), usage=ai.Usage(), stop_reason="tool_use"
        )

    monkeypatch.setattr(ai, "turn", turn)
    r = client.post(
        "/ask",
        headers=external,
        json={
            "question": "How does an export download?",
            "depth": "quick",
            "verbose": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == [public]
    assert "ZZQUILL" not in r.text
    assert seen and not any("ZZQUILL" in messages for messages in seen)
