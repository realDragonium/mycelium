from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, docs_store, drafts_store, server
from mycelium.docgen import publication
from mycelium.docgen.publication import BothSidesEdited
from mycelium.http import create_app
from mycelium.http.authentication import AuthMiddleware
from settings_helpers import assume_configured_models


@pytest.fixture(autouse=True)
def _anthropic_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    assume_configured_models(monkeypatch)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    async def resolve(*_):
        return auth.Principal(id="fixture", name="Fixture", role="writer", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    with closing(docs_store.connect(tmp_path / "drafts.db")) as conn:
        docs_store.migrate(conn)
        monkeypatch.setattr(drafts_store, "connection", lambda: conn)
        document = docs_store.upsert_document(
            conn,
            slug="page",
            title="Page",
            body="# Welcome\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![image](https://example.com/track.png)",
        )
        yield TestClient(create_app()), conn, document


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


@pytest.mark.parametrize("action", ["revisions", "delivery"])
@pytest.mark.parametrize(
    ("error", "status", "extra"),
    [
        (docs_store.RevisionConflict, 409, {}),
        (BothSidesEdited, 409, {"code": "both_sides_edited"}),
        (ValueError, 400, {}),
    ],
)
def test_revision_actions_require_real_writer_and_surface_errors(
    workspace, monkeypatch, action, error, status, extra
):
    client, _, document = workspace
    payload = {
        "expected_revision": 1,
        **({"prompt": "Improve"} if action == "revisions" else {"destination": "docs"}),
    }
    calls = []

    def conflict(*args, **kwargs):
        calls.append(kwargs)
        raise error("Document changed. Reload it before continuing.")

    if action == "revisions":
        monkeypatch.setattr(server, "revise_document", conflict)
    else:
        monkeypatch.setattr(publication, "publish", conflict)
    response = client.post(
        f"/api/documentation/documents/{document}/{action}", json=payload
    )
    assert response.status_code == status
    assert response.json() == {
        "detail": "Document changed. Reload it before continuing.",
        **extra,
    }
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


def test_generated_tool_route_surfaces_revision_conflict(workspace):
    client, _, document = workspace
    response = client.post(
        "/revise-document",
        json={
            "document_id": document,
            "expected_revision": 2,
            "prompt": "Explain workspace exports.",
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "The document has changed. Reload it before continuing."
    }


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


def test_manual_preview_uses_safe_renderer(workspace):
    client, conn, document = workspace
    body = docs_store.get_document(conn, document)["body"]
    response = client.post(
        "/api/documentation/preview", json={"title": "Title", "body": body}
    )
    assert response.status_code == 200
    html = response.json()["body_html"]
    assert "<h1>Welcome</h1>" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert "<img" not in html


def test_only_media_references_render_as_images(workspace):
    client, _conn, _document = workspace
    body = (
        "![The export dialog](media:med_000000000001)\n\n"
        "![tracking pixel](https://example.test/pixel.png)\n"
    )
    response = client.post(
        "/api/documentation/preview", json={"title": "Title", "body": body}
    )
    html = response.json()["body_html"]
    assert (
        '<img src="/api/media/med_000000000001/content" alt="The export dialog"' in html
    )
    assert "example.test" not in html and "tracking pixel" in html


@pytest.mark.parametrize("path", ["preview", "documents/page/edits", "runs/run/edits"])
def test_manual_edit_requires_writer(workspace, monkeypatch, path):
    client, _, _ = workspace

    async def reader(*_):
        return auth.Principal(id="reader", name="Reader", role="reader", type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", reader)
    payload = {"title": "Title", "body": "Body"}
    if path.startswith("documents/"):
        payload["expected_revision"] = 1
    assert client.post("/api/documentation/" + path, json=payload).status_code == 403


def test_manual_edit_validates_input_and_conflict_before_start(workspace):
    client, _, document = workspace
    url = f"/api/documentation/documents/{document}/edits"
    for changes in (
        {"title": " "},
        {"body": "\n "},
        {"body": "x" * 200001},
        {"expected_revision": True},
        {"expected_revision": "1"},
    ):
        payload = {"title": "Title", "body": "Body", "expected_revision": 1, **changes}
        assert client.post(url, json=payload).status_code == 422
    assert (
        client.post(
            url, json={"title": "Title", "body": "Body", "expected_revision": 2}
        ).status_code
        == 409
    )


def test_manual_edit_http_preserves_exact_text_and_author(workspace, monkeypatch):
    from mycelium import doc_runs

    client, conn, document = workspace
    captured = {}

    def start(**kwargs):
        captured.update(kwargs)
        return docs_store.create_run(
            conn,
            prompt=kwargs["prompt"],
            guideline_set=None,
            document_type=None,
            created_by=kwargs["created_by"],
        )

    monkeypatch.setattr(doc_runs, "start_run", start)
    body = "---\ntitle: Title\n---\n\n  Exact body\n"
    result = client.post(
        f"/api/documentation/documents/{document}/edits",
        json={"title": "Title", "body": body, "expected_revision": 1},
    )
    assert result.status_code == 200, result.text
    assert captured["manual_document"].body == body
    assert captured["created_by"] == "fixture"
    assert captured["expected_revision"] == 1
    assert captured["target_document_id"] == document


def test_failed_draft_recovery_uses_original_profile(workspace, monkeypatch):
    from mycelium import doc_runs

    client, conn, _ = workspace
    source = docs_store.create_run(
        conn,
        prompt="Original request",
        guideline_set="internal",
        document_type="guide",
        created_by="first",
    )
    docs_store.finish_run(
        conn,
        source,
        outcome="nothing_written",
        draft_title="Draft",
        draft_body="Original",
    )
    captured = {}

    def start(**kwargs):
        captured.update(kwargs)
        return docs_store.create_run(
            conn,
            prompt=kwargs["prompt"],
            guideline_set=kwargs["guideline_set"],
            document_type=kwargs["document_type"],
            created_by=kwargs["created_by"],
        )

    monkeypatch.setattr(doc_runs, "start_run", start)
    result = client.post(
        f"/api/documentation/runs/{source}/edits",
        json={"title": "Edited", "body": "Exact\n"},
    )
    assert result.status_code == 200, result.text
    assert captured["prompt"] == "Original request"
    assert (captured["guideline_set"], captured["document_type"]) == (
        "internal",
        "guide",
    )
    assert captured["target_document_id"] is None
    assert captured["manual_document"].body == "Exact\n"


def test_recovery_rejects_running_draft_and_stale_revision(workspace):
    client, conn, document = workspace
    source = docs_store.create_run(
        conn,
        prompt="Original",
        guideline_set=None,
        document_type=None,
        created_by=None,
        target_document_id=document,
        target_revision=1,
    )
    payload = {"title": "Edited", "body": "Exact"}
    url = f"/api/documentation/runs/{source}/edits"
    assert client.post(url, json=payload).status_code == 400
    docs_store.finish_run(
        conn,
        source,
        outcome="nothing_written",
        draft_title="Draft",
        draft_body="Original",
    )
    original = docs_store.get_document(conn, document)["body"]
    docs_store.upsert_document(
        conn,
        slug="page",
        title="Newer",
        body="Newer body",
        updates=document,
        replacing=docs_store.body_digest(original),
        expected_revision=1,
    )
    assert client.post(url, json=payload).status_code == 409
    assert docs_store.get_document(conn, document)["body"] == "Newer body"
