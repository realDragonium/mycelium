"""Knowledge health: what needs a curator's attention, and the lists behind
each count. Reading is open to every authenticated user; the connect pass
itself runs through the `connect_statements` tool route."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from .. import knowledge_health, model_settings, product_settings, server, store
from ..ai.pricing import price
from .access import _require_principal

router = APIRouter()


class ConnectLimits(BaseModel):
    batch_size: int
    max_cost_usd: float
    provider: str
    model: str
    #: False when the model has no known price, so neither cost nor the
    #: spending cap can be applied; the op cap and wall clock still bound it.
    priced: bool


class HealthView(BaseModel):
    counts: knowledge_health.Counts
    connect: ConnectLimits | None
    #: Why the connect pass is unavailable, when it is.
    connect_error: str | None


@router.get("/api/knowledge-health")
def knowledge_health_http(request: Request) -> HealthView:
    _require_principal(request)
    counts = knowledge_health.counts(
        server._db(), server._drafts_db(), store.substrate_connection
    )
    try:
        limits = product_settings.get(product_settings.ConnectSettings)
        selected = model_settings.get("connect")
    except model_settings.Unavailable as exc:
        return HealthView(counts=counts, connect=None, connect_error=str(exc))
    if reason := model_settings.credentials_error("connect"):
        return HealthView(counts=counts, connect=None, connect_error=reason)
    return HealthView(
        counts=counts,
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
    skip_pending: bool = False,
) -> knowledge_health.StatementPage:
    _require_principal(request)
    return knowledge_health.statements(
        server._db(),
        server._drafts_db(),
        which,
        after=after,
        limit=limit,
        skip_pending=skip_pending,
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
