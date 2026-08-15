"""The mounted `/mcp` endpoint answers both MCP protocol revisions.

A 2025-era client opens with an `initialize` handshake and carries the
returned `Mcp-Session-Id` on every later request. A 2026-07-28 client sends
one self-describing POST — no handshake, no session header; the protocol
version and client identity ride in `params._meta`, and the method (plus the
tool name, for name-bearing methods) is mirrored into routing headers so a
gateway can route without parsing the body. Both shapes reach the same tools,
and the role filter applies to both.

This is the compatibility guarantee that lets existing users keep working
after the server adopts the stateless revision, so it is asserted on the wire
rather than assumed.

Unlike the rest of the suite (see `conftest`), these tests need the MCP
session manager actually running. `StreamableHTTPSessionManager.run()` may
only be called once per instance, so the whole module shares ONE client
through a module-scoped fixture — a second `TestClient` lifespan here would
raise on entry.
"""

import json

import pytest
from fastapi.testclient import TestClient
from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
    NAME_BEARING_METHODS,
)
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    HEADER_MISMATCH,
    LATEST_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)

from mycelium import auth, auth_store, server, store

# Both revisions negotiate content type through Accept; the transport wants to
# know a client can take either a JSON body or an SSE stream.
_ACCEPT = {"Accept": "application/json, text/event-stream"}

# A 2025-era handshake. The exact version matters less than that it is a
# handshake at all — this is the shape the endpoint must keep answering.
_LEGACY_PROTOCOL_VERSION = "2025-06-18"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MYCELIUM_DATA_DIR", str(tmp_path_factory.mktemp("mcp-eras")))
        # Auth on, so the role filter runs against a principal the middleware
        # resolved from a real bearer token. With auth off every caller is the
        # synthetic local-admin and the filter has nothing to narrow.
        mp.setenv("MYCELIUM_AUTH", "on")
        mp.setenv("MYCELIUM_SESSION_SECRET", "era-test-secret")
        # The one place in the suite that wants the real JSON-RPC endpoint.
        mp.setenv("MYCELIUM_DISABLE_MCP_HTTP", "0")
        store.reset_substrate()
        auth_store.reset()
        server._ctx = None
        from mycelium import embed

        mp.setattr(embed, "embed", lambda t: [0.0] * 768)
        from mycelium.http import app

        # TestClient's default `testserver` host is rejected by the transport's
        # DNS-rebinding protection, which allows `127.0.0.1:*` unless
        # MYCELIUM_ALLOWED_HOSTS names the deployment's real host.
        with TestClient(app, base_url="http://127.0.0.1:8000") as c:
            yield c


@pytest.fixture(scope="module")
def bearer(client):
    """One admin and one reader bearer token, minted against the live app.

    Both writes commit in a single transaction so the request thread — which
    resolves bearers on its own connection — can see them.
    """
    conn = server._auth_db()
    tokens = {}
    with store.transaction(conn):
        for role in ("admin", "reader"):
            uid = auth.create_user(
                conn,
                name=role.title(),
                role=role,
                type="human",
                email=f"{role}@example.com",
            )
            raw, _ = auth.issue_token(conn, user_id=uid, name="era-test", scope=role)
            tokens[role] = f"Bearer {raw}"
    return tokens


def _parse(response):
    """Read one JSON-RPC message out of either a JSON body or an SSE stream.

    Which framing comes back is the transport's choice and differs between the
    eras; the assertions here are about protocol content, not framing.
    """
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
        raise AssertionError(f"no data frame in SSE body: {response.text!r}")
    return response.json()


def _modern(client, method: str, *, token: str, params=None, request_id: int = 1):
    """Send a self-describing 2026-07-28 request.

    Everything the handshake used to establish once — protocol version, client
    identity, capabilities — travels inline on every request. The method and
    tool name are mirrored into routing headers, which the revision requires to
    agree with the body: a proxy that rewrites one and not the other gets a
    -32020 rather than silently dispatching the wrong thing.
    """
    body = dict(params or {})
    body["_meta"] = {
        PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION,
        CLIENT_INFO_META_KEY: {"name": "era-test", "version": "1.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    headers = {
        **_ACCEPT,
        "Authorization": token,
        MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION,
        MCP_METHOD_HEADER: method,
    }
    if name_param := NAME_BEARING_METHODS.get(method):
        headers[MCP_NAME_HEADER] = body[name_param]
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": body},
    )


