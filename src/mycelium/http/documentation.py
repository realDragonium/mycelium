"""Generated documentation: requesting runs, revising documents, and delivering
them to a destination.

Reads are open to any authenticated caller; anything that starts a run or
delivers needs a real writer. The shared conflict handler answers 409 for a stale
`expected_revision`.
Each route calls the function the matching MCP tool calls (`server.documentation`
and `server.documentation_work`).
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import (
    docs_store,
    document_maintenance,
    documentation_planning,
    server,
)
from ..docgen import publication, site
from ..docgen.render import LinkTarget, render_markdown
from ..docgen.schema import STORED_FLOWS, STORED_LINKS
from ..request_timing import TimedRoute
from ..server import documentation_work as work
from .access import _enforce_role, _require_principal

router = APIRouter(route_class=TimedRoute)


class DocumentationRequestBody(BaseModel):
    prompt: str
    guideline_set: str | None = None
    document_type: str | None = None
    provider: Literal["claude", "openai", "agent"] | None = None
    anchor_entity_id: str | None = None


@router.get("/api/documentation/options")
def documentation_options(request: Request) -> dict[str, object]:
    return work.documentation_options(_require_principal(request))


@router.post("/api/documentation/runs")
def request_documentation_http(
    body: DocumentationRequestBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return server.request_documentation(**body.model_dump())


@router.get("/api/documentation/runs")
def documentation_runs_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_documentation_runs()


@router.get("/api/documentation/runs/{run_id}")
def documentation_run_http(run_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    try:
        return server.get_documentation_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class RetryRunBody(BaseModel):
    with_review_notes: bool = False


@router.post("/api/documentation/runs/{run_id}/retry")
def retry_documentation_run_http(
    run_id: str, body: RetryRunBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    try:
        return server.retry_documentation_run(
            run_id, with_review_notes=body.with_review_notes
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class DocumentRevisionBody(BaseModel):
    prompt: str = ""
    expected_revision: int = PydField(ge=1, strict=True)
    provider: Literal["claude", "openai", "agent"] | None = None
    update_sources: bool = False


class DocumentDeliveryBody(BaseModel):
    destination: str
    expected_revision: int = PydField(ge=1, strict=True)


def _document_preview(document: dict[str, object]) -> dict[str, object]:
    """The document with its body as HTML, drawn from the links and flows
    stored with the shown revision."""
    body = document.get("body")
    if not isinstance(body, str):
        return {**document, "body_html": ""}
    flows = STORED_FLOWS.validate_python(document.get("flows") or [])
    return {
        **document,
        "body_html": render_markdown(
            body,
            links=_link_targets(document),
            flows={flow.name: flow for flow in flows},
        ),
    }


def _link_targets(document: dict[str, object]) -> dict[str, LinkTarget]:
    """Where each concept link of a stored document leads in the web app: the
    view of the document anchored on that concept in the same profile. A link
    to the document's own concept, or to a concept without one, has none."""
    links = STORED_LINKS.validate_python(document.get("concept_links") or [])
    if not links or not document.get("guideline_set"):
        return {}
    conn = server._drafts_db()
    row = docs_store.get_document(
        conn, str(document.get("document_id") or document.get("id"))
    )
    own = None if row is None else row["anchor_entity_id"]
    pages = docs_store.linked_documents(
        conn,
        str(document["guideline_set"]),
        str(document["document_type"]),
        [link.entity_id for link in links if link.entity_id != own],
    )
    return {
        link.name: LinkTarget(
            href=f"#/documentation?document={quote(pages[link.entity_id])}"
        )
        for link in links
        if link.entity_id in pages
    }


@router.get("/api/documentation/documents")
def generated_documents_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_generated_documents()


@router.get("/api/documentation/destinations")
def documentation_destinations_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_documentation_destinations()


