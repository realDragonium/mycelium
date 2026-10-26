"""The internal draft reviewer: running it on a draft, answering its questions,
and reviewing the backlog it has not reached.

Running and answering need a real writer (`_enforce_curator`); the backlog and
its review job are admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, JsonValue

from .. import draft_review_settings as review_settings
from .. import server
from ..draft_review_runs import BacklogJob
from ..draft_review_store import Correction
from ..request_timing import TimedRoute
from ..server.drafts import ReviewBacklog, review_backlog
from .access import _enforce_curator, _require_admin

router = APIRouter(route_class=TimedRoute)


class BacklogJobBody(BaseModel):
    job: BacklogJob


@router.get("/api/draft-review/backlog")
def draft_review_backlog(request: Request) -> ReviewBacklog:
    """Submitted drafts the current review configuration has not reached,
    oldest first, to offer reviewing them once when review is switched on,
    with the backlog review this process last started."""
    _require_admin(request)
    try:
        return review_backlog()
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/api/draft-review/backlog")
def review_draft_backlog(request: Request) -> BacklogJobBody:
    """Start reviewing the backlog oldest first, one draft at a time."""
    from .. import draft_review_runs

    _require_admin(request)
    try:
        return BacklogJobBody(job=draft_review_runs.review_backlog())
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/api/draft-review/backlog/pause")
def pause_draft_backlog(request: Request) -> BacklogJobBody:
    """Stop the backlog review after the draft under review."""
    from .. import draft_review_runs

    _require_admin(request)
    return BacklogJobBody(job=draft_review_runs.pause_backlog())


@router.post("/api/draft-review/backlog/resume")
def resume_draft_backlog(request: Request) -> BacklogJobBody:
    from .. import draft_review_runs

    _require_admin(request)
    try:
        return BacklogJobBody(job=draft_review_runs.resume_backlog())
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/api/drafts/{draft_id}/review")
def run_draft_review_http(
    draft_id: str, request: Request
) -> dict[str, dict[str, JsonValue]]:
    _enforce_curator(request, action="running an internal draft review")
    return {"review": server.request_draft_review(draft_id, rerun=True)}


class DraftReviewAnswerBody(BaseModel):
    run_id: str
    answer: str


@router.post("/api/drafts/{draft_id}/review/answer")
def answer_draft_review_http(
    draft_id: str, body: DraftReviewAnswerBody, request: Request
) -> dict[str, dict[str, JsonValue]]:
    """Answer the internal reviewer's questions; the draft is reviewed again."""
    from pydantic import ValidationError

    from .. import draft_review_runs

    principal = _enforce_curator(request, action="answering the internal reviewer")
    try:
        run = draft_review_runs.answer(draft_id, body.run_id, body.answer, principal)
    except ValidationError as exc:
        raise ValueError("answer must be 1 to 6000 characters") from exc
    return {"review": run.model_dump(mode="json")}


class DraftReviewAcceptBody(BaseModel):
    run_id: str
    #: The corrections to apply; the reviewer's own when omitted.
    corrections: list[Correction] | None = None


@router.post("/api/drafts/{draft_id}/review/accept")
def accept_draft_review_http(
    draft_id: str, body: DraftReviewAcceptBody, request: Request
) -> dict[str, dict[str, JsonValue]]:
    """Approve a draft the reviewer held, with its suggested corrections or
    the curator's edit of them."""
    from .. import draft_review_runs, drafts_store

    principal = _enforce_curator(request, action="approving a reviewed draft")
    try:
        run = draft_review_runs.accept_corrections(
            draft_id, body.run_id, body.corrections, principal
        )
    except drafts_store.ActiveApplicationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except server.DraftOpsRejectedError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The corrections were applied to the draft, but "
                "approving it was refused: fix or discard the refused "
                "statements, then approve again.",
                "rejections": exc.rejections,
            },
        ) from exc
    return {"review": run.model_dump(mode="json")}
