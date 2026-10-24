"""Knowledge health: what needs a curator's attention, and the lists behind
each count. Reading is open to every authenticated user; the connect pass
itself runs through the `connect_statements` tool route, and outside agents
claim work through the curation tools. Freeing an agent's claims is an
admin's."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .. import (
    auth,
    automation_stops,
    curation,
    documentation_planning,
    knowledge_health,
    model_settings,
    product_settings,
    server,
    store,
)
from ..request_timing import TimedRoute
from ..server import runtime
from .access import _require_admin, _require_principal

router = APIRouter(route_class=TimedRoute)


class ConnectLimits(BaseModel):
    batch_size: int
    #: Most tokens one run may use; 0 for no cap.
    max_run_tokens: int
    provider: str
    model: str
    #: Runs are queued for an outside agent instead of a server model.
    external_agent: bool = False


class Holder(curation.Holder):
    #: The holder's display name, while they are a known user.
    name: str | None


class CurationView(BaseModel):
    kind: curation.Kind
    claims: list[Holder]
    attempted: int
    outcomes: dict[str, int]


class HealthView(BaseModel):
    counts: knowledge_health.Counts
    connect: ConnectLimits | None
    #: Why the connect pass is unavailable, when it is.
    connect_error: str | None
    #: Per curation work kind: who holds items, and what came of them.
    curation: list[CurationView]
    #: Per writing profile, statements its audience may see that none of its
    #: documents cites, apart from those dismissed for it.
    uncovered_by_profile: dict[str, int]
    #: Automatic work that exhausted its saved retry limit.
    stopped: list[automation_stops.Stop]


def _curation() -> list[CurationView]:
    names: dict[str, str | None] = {}
    views = []
    for summary in curation.summaries(
        server._db(), server._drafts_db(), datetime.now(UTC)
    ):
        holders = []
        for holder in summary.claims:
            if holder.claimed_by not in names:
                user = auth.get_user(runtime._auth_db(), holder.claimed_by)
                names[holder.claimed_by] = None if user is None else str(user["name"])
            holders.append(Holder(**holder.model_dump(), name=names[holder.claimed_by]))
        views.append(
            CurationView(
                kind=summary.kind,
                claims=holders,
                attempted=summary.attempted,
                outcomes=summary.outcomes,
            )
        )
    return views


@router.get("/api/knowledge-health")
def knowledge_health_http(request: Request) -> HealthView:
    _require_principal(request)
    counts = knowledge_health.counts(
        server._db(), server._drafts_db(), store.substrate_connection
    )
    uncovered = documentation_planning.uncovered_counts(
        server._drafts_db(), server._db()
    )
    work = _curation()
    stopped = automation_stops.stops(server._db())
    try:
        limits = product_settings.get(product_settings.ConnectSettings)
        selected = model_settings.get("connect")
    except model_settings.Unavailable as exc:
        return HealthView(
            counts=counts,
            connect=None,
            connect_error=str(exc),
            curation=work,
            uncovered_by_profile=uncovered,
            stopped=stopped,
        )
    if reason := model_settings.credentials_error("connect"):
        return HealthView(
            counts=counts,
            connect=None,
            connect_error=reason,
            curation=work,
            uncovered_by_profile=uncovered,
            stopped=stopped,
        )
    return HealthView(
        counts=counts,
        curation=work,
        uncovered_by_profile=uncovered,
        stopped=stopped,
        connect=ConnectLimits(
            batch_size=limits.batch_size,
            max_run_tokens=limits.max_run_tokens,
            provider=selected.provider,
            model=selected.model,
            external_agent=selected.external_agent,
        ),
        connect_error=None,
    )


@router.get("/api/knowledge-health/statements/{which}")
def health_statements_http(
    which: knowledge_health.StatementFilter,
    request: Request,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    to_connect: bool = False,
) -> knowledge_health.StatementPage:
    _require_principal(request)
    if to_connect:
        return knowledge_health.to_connect(
            server._db(), server._drafts_db(), which, limit=limit
        )
    return knowledge_health.statements(
        server._db(), server._drafts_db(), which, after=after, limit=limit
    )


@router.get("/api/knowledge-health/entities/{which}")
def health_entities_http(
    which: knowledge_health.EntityFilter,
    request: Request,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> knowledge_health.EntityPage:
    _require_principal(request)
    return knowledge_health.entities(server._db(), which, after=after, limit=limit)


class FreeClaims(BaseModel):
    kind: curation.Kind
    claimed_by: str


class Freed(BaseModel):
    freed: int


@router.post("/api/knowledge-health/claims/free")
def free_claims_http(body: FreeClaims, request: Request) -> Freed:
    _require_admin(request)
    with store.transaction(server._db()):
        freed = curation.free(server._db(), body.kind, body.claimed_by)
    return Freed(freed=freed)


class RetryStopped(BaseModel):
    kind: automation_stops.Kind
    item_id: str


class Retried(BaseModel):
    retried: bool


@router.post("/api/knowledge-health/stopped/retry")
def retry_stopped_http(body: RetryStopped, request: Request) -> Retried:
    _require_admin(request)
    with store.transaction(server._db()):
        retried = automation_stops.retry(server._db(), body.kind, body.item_id)
    return Retried(retried=retried)
