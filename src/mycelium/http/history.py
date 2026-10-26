"""The activity feed route; `server.history.get_history` builds the feed for
the web app and agents alike."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import server
from ..request_timing import TimedRoute

router = APIRouter(route_class=TimedRoute)


@router.get("/api/history")
def get_history(
    limit: int = 50,
    offset: int = 0,
    op: str | None = None,
    target_kind: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    return server.get_history(
        limit=limit, offset=offset, op=op, target_kind=target_kind, q=q
    )
