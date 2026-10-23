"""Generated documentation: requesting runs, editing and revising documents, and
delivering them to a destination.

Reads are open to any authenticated caller; anything that starts a run or
delivers needs a real writer. A stale `expected_revision` answers 409.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import auth, server
from ..docgen.publication import BothSidesEdited
from ..docgen.schema import ManualDocument
from .access import _enforce_role, _require_principal

router = APIRouter()


class DocumentationRequestBody(BaseModel):
    prompt: str
    guideline_set: str | None = None
    document_type: str | None = None
    provider: Literal["claude", "openai"] | None = None
    anchor_entity_id: str | None = None


@router.get("/api/documentation/options")
def documentation_options(request: Request) -> dict[str, object]:
    principal = _require_principal(request)
    from .. import guidelines, prompt_store
    from ..docgen.config import DocgenConfig

    return {
        **server.list_documentation_models(),
        "can_generate": auth.principal_has_real_role(principal, "writer"),
        "guideline_sets": guidelines.catalogue(prompt_store.connection()),
        "max_prompt_chars": DocgenConfig.from_env().max_prompt_chars,
    }


@router.post("/api/documentation/runs")
def request_documentation_http(
    body: DocumentationRequestBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return server.request_documentation(**body.model_dump(), match_existing=False)


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
    from .. import docs_store, document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    try:
        run_id = document_edits.start_document_edit(
            server._drafts_db(),
            document_id,
            body.expected_revision,
            ManualDocument(title=body.title, body=body.body),
            created_by=principal.id,
            provider=body.provider,
        )
    except docs_store.RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return server.get_documentation_run(run_id)


@router.post("/api/documentation/runs/{run_id}/edits")
def edit_document_draft_http(
    run_id: str, body: DocumentEditBody, request: Request
) -> dict[str, object]:
    from .. import docs_store, document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    try:
        new_run_id = document_edits.start_draft_edit(
            server._drafts_db(),
            run_id,
            ManualDocument(title=body.title, body=body.body),
            created_by=principal.id,
            provider=body.provider,
        )
    except docs_store.RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return server.get_documentation_run(new_run_id)


class DocumentRevisionBody(BaseModel):
    prompt: str
    expected_revision: int = PydField(ge=1, strict=True)
    provider: Literal["claude", "openai"] | None = None
    start_from_destination: bool = False


class DocumentDeliveryBody(BaseModel):
    destination: str
    expected_revision: int = PydField(ge=1, strict=True)


def _document_preview(document: dict[str, object]) -> dict[str, object]:
    from markdown_it import MarkdownIt

    body = document.get("body")
    return {
        **document,
        "body_html": MarkdownIt("js-default").disable("image").render(body)
        if isinstance(body, str)
        else "",
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


async def _both_sides_edited_handler(
    request: Request, exc: BothSidesEdited
) -> JSONResponse:
    """A conflict the caller resolves by choosing a side, so the client gets a
    code to offer `start_from_destination` on rather than a message to parse."""
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "code": "both_sides_edited"}
    )


@router.post("/api/documentation/documents/{document_id}/revisions")
def revise_document_http(
    document_id: str, body: DocumentRevisionBody, request: Request
) -> dict[str, object]:
    from ..docs_store import RevisionConflict

    _enforce_role(request, "writer", real_role=True)
    try:
        return server.revise_document(document_id, **body.model_dump())
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/documentation/documents/{document_id}/delivery")
def deliver_document_http(
    document_id: str, body: DocumentDeliveryBody, request: Request
) -> dict[str, object]:
    from ..docs_store import RevisionConflict

    _enforce_role(request, "writer", real_role=True)
    try:
        return server.deliver_document(document_id, **body.model_dump())
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
