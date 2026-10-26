"""Knowledge health: what needs a curator's attention, and the lists behind
each count. Reading is open to every authenticated user; the connect pass
itself runs through the `connect_statements` tool route, and outside agents
claim work through the curation tools. Freeing an agent's claims or retrying
stopped work is an admin's. Each route calls the function the matching MCP
tool calls (`server.health`)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .. import automation_stops, curation, knowledge_health
from ..request_timing import TimedRoute
from ..server import health
from .access import _require_admin, _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/knowledge-health")
def knowledge_health_http(request: Request) -> health.HealthView:
    _require_principal(request)
    return health.health_view()


@router.get("/api/knowledge-health/statements/{which}")
def health_statements_http(
    which: knowledge_health.StatementFilter,
    request: Request,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    to_connect: bool = False,
) -> knowledge_health.StatementPage | knowledge_health.EntityPage:
    _require_principal(request)
    return health.health_list(which, after=after, limit=limit, to_connect=to_connect)


@router.get("/api/knowledge-health/entities/{which}")
def health_entities_http(
    which: knowledge_health.EntityFilter,
    request: Request,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> knowledge_health.StatementPage | knowledge_health.EntityPage:
    _require_principal(request)
    return health.health_list(which, after=after, limit=limit)


class FreeClaims(BaseModel):
    kind: curation.Kind
    claimed_by: str


class Freed(BaseModel):
    freed: int


@router.post("/api/knowledge-health/claims/free")
def free_claims_http(body: FreeClaims, request: Request) -> Freed:
    _require_admin(request)
    return Freed(freed=health.free_claims(body.kind, body.claimed_by))


class RetryStopped(BaseModel):
    kind: automation_stops.Kind
    item_id: str


class Retried(BaseModel):
    retried: bool


@router.post("/api/knowledge-health/stopped/retry")
def retry_stopped_http(body: RetryStopped, request: Request) -> Retried:
    _require_admin(request)
    return Retried(retried=health.retry_stopped(body.kind, body.item_id))