def _legacy_session(client, *, token: str) -> dict[str, str]:
    """Complete a 2025-era handshake and return headers carrying its session."""
    auth_headers = {**_ACCEPT, "Authorization": token}
    init = client.post(
        "/mcp",
        headers=auth_headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _LEGACY_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "era-test-legacy", "version": "1.0"},
            },
        },
    )
    assert init.status_code == 200, init.text
    session_id = init.headers.get("mcp-session-id")
    assert session_id, "legacy handshake must still issue a session id"

    headers = {**auth_headers, "Mcp-Session-Id": session_id}
    client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    return headers


def test_modern_client_lists_tools_without_a_handshake(client, bearer):
    r = _modern(client, "tools/list", token=bearer["admin"])

    assert r.status_code == 200, r.text
    # The header the 2026-07-28 revision removes. Its absence is the point:
    # nothing ties this request to a worker, so any replica can serve it.
    assert "mcp-session-id" not in r.headers

    message = _parse(r)
    assert "error" not in message, message
    assert "list_entities" in {t["name"] for t in message["result"]["tools"]}


def test_legacy_client_still_gets_a_session_and_can_call_tools(client, bearer):
    """The compatibility guarantee: an existing client is not stranded."""
    session = _legacy_session(client, token=bearer["admin"])

    listed = client.post(
        "/mcp",
        headers=session,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    message = _parse(listed)
    assert "error" not in message, message
    assert "list_entities" in {t["name"] for t in message["result"]["tools"]}


def test_both_eras_reach_the_same_substrate(client, bearer):
    """Not just 'both connect' — a 2026 client's write is a 2025 client's read."""
    created = _modern(
        client,
        "tools/call",
        token=bearer["admin"],
        params={
            "name": "upsert_entity",
            "arguments": {
                "name": "Era Probe",
                "description": "written by a 2026-07-28 client",
            },
        },
    )
    assert created.status_code == 200, created.text
    assert "error" not in _parse(created), _parse(created)

    # `list_entities` rather than `search_entities`: search is embedding-backed
    # and the embedder is stubbed here, so a listing is what actually shows
    # the write crossed the era boundary.
    session = _legacy_session(client, token=bearer["admin"])
    found = client.post(
        "/mcp",
        headers=session,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_entities", "arguments": {}},
        },
    )
    assert found.status_code == 200, found.text
    message = _parse(found)
    assert "error" not in message, message
    assert "Era Probe" in json.dumps(message["result"])


def test_role_filter_applies_on_the_modern_path(client, bearer):
    """A reader must not see write tools on the new path.

    The filter reads the principal AuthMiddleware resolved for the request, so
    it is transport-agnostic by construction — but 'by construction' is exactly
    the kind of claim that quietly stops being true, and an authz gap on a
    freshly added path is the expensive kind.
    """
    r = _modern(client, "tools/list", token=bearer["reader"])

    assert r.status_code == 200, r.text
    names = {t["name"] for t in _parse(r)["result"]["tools"]}
    assert "list_entities" in names
    assert not any(n.startswith(("delete_", "merge_")) for n in names), names


def test_role_filter_applies_on_the_legacy_path(client, bearer):
    """And on the old one. The two eras reach the middleware through different
    connection plumbing, so covering only the modern path would let a
    regression in legacy principal propagation pass unnoticed.
    """
    session = _legacy_session(client, token=bearer["reader"])

    listed = client.post(
        "/mcp",
        headers=session,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    names = {t["name"] for t in _parse(listed)["result"]["tools"]}
    assert "list_entities" in names
    assert not any(n.startswith(("delete_", "merge_")) for n in names), names


def test_routing_headers_must_agree_with_the_body(client, bearer):
    """A modern request whose routing headers contradict its body is rejected.

    Pinned because the deployment notes tell operators their proxy must pass
    `Mcp-Method` / `Mcp-Name` through untouched. If this stopped being enforced,
    that advice would silently become optional — and a proxy rewriting one but
    not the other would dispatch something the caller didn't ask for.
    """
    body = {
        "_meta": {
            PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION,
            CLIENT_INFO_META_KEY: {"name": "era-test", "version": "1.0"},
            CLIENT_CAPABILITIES_META_KEY: {},
        }
    }
    r = client.post(
        "/mcp",
        headers={
            **_ACCEPT,
            "Authorization": bearer["admin"],
            MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION,
            MCP_METHOD_HEADER: "tools/list",  # disagrees with the body below
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": body},
    )

    assert r.status_code == 400, r.text
    assert _parse(r)["error"]["code"] == HEADER_MISMATCH
