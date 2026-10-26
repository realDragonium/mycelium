"""Knowledge-gap reports: free-form notes flagged by callers.

Humans report through the UI, agents through the `report_knowledge_gap` tool.
Reading gaps is open to every authenticated user; resolving, dismissing or
reopening one takes a real writer. Nothing here deletes one. Each route calls
the function the matching MCP tool calls (`server.gaps`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import server, store
from ..request_timing import TimedRoute
from ..server.gaps import is_gap_action, is_gap_status
from .access import _enforce_curator, _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/knowledge-gaps")
def list_knowledge_gaps(request: Request, status: str | None = None) -> dict[str, Any]:
    """List gap reports.

    `status` query param filters to `open` / `resolved` / `dismissed`
    (or `all`, the default — returns everything ordered newest first).
    The status column is virtual: derived from which terminal
    timestamp is set.
    """
    _require_principal(request)
    status = status or "all"
    if not is_gap_status(status):
        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, resolved, dismissed",
        )
    return server.list_knowledge_gaps(status)


class GapUpdateBody(BaseModel):
    action: str


@router.patch("/api/knowledge-gaps/{gap_id}")
def update_knowledge_gap(
    gap_id: str, body: GapUpdateBody, request: Request
) -> dict[str, Any]:
    _enforce_curator(request, "changing a knowledge gap's status")
    if store.get_knowledge_gap(store.substrate_connection(), gap_id) is None:
        raise HTTPException(status_code=404, detail="gap not found")
    if not is_gap_action(body.action):
        raise HTTPException(
            status_code=400,
            detail="action must be one of: resolve, dismiss, reopen",
        )
    try:
        return server.update_knowledge_gap(gap_id, body.action)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
