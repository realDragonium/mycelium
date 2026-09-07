from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, docs_store, server
from mycelium.http import AuthMiddleware, app


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    async def resolve(*_):
        return auth.Principal(id="fixture", name="Fixture", role="writer", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    with closing(docs_store.connect(tmp_path / "drafts.db")) as conn:
        docs_store.migrate(conn)
        monkeypatch.setattr(server, "_drafts_db", lambda: conn)
        document = docs_store.upsert_document(
            conn,
            slug="page",
            title="Page",
            body="# Welcome\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![image](https://example.com/track.png)",
        )
        yield TestClient(app), conn, document


def test_library_renders_safe_markdown_and_reads_historical_body(workspace):
    client, conn, document = workspace
    first = docs_store.get_document(conn, document)["body"]
    docs_store.upsert_document(
        conn,
        slug="page",
        title="Page",
        body="Second",
        updates=document,
        replacing=docs_store.body_digest(first),
        expected_revision=1,
    )
    assert (
        client.get("/api/documentation/documents").json()["documents"][0][
            "current_revision"
        ]
        == 2
    )
    detail = client.get(f"/api/documentation/documents/{document}/revisions/1")
    assert detail.status_code == 200
    html = detail.json()["body_html"]
    assert "<h1>Welcome</h1>" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert "<img" not in html
    assert detail.json()["body"] == first
    history = client.get(f"/api/documentation/documents/{document}/revisions").json()
    assert [row["revision"] for row in history["revisions"]] == [2, 1]
    assert (
        client.get(f"/api/documentation/documents/{document}/revisions/99").status_code
        == 404
    )


def test_ui_creation_never_implicitly_replaces_an_existing_document(
    workspace, monkeypatch
):
    client, _, _ = workspace
    requests = []

    def request(**kwargs):
        requests.append(kwargs)
        return {"id": "run"}

    monkeypatch.setattr(server, "request_documentation", request)
    assert (
        client.post("/api/documentation/runs", json={"prompt": "New page"}).status_code
        == 200
    )
    assert requests[0]["match_existing"] is False


@pytest.mark.parametrize("action", ["revisions", "delivery"])
def test_revision_actions_require_real_writer_and_surface_conflicts(
    workspace, monkeypatch, action
):
    client, _, document = workspace
    payload = {
        "expected_revision": 1,
        **({"prompt": "Improve"} if action == "revisions" else {"destination": "docs"}),
    }
    calls = []

    def conflict(*args, **kwargs):
        calls.append(kwargs)
        raise docs_store.RevisionConflict(
            "Document changed. Reload it before continuing."
        )

    monkeypatch.setattr(
        server,
        "revise_document" if action == "revisions" else "deliver_document",
        conflict,
    )
    assert (
        client.post(
            f"/api/documentation/documents/{document}/{action}", json=payload
        ).status_code
        == 409
    )
    assert calls[0]["expected_revision"] == 1

    async def reader(*_):
        return auth.Principal(id="reader", name="Reader", role="reader", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", reader)
    assert (
        client.post(
            f"/api/documentation/documents/{document}/{action}", json=payload
        ).status_code
        == 403
    )
    assert len(calls) == 1
    assert client.get(f"/api/documentation/documents/{document}").status_code == 200


def test_delivery_requires_explicit_numeric_revision(workspace):
    client, _, document = workspace
    url = f"/api/documentation/documents/{document}/delivery"
    for revision in (None, True, "1", 0):
        assert (
            client.post(
                url, json={"destination": "docs", "expected_revision": revision}
            ).status_code
            == 422
        )
