"""Generated documentation: requesting runs, editing and revising documents, and
delivering them to a destination.

Reads are open to any authenticated caller; anything that starts a run or
delivers needs a real writer. The shared conflict handler answers 409 for a stale
`expected_revision` or edits on both sides, preserving the latter's response code.
"""

from __future__ import annotations

import difflib
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import (
    auth,
    document_maintenance,
    documentation_planning,
    product_settings,
    server,
)
from ..docgen.schema import ManualDocument
from ..request_timing import TimedRoute
from .access import _enforce_role, _require_principal

router = APIRouter(route_class=TimedRoute)


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
        "profile_audiences": _profile_audiences(),
        "max_prompt_chars": DocgenConfig.from_env().max_prompt_chars,
    }


def _profile_audiences() -> dict[str, dict[str, str] | None]:
    """Which audience each profile writes for, so the generate form can say."""
    from .. import documentation_profiles

    snapshot = documentation_profiles.capture()
    return {
        profile.name: (
            {"id": audience.id, "name": audience.name, "scope": audience.scope}
            if (audience := snapshot.audience(profile.name)) is not None
            else None
        )
        for profile in snapshot.profiles
    }


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
    from .. import document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    run_id = document_edits.start_document_edit(
        server._drafts_db(),
        document_id,
        body.expected_revision,
        ManualDocument(title=body.title, body=body.body),
        created_by=principal.id,
        provider=body.provider,
    )
    return server.get_documentation_run(run_id)


@router.post("/api/documentation/runs/{run_id}/edits")
def edit_document_draft_http(
    run_id: str, body: DocumentEditBody, request: Request
) -> dict[str, object]:
    from .. import document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    new_run_id = document_edits.start_draft_edit(
        server._drafts_db(),
        run_id,
        ManualDocument(title=body.title, body=body.body),
        created_by=principal.id,
        provider=body.provider,
    )
    return server.get_documentation_run(new_run_id)


class DocumentRevisionBody(BaseModel):
    prompt: str = ""
    expected_revision: int = PydField(ge=1, strict=True)
    provider: Literal["claude", "openai"] | None = None
    start_from_destination: bool = False
    update_sources: bool = False


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


_DIFF_OPS: dict[str, Literal["+", "-", " "]] = {"+": "+", "-": "-", " ": " "}


class DiffLine(BaseModel):
    #: "+" added, "-" removed, " " unchanged context, "@" a hunk header.
    op: Literal["+", "-", " ", "@"]
    text: str


class RevisionDiff(BaseModel):
    document_id: str
    from_revision: int
    to_revision: int
    lines: list[DiffLine]


@router.get("/api/documentation/documents/{document_id}/revisions/{revision}/diff")
def document_revision_diff_http(
    document_id: str, revision: int, request: Request
) -> RevisionDiff:
    """A revision's body against the one it was revised from."""
    from .. import docs_store

    _require_principal(request)
    conn = server._drafts_db()
    new = docs_store.get_revision(conn, document_id, revision)
    if new is None:
        raise HTTPException(status_code=404, detail="revision not found")
    previous_revision = int(new["parent_revision"] or revision - 1)
    old = docs_store.get_revision(conn, document_id, previous_revision)
    if old is None:
        raise HTTPException(status_code=404, detail="no earlier revision to compare")
    diff = list(
        difflib.unified_diff(
            str(old["body"]).splitlines(),
            str(new["body"]).splitlines(),
            lineterm="",
            n=2,
        )
    )[2:]  # the ---/+++ file headers
    lines = [
        DiffLine(op="@", text=line)
        if line.startswith("@@")
        else DiffLine(op=_DIFF_OPS[line[0]], text=line[1:])
        for line in diff
    ]
    return RevisionDiff(
        document_id=document_id,
        from_revision=previous_revision,
        to_revision=revision,
        lines=lines,
    )


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
    return server.deliver_document(document_id, **body.model_dump())


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


class ApprovedItem(BaseModel):
    item_id: str
    run: dict[str, object] | None = None
    error: str | None = None


@router.post("/api/documentation/plan-items/approve")
def approve_plan_items_http(
    body: PlanItemsBody, request: Request
) -> list[ApprovedItem]:
    """Approve several items; each starts its own run, and one that cannot
    start reports why without stopping the rest."""
    _enforce_role(request, "writer", real_role=True)
    limit = product_settings.get(
        product_settings.DocumentationPlanningSettings
    ).approve_batch
    if len(body.item_ids) > limit:
        raise ValueError(f"Approve at most {limit} items at a time.")
    principal = _require_principal(request)
    results: list[ApprovedItem] = []
    for item_id in dict.fromkeys(body.item_ids):
        try:
            run = documentation_planning.approve(item_id, decided_by=principal.id)
        except (ValueError, LookupError) as exc:
            results.append(ApprovedItem(item_id=item_id, error=str(exc)))
        else:
            results.append(ApprovedItem(item_id=item_id, run=run))
    return results


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
