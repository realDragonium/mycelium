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
    curation,
    knowledge_health,
    model_settings,
    product_settings,
    server,
    store,
)
from ..ai.pricing import price
from ..request_timing import TimedRoute
from ..server import runtime
from .access import _require_admin, _require_principal

router = APIRouter(route_class=TimedRoute)


class ConnectLimits(BaseModel):
    batch_size: int
    max_cost_usd: float
    provider: str
    model: str
    #: False when the model has no known price, so neither cost nor the
    #: spending cap can be applied; the op cap and wall clock still bound it.
    priced: bool


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


def _curation() -> list[CurationView]:
    names: dict[str, str | None] = {}
    views = []
    for summary in curation.summaries(server._db(), datetime.now(UTC)):
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
    work = _curation()
    try:
        limits = product_settings.get(product_settings.ConnectSettings)
        selected = model_settings.get("connect")
    except model_settings.Unavailable as exc:
        return HealthView(
            counts=counts, connect=None, connect_error=str(exc), curation=work
        )
    if reason := model_settings.credentials_error("connect"):
        return HealthView(
            counts=counts, connect=None, connect_error=reason, curation=work
        )
    return HealthView(
        counts=counts,
        curation=work,
        connect=ConnectLimits(
            batch_size=limits.batch_size,
            max_cost_usd=limits.max_cost_usd,
            provider=selected.provider,
            model=selected.model,
            priced=price(selected.provider, selected.model) is not None,
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
