"""Generated documentation: requesting runs, editing and revising documents, and
delivering them to a destination.

Reads are open to any authenticated caller; anything that starts a run or
delivers needs a real writer. The shared conflict handler answers 409 for a stale
`expected_revision` or edits on both sides, preserving the latter's response code.
Each route calls the function the matching MCP tool calls (`server.documentation`
and `server.documentation_work`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import (
    document_maintenance,
    documentation_planning,
    media,
    server,
)
from ..docgen import publication
from ..docgen.schema import ManualDocument
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


class DocumentEditBody(ManualDocument):
    provider: Literal["claude", "openai"] | None = None


class SavedDocumentEditBody(DocumentEditBody):
    expected_revision: int = PydField(ge=1, strict=True)


@router.post("/api/documentation/preview")
def preview_document_edit(body: ManualDocument, request: Request) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return _document_preview({"body": body.body})


@router.post("/api/documentation/documents/{document_id}/edits")
def edit_saved_document_http(
    document_id: str, body: SavedDocumentEditBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return work.edit_saved(
        document_id,
        body.expected_revision,
        ManualDocument(title=body.title, body=body.body),
        body.provider,
        _require_principal(request).id,
    )


@router.post("/api/documentation/runs/{run_id}/edits")
def edit_document_draft_http(
    run_id: str, body: DocumentEditBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return work.edit_draft(
        run_id,
        ManualDocument(title=body.title, body=body.body),
        body.provider,
        _require_principal(request).id,
    )


class DocumentRevisionBody(BaseModel):
    prompt: str = ""
    expected_revision: int = PydField(ge=1, strict=True)
    provider: Literal["claude", "openai", "agent"] | None = None
    start_from_destination: bool = False
    update_sources: bool = False


class DocumentDeliveryBody(BaseModel):
    destination: str
    expected_revision: int = PydField(ge=1, strict=True)


def _render_markdown(body: str) -> str:
    """Safe HTML for a document body. The only images are media references,
    served by Mycelium under the reader's own audience check; any other
    image becomes its alt text, so a document cannot load outside content."""
    from markdown_it import MarkdownIt
    from markdown_it.common.utils import escapeHtml
    from markdown_it.renderer import RendererHTML
    from markdown_it.token import Token
    from markdown_it.utils import EnvType, OptionsDict

    renderer = MarkdownIt("js-default")

    def image(
        self: RendererHTML,
        tokens: Sequence[Token],
        idx: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[idx]
        alt = escapeHtml(self.renderInlineAsText(token.children or [], options, env))
        found = media.REFERENCE.fullmatch(str(token.attrGet("src") or ""))
        if found is None:
            return alt
        return (
            f'<img src="{escapeHtml(media.content_url(found.group(1)))}" '
            f'alt="{alt}" loading="lazy">'
        )

    renderer.add_render_rule("image", image)
    html: str = renderer.render(body)
    return html


def _document_preview(document: dict[str, object]) -> dict[str, object]:
    body = document.get("body")
    return {
        **document,
        "body_html": _render_markdown(body) if isinstance(body, str) else "",
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
