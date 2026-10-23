"""Draft lifecycle over HTTP: list, inspect, edit, submit, approve, reject, withdraw.

Drafts are pending change sets submitted by drafters (or anyone passing an
explicit `draft_id` to a write tool). Curators review and either approve
(replay the ops against the substrate) or reject (drop them without
applying). Status is derived from terminal timestamps + decision, the same
pattern as knowledge gaps.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import server, store
from ..server.draft_queue import _require_draft_owner
from .access import _enforce_curator, _require_principal

router = APIRouter()


@router.get("/api/drafts")
def list_drafts(request: Request, status: str | None = None) -> dict[str, Any]:
    """List drafts, newest first. `status` filters to one of:
    open / submitted / approved / rejected / withdrawn / all (default).
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
    rows = drafts_store.list_drafts(conn, status=status)
    counts = drafts_store.count_ops_by_draft(conn)
    out = []
    for r in rows:
        d = drafts_store.serialize_draft(r)
        d["op_count"] = counts.get(r["id"], 0)
        out.append(d)
    return {"drafts": out}


@router.get("/api/drafts/{draft_id}")
def get_draft_detail(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row, ops = drafts_store.get_draft_snapshot(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return {"draft": drafts_store.serialize_draft(row, ops=ops)}


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
    p = _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    _require_draft_owner(p, row)
    if drafts_store.status_for(row) != "open":
        raise HTTPException(
            status_code=400,
            detail="only open drafts can be submitted",
        )
    with store.transaction(conn):
        drafts_store.set_submitted(conn, draft_id)
    from .. import draft_review_runs

    draft_review_runs.on_submitted(draft_id)
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

    conn = server._drafts_db()
    try:
        with store.write_lock():
            result = server.apply_draft(draft_id)
            with store.transaction(conn):
                drafts_store.set_decision(conn, draft_id, decision="approved", by=p.id)
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

    conn = server._drafts_db()
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            raise HTTPException(status_code=404, detail="draft not found")
        if drafts_store.status_for(row) not in ("open", "submitted"):
            raise HTTPException(
                status_code=400,
                detail="only open or submitted drafts can be rejected",
            )
        drafts_store.set_decision(conn, draft_id, decision="rejected", by=p.id)
    return {"ok": True}


@router.post("/api/drafts/{draft_id}/withdraw")
def withdraw_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="draft not found")
    _require_draft_owner(p, row)
    if drafts_store.status_for(row) not in ("open", "submitted"):
        raise HTTPException(
            status_code=400,
            detail="only open or submitted drafts can be withdrawn",
        )
    with store.transaction(conn):
        try:
            drafts_store.set_decision(conn, draft_id, decision="withdrawn", by=p.id)
        except drafts_store.ActiveApplicationError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
    return {"ok": True}
