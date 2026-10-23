"""Names and aliases: the names workspace, mention candidates and alias suggestions.

Reads are open to any authenticated caller. Edits need a real writer, and
merging or removing a name an admin; alias suggestions are reviewed by a real
writer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import JsonValue

from .. import alias_suggestions, auth, names_workspace, server
from .access import _enforce_curator, _enforce_role, _require_admin, _require_principal

router = APIRouter()


@router.get("/api/mention-candidates")
def mention_candidates(
    request: Request, entity_id: str, after: int = 0, limit: int = 50
) -> dict[str, JsonValue]:
    _require_principal(request)
    return server.get_mention_candidates(entity_id=entity_id, after=after, limit=limit)


@router.get("/api/names-workspace")
def names_catalogue_http(request: Request, q: str = "") -> names_workspace.Catalogue:
    principal = _require_principal(request)
    result = names_workspace.catalogue(server._db(), q)
    result.can_write = auth.principal_has_real_role(principal, "writer")
    if result.can_write:
        result.allowed_actions = ["add", "correct", "prefer", "move", "split"]
    if auth.principal_has_real_role(principal, "admin"):
        result.allowed_actions.extend(("merge", "remove"))
    return result


@router.post("/api/names-workspace/preview")
def names_preview_http(
    body: names_workspace.PreviewRequest, request: Request
) -> names_workspace.Preview:
    _enforce_curator(request, "editing names and aliases")
    if body.action.kind in {"merge", "remove"}:
        _require_admin(request)
    return names_workspace.preview(server._db(), body.action)


@router.post("/api/names-workspace/apply")
def names_apply_http(
    body: names_workspace.ApplyRequest, request: Request
) -> names_workspace.Applied:
    _enforce_curator(request, "editing names and aliases")
    if body.action.kind in {"merge", "remove"}:
        _require_admin(request)
    return names_workspace.apply(body)


@router.post("/api/names-workspace/duplicates/dismiss", status_code=204)
def names_dismiss_duplicate_http(
    body: names_workspace.DismissDuplicate, request: Request
) -> None:
    _enforce_curator(request, "dismissing possible duplicates")
    names_workspace.dismiss_duplicate(server._db(), body)


@router.get("/api/names-workspace/duplicates/dismissed")
def names_dismissed_duplicates_http(
    request: Request,
) -> names_workspace.DismissedDuplicates:
    _require_principal(request)
    return names_workspace.dismissed_duplicates(server._db())


@router.post("/api/names-workspace/duplicates/restore", status_code=204)
def names_restore_duplicate_http(
    body: names_workspace.DismissDuplicate, request: Request
) -> None:
    _enforce_curator(request, "restoring dismissed duplicates")
    names_workspace.restore_duplicate(server._db(), body)


@router.get("/api/names-workspace/{entity_id}")
def names_detail_http(entity_id: str, request: Request) -> names_workspace.Detail:
    _require_principal(request)
    return names_workspace.detail(server._db(), entity_id)


@router.get("/api/alias-suggestions")
def alias_suggestions_http(
    request: Request, status: str = "pending"
) -> dict[str, object]:
    _enforce_role(request, "reader")
    return {
        "suggestions": [
            entry.model_dump(mode="json")
            for entry in alias_suggestions.list_entries(status)
        ]
    }


@router.post("/api/alias-suggestions/scan")
def scan_alias_suggestions_http(
    request: Request, body: alias_suggestions.ScanRequest
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return alias_suggestions.scan(body, _require_principal(request)).model_dump(
        mode="json"
    )


@router.post("/api/alias-suggestions/{draft_id}/{operation_ref}/review")
def review_alias_suggestion_http(
    draft_id: str,
    operation_ref: str,
    request: Request,
    body: alias_suggestions.ReviewRequest,
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    entry = alias_suggestions.review(
        draft_id, operation_ref, body, _require_principal(request)
    )
    return entry.model_dump(mode="json")
