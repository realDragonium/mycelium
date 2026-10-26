"""Draft lifecycle over HTTP: list, inspect, edit, submit, approve, reject,
reopen, withdraw.

Drafts are pending change sets submitted by drafters (or anyone passing an
explicit `draft_id` to a write tool). Curators review and either approve
(replay the ops against the substrate) or reject (drop them without
applying). Status is derived from terminal timestamps + decision, the same
pattern as knowledge gaps.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import server, store
from ..draft_review_store import Application, Label
from ..request_timing import TimedRoute
from ..server import draft_decisions
from ..server.drafts import submit, withdraw
from .access import _enforce_curator, _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/drafts")
def list_drafts(
    request: Request,
    status: str | None = None,
    label: Label | None = None,
    application: Application | None = None,
) -> dict[str, Any]:
    """List drafts, newest first. `status` filters to one of:
    open / submitted / approved / rejected / withdrawn / all (default);
    `label` and `application` to the latest review assessment's.
    """
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    status = status or "all"
    if status not in ("all", "open", "submitted", "approved", "rejected", "withdrawn"):
        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, submitted, approved, rejected, withdrawn",
        )
    counts = drafts_store.count_ops_by_draft(conn)
    return {
        "drafts": [
            {**draft, "op_count": counts.get(draft["id"], 0)}
            for draft in drafts_store.list_draft_summaries(
                conn, status=status, label=label, application=application
            )
        ]
    }


@router.get("/api/drafts/{draft_id}")
def get_draft_detail(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row, ops = drafts_store.get_draft_snapshot(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    decisions = drafts_store.list_decisions(conn, draft_id)
    return {"draft": drafts_store.serialize_draft(row, ops=ops, decisions=decisions)}


class DraftOpEditBody(BaseModel):
    payload: dict[str, Any]
    expected_revision: int | None = None


@router.patch("/api/drafts/{draft_id}/ops/{seq}")
def edit_draft_op(
    draft_id: str, seq: int, body: DraftOpEditBody, request: Request
) -> dict[str, Any]:
    """Replace an op's payload on an open or submitted draft."""
    _enforce_curator(request, action="editing a draft operation")
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            raise HTTPException(status_code=404, detail="draft not found")
        status = drafts_store.status_for(row)
        if status not in ("open", "submitted"):
            raise HTTPException(
                status_code=400,
                detail=f"cannot edit ops on a {status} draft",
            )
        revision = drafts_store.update_op_payload(
            conn,
            draft_id,
            seq,
            body.payload,
            expected_revision=body.expected_revision,
        )
    if revision is None:
        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True, "revision": revision}


@router.delete("/api/drafts/{draft_id}/ops/{seq}")
def remove_draft_op_http(
    draft_id: str,
    seq: int,
    request: Request,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    _enforce_curator(request, action="removing a draft operation")
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            raise HTTPException(status_code=404, detail="draft not found")
        status = drafts_store.status_for(row)
        if status not in ("open", "submitted"):
            raise HTTPException(
                status_code=400,
                detail=f"cannot remove ops from a {status} draft",
            )
        revision = drafts_store.remove_op(
            conn, draft_id, seq, expected_revision=expected_revision
        )
    if revision is None:
        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True, "revision": revision}


@router.post("/api/drafts/{draft_id}/submit")
def submit_draft_http(draft_id: str, request: Request) -> dict[str, Any]:
    try:
        submit(draft_id, _require_principal(request))
    except LookupError as ex:
        raise HTTPException(status_code=404, detail="draft not found") from ex
    return {"ok": True}


@router.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, request: Request) -> dict[str, Any]:
    """Replay the draft's ops against the substrate as the curator.

    Requires real writer+ (not drafter — see `_enforce_curator`).
    All-or-nothing: a single op failure halts replay and leaves the
    draft in its prior state so the curator can edit and retry. When a
    tool refuses statements (the phrasing linter), the 422 detail lists
    each one under `rejections` so the curator can fix them.
    """
    p = _enforce_curator(request)
    from .. import drafts_store

    try:
        result = server.approve_draft(
            draft_id, decided_by=p.id, note=drafts_store.decision_note(p.id)
        )
    except drafts_store.ActiveApplicationError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except server.DraftOpsRejectedError as ex:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Nothing was applied: fix or discard the refused "
                "statements, then approve again.",
                "rejections": ex.rejections,
            },
        ) from ex
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, **result}


@router.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _enforce_curator(request)
    from .. import drafts_store

    if drafts_store.get_draft(server._drafts_db(), draft_id) is None:
        raise HTTPException(status_code=404, detail="draft not found")
    draft_decisions.reject(draft_id, drafts_store.decision_note(p.id))
    return {"ok": True}


class DraftReopenBody(BaseModel):
    reason: str = Field(min_length=1, max_length=draft_decisions.MAX_REASON)


@router.post("/api/drafts/{draft_id}/reopen")
def reopen_draft(
    draft_id: str, body: DraftReopenBody, request: Request
) -> dict[str, Any]:
    """Return a rejected draft to submitted so it can be decided again."""
    p = _enforce_curator(request, action="reopening a draft")
    from .. import drafts_store

    if drafts_store.get_draft(server._drafts_db(), draft_id) is None:
        raise HTTPException(status_code=404, detail="draft not found")
    draft_decisions.reopen(
        draft_id, drafts_store.decision_note(p.id, reason=body.reason.strip())
    )
    return {"ok": True}


@router.post("/api/drafts/{draft_id}/withdraw")
def withdraw_draft(draft_id: str, request: Request) -> dict[str, Any]:
    try:
        withdraw(draft_id, _require_principal(request))
    except LookupError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex
    return {"ok": True}
