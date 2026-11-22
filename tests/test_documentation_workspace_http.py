from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, docs_store, drafts_store, server
from mycelium.docgen import publication
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


def test_a_document_renders_its_stored_links_and_flows(workspace):
    from mycelium.docgen import flows
    from mycelium.docgen.schema import StoredFlow

    client, conn, _document = workspace

    class Chain:
        def statement(self, statement_id):
            return flows.FlowStatement("event", "The export is requested.")

        def links(self, statement_id):
            return []

    drawing = flows.draw_flow(Chain(), "stm_requested")
    assert drawing is not None
    flow = StoredFlow(
        name="export-steps",
        title="Export steps",
        start="stm_requested",
        drawing=drawing,
    )

    def anchored(slug: str, template: str, concept: str, **extra) -> str:
        return docs_store.upsert_document(
            conn,
            slug=slug,
            title=slug,
            body=extra.pop("body", "Body."),
            guideline_set="developer-reference",
            document_type=template,
            anchor_entity_id=concept,
            **extra,
        )

    how_to = anchored("invoice-how-to", "how-to", "ent_invoice")
    entity_page = anchored("invoice", "entity-page", "ent_invoice")
    reference = anchored("workspace-reference", "reference", "ent_workspace")
    anchored("sso-elsewhere", "entity-page", "ent_sso")
    conn.execute(
        "UPDATE generated_documents SET guideline_set = 'support' "
        "WHERE slug = 'sso-elsewhere'"
    )
    conn.commit()
    export = anchored(
        "export",
        "entity-page",
        "ent_export",
        body=(
            "An [[Export]] holds each [[invoice|bill]] of a [[Workspace]], "
            "behind [[SSO]] and [[Ledgr]].\n\n```flow\nexport-steps\n```\n"
        ),
        concept_links=[
            {"name": "Export", "entity_id": "ent_export"},
            {"name": "invoice", "entity_id": "ent_invoice"},
            {"name": "Workspace", "entity_id": "ent_workspace"},
            {"name": "SSO", "entity_id": "ent_sso"},
        ],
        flows=[flow.model_dump(mode="json")],
    )

    shown = client.get(f"/api/documentation/documents/{export}").json()

    html = shown["body_html"]
    # Same template first, else the template that comes first by name; no page
    # in this profile, the document's own concept and no match stay text.
    assert (
        f'<p>An Export holds each <a class="concept-link" '
        f'href="#/documentation?document={entity_page}">bill</a> of a '
        f'<a class="concept-link" href="#/documentation?document={reference}">'
        "Workspace</a>, behind SSO and Ledgr.</p>"
    ) in html
    assert how_to not in html
    assert "<figcaption>Export steps</figcaption>" in html
    assert '<span class="flow-statement">The export is requested.</span>' in html
    assert "#source-" not in html
    assert shown["flows"][0]["title"] == "Export steps"
    revision = client.get(f"/api/documentation/documents/{export}/revisions/1").json()
    assert revision["body_html"] == html


@pytest.mark.parametrize("action", ["revisions", "delivery"])
@pytest.mark.parametrize(
    ("error", "status"),
    [(docs_store.RevisionConflict, 409), (ValueError, 400)],
)
def test_revision_actions_require_real_writer_and_surface_errors(
    workspace, monkeypatch, action, error, status
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
        "detail": "Document changed. Reload it before continuing."
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
