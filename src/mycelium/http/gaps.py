"""Knowledge-gap reports: free-form notes flagged by callers.

Humans report through the UI, agents through the `report_knowledge_gap` tool.
Reading gaps is open to every authenticated user; resolving, dismissing or
reopening one takes a real writer. Nothing here deletes one.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import auth, store
from .access import _enforce_curator, _require_principal

router = APIRouter()


def _serialize_gap(row: sqlite3.Row) -> dict[str, Any]:
    if row["resolved_at"]:
        status = "resolved"
    elif row["dismissed_at"]:
        status = "dismissed"
    else:
        status = "open"
    return {
        "id": row["id"],
        "text": row["text"],
        "status": status,
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
        "dismissed_at": row["dismissed_at"],
        "dismissed_by": row["dismissed_by"],
        "draft_id": row["draft_id"],
        "statement_id": row["statement_id"],
        "document_id": row["document_id"],
    }


@router.get("/api/knowledge-gaps")
def list_knowledge_gaps(request: Request, status: str | None = None) -> dict[str, Any]:
    """List gap reports.

    `status` query param filters to `open` / `resolved` / `dismissed`
    (or `all`, the default — returns everything ordered newest first).
    The status column is virtual: derived from which terminal
    timestamp is set.
    """
    p = _require_principal(request)
    conn = store.substrate_connection()
    status = status or "all"
    if status not in ("all", "open", "resolved", "dismissed"):
        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, resolved, dismissed",
        )
    rows = store.list_knowledge_gaps(conn, status=status)
    return {
        "gaps": [_serialize_gap(r) for r in rows],
        "can_write": auth.principal_has_real_role(p, "writer"),
    }


class GapUpdateBody(BaseModel):
    # One of:
    #   {"action": "resolve"}    → set resolved_at + resolved_by
    #   {"action": "dismiss"}    → set dismissed_at + dismissed_by
    #   {"action": "reopen"}     → clear both terminal timestamps
    action: str


@router.patch("/api/knowledge-gaps/{gap_id}")
def update_knowledge_gap(
    gap_id: str, body: GapUpdateBody, request: Request
) -> dict[str, Any]:
    p = _enforce_curator(request, "changing a knowledge gap's status")
    conn = store.substrate_connection()
    if store.get_knowledge_gap(conn, gap_id) is None:
        raise HTTPException(status_code=404, detail="gap not found")
    if body.action not in ("resolve", "dismiss", "reopen"):
        raise HTTPException(
            status_code=400,
            detail="action must be one of: resolve, dismiss, reopen",
        )
    with store.transaction(conn):
        updated = store.set_knowledge_gap_status(conn, gap_id, body.action, p.id)
    return {"gap": _serialize_gap(updated)}
