"""Documentation audiences, statement audience labels and the labelling backfill.

Reads need an authenticated caller. Audiences and the backfill are admin
configuration; a curator's label decision needs a real writer.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import (
    audience_labelling,
    audiences,
    grant_confirmation,
    product_settings,
    server,
    store,
)
from ..request_timing import TimedRoute
from .access import _enforce_role, _require_principal

router = APIRouter(route_class=TimedRoute)


class AudiencesResponse(audiences.AudiencesView):
    labelling: audience_labelling.Status


@router.get("/api/audiences")
def list_audiences_http(request: Request) -> AudiencesResponse:
    view = audiences.view(_require_principal(request), server._db())
    return AudiencesResponse(
        **view.model_dump(), labelling=audience_labelling.status(server._db())
    )


@router.post("/api/audiences")
def create_audience_http(
    body: audiences.CreateAudience, request: Request
) -> dict[str, str]:
    created = audiences.create(body, _require_principal(request))
    return {"id": created.id}


@router.put("/api/audiences/{audience_id}")
def save_audience_http(
    audience_id: str, body: audiences.SaveAudience, request: Request
) -> dict[str, str]:
    saved = audiences.save(audience_id, body, _require_principal(request))
    return {"id": saved.id}


@router.post("/api/audiences/{audience_id}/retire")
def retire_audience_http(
    audience_id: str, body: audiences.RetireAudience, request: Request
) -> dict[str, bool]:
    audiences.retire(audience_id, body, _require_principal(request))
    return {"retired": True}


@router.get("/api/audiences/labelling")
def labelling_status_http(request: Request) -> audience_labelling.Status:
    _require_principal(request)
    return audience_labelling.status(server._db())


class BackfillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relabel_ai: bool = False


@router.post("/api/audiences/labelling/backfill")
def backfill_http(body: BackfillBody, request: Request) -> audience_labelling.Backfill:
    _enforce_role(request, "admin", real_role=True)
    return audience_labelling.backfill(relabel_ai=body.relabel_ai)


# --- statement labels ----------------------------------------------------------


class Label(BaseModel):
    audiences: list[str]
    source: Literal["ai", "curator"]
    reason: str
    model: str | None
    labelled_at: str
    labelled_by: str | None
    text_changed_at: str | None
    pending: list[str]
    #: Set when the AI's relabel after an edit took the statement away from
    #: audiences that saw it, with the reason it gave.
    narrowed: store.audience_labels.Narrowed | None
    #: Set while confirmed external grants an edit kept wait for a spot check.
    spot_check: store.audience_labels.SpotCheck | None


class AudienceVisibility(BaseModel):
    id: str
    name: str
    scope: audiences.Scope
    visible: bool
    pending: bool


class StatementAudiences(BaseModel):
    statement_id: str
    label: Label | None
    queued: bool
    audiences: list[AudienceVisibility]
    can_curate: bool


def _label(row: sqlite3.Row | None) -> Label | None:
    if row is None:
        return None
    return Label(
        audiences=store.audience_labels.label_audiences(row),
        source=row["source"],
        reason=row["reason"],
        model=row["model"],
        labelled_at=row["labelled_at"],
        labelled_by=row["labelled_by"],
        text_changed_at=row["text_changed_at"],
        pending=store.audience_labels.label_pending(row),
        narrowed=store.audience_labels.label_narrowed(row),
        spot_check=store.audience_labels.label_spot_check(row),
    )


def _statement_audiences(statement_id: str, request: Request) -> StatementAudiences:
    from .. import auth

    principal = _require_principal(request)
    conn = server._db()
    if store.get_statement(conn, statement_id) is None:
        raise ValueError(f"Statement {statement_id} does not exist.")
    row = store.audience_labels.get_label(conn, statement_id)
    pending = set(store.audience_labels.label_pending(row)) if row else set()
    return StatementAudiences(
        statement_id=statement_id,
        label=_label(row),
        queued=store.audience_labels.is_queued(conn, statement_id),
        audiences=[
            AudienceVisibility(
                id=item.id,
                name=item.name,
                scope=item.scope,
                visible=store.audience_labels.label_visible(
                    row, item.sees, item.internal
                ),
                pending=item.id in pending,
            )
            for item in audiences.live()
        ],
        can_curate=auth.principal_has_real_role(principal, "writer"),
    )


@router.get("/api/statements/{statement_id}/audiences")
def statement_audiences_http(statement_id: str, request: Request) -> StatementAudiences:
    return _statement_audiences(statement_id, request)


class CuratorLabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audiences: list[str] = Field(max_length=50)
    reason: str = Field(default="", max_length=500)


@router.put("/api/statements/{statement_id}/audiences")
def set_statement_audiences_http(
    statement_id: str, body: CuratorLabelBody, request: Request
) -> StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.set_curator_label(
        statement_id,
        body.audiences,
        body.reason,
        curator=_require_principal(request).id,
    )
    return _statement_audiences(statement_id, request)


@router.post("/api/statements/{statement_id}/audiences/confirm")
def confirm_statement_audiences_http(
    statement_id: str, request: Request
) -> StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.confirm_curator_label(
        statement_id, curator=_require_principal(request).id
    )
    return _statement_audiences(statement_id, request)


@router.delete("/api/statements/{statement_id}/audiences")
def clear_statement_audiences_http(
    statement_id: str, request: Request
) -> StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.clear_curator_label(statement_id)
    return _statement_audiences(statement_id, request)


# --- filter --------------------------------------------------------------------


class LabelledStatement(BaseModel):
    id: str
    kind: str
    text: str
    label: Label | None
    queued: bool


class LabelledStatements(BaseModel):
    statements: list[LabelledStatement]
    total: int
    can_curate: bool


@router.get("/api/audiences/statements")
def labelled_statements_http(
    request: Request,
    audience: str | None = None,
    visibility: store.audience_labels.Visibility | None = None,
    state: store.audience_labels.LabelState | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> LabelledStatements:
    """Statements by what an audience sees and by label state."""
    from .. import auth

    principal = _require_principal(request)
    chosen = None
    if visibility is not None:
        chosen = next((item for item in audiences.live() if item.id == audience), None)
        if chosen is None:
            raise ValueError("Choose a live audience to filter by visibility.")
    conn = server._db()
    rows, total = store.audience_labels.list_labelled_statements(
        conn,
        sees=chosen.sees if chosen else None,
        internal=chosen.internal if chosen else False,
        visibility=visibility,
        state=state,
        offset=offset,
        limit=limit,
    )
    return LabelledStatements(
        statements=[
            LabelledStatement(
                id=row["id"],
                kind=row["kind"],
                text=row["text"],
                label=_label(store.audience_labels.get_label(conn, row["id"])),
                queued=row["queued"] is not None,
            )
            for row in rows
        ],
        total=total,
        can_curate=auth.principal_has_real_role(principal, "writer"),
    )


# --- pending external grants ---------------------------------------------------


class PendingGrants(BaseModel):
    audience_id: str
    total: int
    groups: list[grant_confirmation.PendingGroup]
    can_curate: bool
    sample_size: int
    min_sample_precision_percent: int


@router.get("/api/audiences/{audience_id}/pending")
def pending_grants_http(audience_id: str, request: Request) -> PendingGrants:
    """The audience's grants waiting for a curator, grouped by concept."""
    from .. import auth

    principal = _require_principal(request)
    audience = grant_confirmation.live_audience(audience_id)
    groups = grant_confirmation.groups(server._db(), audience.id)
    limits = product_settings.get(product_settings.AudienceLabellingSettings)
    return PendingGrants(
        audience_id=audience.id,
        total=sum(len(group.statements) for group in groups),
        groups=groups,
        can_curate=auth.principal_has_real_role(principal, "writer"),
        sample_size=limits.sample_size,
        min_sample_precision_percent=limits.min_sample_precision_percent,
    )


