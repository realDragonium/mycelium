"""Documentation audiences, statement audience labels and the labelling backfill.

Reads need an authenticated caller. Audiences and the backfill are admin
configuration; a curator's label decision needs a real writer. Each route calls
the function the matching MCP tool calls (`server.audience_tools`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import audience_labelling, audiences, grant_confirmation, store
from ..request_timing import TimedRoute
from ..server import audience_tools as tools
from .access import _enforce_role, _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/audiences")
def list_audiences_http(request: Request) -> tools.AudiencesResponse:
    return tools.audiences_view(_require_principal(request))


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
    return audience_labelling.status(store.substrate_connection())


class BackfillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relabel_ai: bool = False


@router.post("/api/audiences/labelling/backfill")
def backfill_http(body: BackfillBody, request: Request) -> audience_labelling.Backfill:
    _enforce_role(request, "admin", real_role=True)
    return audience_labelling.backfill(relabel_ai=body.relabel_ai)


# --- statement labels ----------------------------------------------------------


@router.get("/api/statements/{statement_id}/audiences")
def statement_audiences_http(
    statement_id: str, request: Request
) -> tools.StatementAudiences:
    return tools.statement_audiences(statement_id, _require_principal(request))


class CuratorLabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audiences: list[str] = Field(max_length=50)
    reason: str = Field(default="", max_length=500)


@router.put("/api/statements/{statement_id}/audiences")
def set_statement_audiences_http(
    statement_id: str, body: CuratorLabelBody, request: Request
) -> tools.StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.set_curator_label(
        statement_id,
        body.audiences,
        body.reason,
        curator=_require_principal(request).id,
    )
    return tools.statement_audiences(statement_id, _require_principal(request))


@router.post("/api/statements/{statement_id}/audiences/confirm")
def confirm_statement_audiences_http(
    statement_id: str, request: Request
) -> tools.StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.confirm_curator_label(
        statement_id, curator=_require_principal(request).id
    )
    return tools.statement_audiences(statement_id, _require_principal(request))


@router.delete("/api/statements/{statement_id}/audiences")
def clear_statement_audiences_http(
    statement_id: str, request: Request
) -> tools.StatementAudiences:
    _enforce_role(request, "writer", real_role=True)
    audience_labelling.clear_curator_label(statement_id)
    return tools.statement_audiences(statement_id, _require_principal(request))


# --- filter --------------------------------------------------------------------


@router.get("/api/audiences/statements")
def labelled_statements_http(
    request: Request,
    audience: str | None = None,
    visibility: store.audience_labels.Visibility | None = None,
    state: store.audience_labels.LabelState | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> tools.LabelledStatements:
    """Statements by what an audience sees and by label state."""
    return tools.labelled_statements(
        _require_principal(request),
        audience=audience,
        visibility=visibility,
        state=state,
        offset=offset,
        limit=limit,
    )


# --- pending external grants ---------------------------------------------------


@router.get("/api/audiences/{audience_id}/pending")
def pending_grants_http(audience_id: str, request: Request) -> tools.PendingGrants:
    """The audience's grants waiting for a curator, grouped by concept."""
    return tools.pending_grants(audience_id, _require_principal(request))


@router.get("/api/audiences/{audience_id}/pending/sample")
def pending_sample_http(audience_id: str, request: Request) -> tools.PendingSample:
    """A fresh random sample of the audience's pending grants, stratified by
    concept."""
    _require_principal(request)
    return tools.pending_sample(audience_id)


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement_ids: list[str] = Field(min_length=1, max_length=2000)
    decision: Literal["confirm", "reject"]


@router.post("/api/audiences/{audience_id}/pending/decide")
def decide_pending_http(
    audience_id: str, body: DecideBody, request: Request
) -> tools.Decided:
    _enforce_role(request, "writer", real_role=True)
    return tools.decide_pending(
        audience_id,
        body.statement_ids,
        body.decision,
        _require_principal(request).id,
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


@router.get("/api/audiences/spot-checks")
def spot_checks_http(request: Request) -> tools.SpotChecks:
    """Recently edited statements whose confirmed external grants stayed in force."""
    return tools.spot_checks(_require_principal(request))


class SpotCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirm", "narrow"]


@router.post("/api/statements/{statement_id}/audiences/spot-check")
def decide_spot_check_http(
    statement_id: str, body: SpotCheckBody, request: Request
) -> tools.Decided:
    _enforce_role(request, "writer", real_role=True)
    return tools.decide_spot_check(
        statement_id, body.decision, _require_principal(request).id
    )