@router.get("/api/documentation/documents/{document_id}")
def generated_document_http(document_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    try:
        return _document_preview(server.get_generated_document(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/documentation/documents/{document_id}/revisions")
def document_revisions_http(document_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_document_revisions(document_id)


@router.get("/api/documentation/documents/{document_id}/revisions/{revision}")
def document_revision_http(
    document_id: str, revision: int, request: Request
) -> dict[str, object]:
    _require_principal(request)
    try:
        return _document_preview(server.get_document_revision(document_id, revision))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/documentation/documents/{document_id}/revisions/{revision}/diff")
def document_revision_diff_http(
    document_id: str, revision: int, request: Request
) -> work.RevisionDiff:
    """A revision's body against the one it was revised from."""
    _require_principal(request)
    try:
        return work.revision_diff(document_id, revision)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/documentation/maintenance")
def document_maintenance_http(request: Request) -> document_maintenance.Feed:
    """Documents kept up to date by their profile's maintenance policy."""
    _require_principal(request)
    return document_maintenance.feed(server._drafts_db())


@router.post("/api/documentation/documents/{document_id}/revisions")
def revise_document_http(
    document_id: str, body: DocumentRevisionBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return server.revise_document(document_id, **body.model_dump())


@router.post("/api/documentation/documents/{document_id}/delivery")
def deliver_document_http(
    document_id: str, body: DocumentDeliveryBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return publication.publish(server._drafts_db(), document_id, **body.model_dump())


# --- documentation planning ------------------------------------------------------


@router.get("/api/documentation/sites/{guideline_set}")
def documentation_site_http(
    guideline_set: str,
    request: Request,
    title: str | None = None,
    feedback_url: str | None = None,
) -> Response:
    """The profile's documents as a static site in one zip. For admins only:
    the site holds everything the profile's audience may see, whoever asks."""
    _enforce_role(request, "admin", real_role=True)
    try:
        data = work.site_archive(guideline_set, title=title, feedback_url=feedback_url)
    except site.SiteRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(guideline_set)}-site.zip",
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/documentation/plans/{guideline_set}")
def documentation_plan_http(
    guideline_set: str, request: Request
) -> documentation_planning.PlanView:
    _require_principal(request)
    return documentation_planning.view(guideline_set)


@router.post("/api/documentation/plans/{guideline_set}")
def plan_documentation_http(
    guideline_set: str, request: Request
) -> documentation_planning.PlanView:
    _enforce_role(request, "writer", real_role=True)
    documentation_planning.start(
        guideline_set, created_by=_require_principal(request).id
    )
    return documentation_planning.view(guideline_set)


class PlanItemsBody(BaseModel):
    item_ids: list[str] = PydField(min_length=1)


@router.post("/api/documentation/plan-items/approve")
def approve_plan_items_http(
    body: PlanItemsBody, request: Request
) -> list[work.ApprovedItem]:
    """Approve several items; each starts its own run, and one that cannot
    start reports why without stopping the rest."""
    _enforce_role(request, "writer", real_role=True)
    return work.approve_items(body.item_ids, _require_principal(request).id)


@router.post("/api/documentation/plan-items/{item_id}/retry")
def retry_plan_item_http(
    item_id: str, body: RetryRunBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    try:
        return documentation_planning.retry(
            item_id, with_review_notes=body.with_review_notes
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/documentation/plan-items/{item_id}/dismiss")
def dismiss_plan_item_http(item_id: str, request: Request) -> dict[str, bool]:
    _enforce_role(request, "writer", real_role=True)
    try:
        documentation_planning.dismiss_item(
            item_id, decided_by=_require_principal(request).id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"dismissed": True}


@router.post(
    "/api/documentation/plans/{guideline_set}/uncovered/{statement_id}/dismiss"
)
def dismiss_uncovered_statement_http(
    guideline_set: str, statement_id: str, request: Request
) -> dict[str, bool]:
    _enforce_role(request, "writer", real_role=True)
    try:
        documentation_planning.dismiss_statement(
            guideline_set, statement_id, decided_by=_require_principal(request).id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"dismissed": True}


@router.post(
    "/api/documentation/plans/{guideline_set}/uncovered/{statement_id}/restore"
)
def restore_uncovered_statement_http(
    guideline_set: str, statement_id: str, request: Request
) -> dict[str, bool]:
    _enforce_role(request, "writer", real_role=True)
    try:
        documentation_planning.restore_statement(guideline_set, statement_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"restored": True}


class StaleDismissalBody(BaseModel):
    revision: int = PydField(ge=1, strict=True)


@router.post("/api/documentation/plans/{guideline_set}/stale/{document_id}/dismiss")
def dismiss_stale_document_http(
    guideline_set: str, document_id: str, body: StaleDismissalBody, request: Request
) -> dict[str, bool]:
    _enforce_role(request, "writer", real_role=True)
    try:
        documentation_planning.dismiss_stale(
            guideline_set,
            document_id,
            body.revision,
            decided_by=_require_principal(request).id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"dismissed": True}
