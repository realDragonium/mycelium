"""Documentation audiences, statement audience labels and the labelling backfill.

Reads need an authenticated caller. Audiences and the backfill are admin
configuration; a curator's label decision needs a real writer.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import audience_labelling, audiences, server, store, timestamps
from .access import _enforce_role, _require_principal

router = APIRouter()


async def _audience_conflict(request: Request, exc: audiences.Conflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


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
def labelling_status_http(
    request: Request, since: str | None = None
) -> audience_labelling.Status:
    _require_principal(request)
    return audience_labelling.status(server._db(), since=since)


class BackfillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relabel_ai: bool = False


class BackfillResponse(BaseModel):
    queued: int
    started_at: str


@router.post("/api/audiences/labelling/backfill")
def backfill_http(body: BackfillBody, request: Request) -> BackfillResponse:
    _enforce_role(request, "admin", real_role=True)
    started_at = timestamps.now()
    return BackfillResponse(
        queued=audience_labelling.backfill(relabel_ai=body.relabel_ai),
        started_at=started_at,
    )


# --- statement labels ----------------------------------------------------------


class Label(BaseModel):
    audiences: list[str]
    source: Literal["ai", "curator"]
    reason: str
    model: str | None
    labelled_at: str
    labelled_by: str | None


class AudienceVisibility(BaseModel):
    id: str
    name: str
    scope: audiences.Scope
    visible: bool


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
    )


def _statement_audiences(statement_id: str, request: Request) -> StatementAudiences:
    from .. import auth

    principal = _require_principal(request)
    conn = server._db()
    if store.get_statement(conn, statement_id) is None:
        raise ValueError(f"Statement {statement_id} does not exist.")
    row = store.audience_labels.get_label(conn, statement_id)
    granted = set(store.audience_labels.label_audiences(row)) if row else set()
    return StatementAudiences(
        statement_id=statement_id,
        label=_label(row),
        queued=conn.execute(
            "SELECT 1 FROM audience_label_queue WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()
        is not None,
        audiences=[
            AudienceVisibility(
                id=item.id,
                name=item.name,
                scope=item.scope,
                visible=item.id in granted if row else item.internal,
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


@router.get("/api/audiences/statements")
def labelled_statements_http(
    request: Request,
    audience: str | None = None,
    visibility: Literal["visible", "hidden"] | None = None,
    state: Literal["unlabelled", "ai", "curator", "queued"] | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> LabelledStatements:
    """Statements by what an audience sees and by label state."""
    _require_principal(request)
    conditions: list[str] = []
    params: list[str | int] = []
    if visibility is not None:
        chosen = next((item for item in audiences.live() if item.id == audience), None)
        if chosen is None:
            raise ValueError("Choose a live audience to filter by visibility.")
        clause, values = store.audience_labels.visibility_clause(
            chosen.id, chosen.internal
        )
        conditions.append(clause if visibility == "visible" else f"NOT {clause}")
        params.extend(values)
    if state == "unlabelled":
        conditions.append("l.statement_id IS NULL")
    elif state in ("ai", "curator"):
        conditions.append("l.source = ?")
        params.append(state)
    elif state == "queued":
        conditions.append("q.statement_id IS NOT NULL")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    base = (
        "FROM statements s LEFT JOIN statement_audience_labels l "
        "ON l.statement_id = s.id LEFT JOIN audience_label_queue q "
        f"ON q.statement_id = s.id {where}"
    )
    conn = server._db()
    total = int(conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT s.id, s.kind, s.text, q.statement_id AS queued {base} "
        "ORDER BY s.created_at DESC, s.id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
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
    )