class PendingSample(BaseModel):
    groups: list[grant_confirmation.PendingGroup]


@router.get("/api/audiences/{audience_id}/pending/sample")
def pending_sample_http(audience_id: str, request: Request) -> PendingSample:
    """A fresh random sample of the audience's pending grants, stratified by
    concept."""
    _require_principal(request)
    audience = grant_confirmation.live_audience(audience_id)
    limits = product_settings.get(product_settings.AudienceLabellingSettings)
    return PendingSample(
        groups=grant_confirmation.sample(server._db(), audience.id, limits.sample_size)
    )


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement_ids: list[str] = Field(min_length=1, max_length=2000)
    decision: Literal["confirm", "reject"]


class Decided(BaseModel):
    decided: int


@router.post("/api/audiences/{audience_id}/pending/decide")
def decide_pending_http(
    audience_id: str, body: DecideBody, request: Request
) -> Decided:
    _enforce_role(request, "writer", real_role=True)
    return Decided(
        decided=grant_confirmation.decide(
            audience_id,
            body.statement_ids,
            confirm=body.decision == "confirm",
            curator=_require_principal(request).id,
        )
    )


class AcceptRestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample: list[str] = Field(min_length=1, max_length=500)


@router.post("/api/audiences/{audience_id}/pending/accept-rest")
def accept_rest_http(
    audience_id: str, body: AcceptRestBody, request: Request
) -> grant_confirmation.Accepted:
    _enforce_role(request, "writer", real_role=True)
    return grant_confirmation.accept_rest(
        audience_id, body.sample, curator=_require_principal(request).id
    )


# --- spot checks after edits ----------------------------------------------------


class SpotChecks(BaseModel):
    statements: list[grant_confirmation.SpotCheck]
    can_curate: bool


@router.get("/api/audiences/spot-checks")
def spot_checks_http(request: Request) -> SpotChecks:
    """Recently edited statements whose confirmed external grants stayed in force."""
    from .. import auth

    principal = _require_principal(request)
    return SpotChecks(
        statements=grant_confirmation.spot_checks(server._db()),
        can_curate=auth.principal_has_real_role(principal, "writer"),
    )


class SpotCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirm", "narrow"]


@router.post("/api/statements/{statement_id}/audiences/spot-check")
def decide_spot_check_http(
    statement_id: str, body: SpotCheckBody, request: Request
) -> Decided:
    _enforce_role(request, "writer", real_role=True)
    return Decided(
        decided=int(
            grant_confirmation.decide_spot_check(
                statement_id,
                confirm=body.decision == "confirm",
                curator=_require_principal(request).id,
            )
        )
    )
