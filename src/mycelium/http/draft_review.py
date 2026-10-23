"""The internal draft reviewer: running it on a draft, answering its questions,
and reviewing the backlog it has not reached.

Running and answering need a real writer (`_enforce_curator`); the backlog is
admin-only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, JsonValue

from .. import draft_review_settings as review_settings
from .. import server
from .access import _enforce_curator, _require_admin

router = APIRouter()


class Backlog(BaseModel):
    draft_ids: list[str]
    #: What reviewing them all is likely to cost, from what a review has
    #: cost over the last 30 days; None without a priced review on record.
    estimated_cost_usd: float | None


@router.get("/api/draft-review/backlog")
def draft_review_backlog(request: Request) -> Backlog:
    """Submitted drafts the current review configuration has not reached, to
    offer reviewing them once when review is switched on."""
    from .. import ai_usage, draft_review_runs, drafts_store, timestamps

    _require_admin(request)
    try:
        draft_ids = draft_review_runs.backlog()
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    since = timestamps.of(datetime.now(UTC) - timedelta(days=30))
    mean = ai_usage.mean_run_cost(drafts_store.connection(), "draft_review", since)
    return Backlog(
        draft_ids=draft_ids,
        estimated_cost_usd=None if mean is None else len(draft_ids) * mean,
    )


@router.post("/api/draft-review/backlog")
def review_draft_backlog(request: Request) -> dict[str, list[str]]:
    """Start reviewing every draft in the backlog; returns their ids."""
    from .. import draft_review_runs

    _require_admin(request)
    try:
        return {"draft_ids": draft_review_runs.review_backlog()}
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
