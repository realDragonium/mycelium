"""Audiences and statement audience labels over every transport.

Reads are open to any caller. Configuring audiences and running the labelling
backfill are a real admin's; a curator's label decisions (setting, confirming
or clearing a label, deciding pending external grants and spot checks) need a
real writer. The web app's audience routes call these same functions, which
record each decision as the caller's.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import (
    audience_labelling,
    audiences,
    auth,
    grant_confirmation,
    product_settings,
    store,
)
from .registry import tool
from .runtime import _caller, _db


class AudiencesResponse(audiences.AudiencesView):
    labelling: audience_labelling.Status


def audiences_view(principal: auth.Principal) -> AudiencesResponse:
    view = audiences.view(principal, _db())
    return AudiencesResponse(
        **view.model_dump(), labelling=audience_labelling.status(_db())
    )


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


def statement_audiences(
    statement_id: str, principal: auth.Principal
) -> StatementAudiences:
    conn = _db()
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


def labelled_statements(
    principal: auth.Principal,
    *,
    audience: str | None,
    visibility: store.audience_labels.Visibility | None,
    state: store.audience_labels.LabelState | None,
    offset: int,
    limit: int,
) -> LabelledStatements:
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be at least 0 and limit between 1 and 200")
    chosen = None
    if visibility is not None:
        chosen = next((item for item in audiences.live() if item.id == audience), None)
        if chosen is None:
            raise ValueError("Choose a live audience to filter by visibility.")
    conn = _db()
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


class PendingGrants(BaseModel):
    audience_id: str
    total: int
    groups: list[grant_confirmation.PendingGroup]
    can_curate: bool
    sample_size: int
    min_sample_precision_percent: int


def pending_grants(audience_id: str, principal: auth.Principal) -> PendingGrants:
    audience = grant_confirmation.live_audience(audience_id)
    groups = grant_confirmation.groups(_db(), audience.id)
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


def pending_sample(audience_id: str) -> PendingSample:
    audience = grant_confirmation.live_audience(audience_id)
    limits = product_settings.get(product_settings.AudienceLabellingSettings)
    return PendingSample(
        groups=grant_confirmation.sample(_db(), audience.id, limits.sample_size)
    )


class SpotChecks(BaseModel):
    statements: list[grant_confirmation.SpotCheck]
    can_curate: bool


def spot_checks(principal: auth.Principal) -> SpotChecks:
    return SpotChecks(
        statements=grant_confirmation.spot_checks(_db()),
        can_curate=auth.principal_has_real_role(principal, "writer"),
    )


AudiencesRead = Literal[
    "audiences", "statement", "statements", "pending", "pending_sample", "spot_checks"
]


def _audience_id(audience_id: str | None) -> str:
    if audience_id is None:
        raise ValueError("Give the audience_id.")
    return audience_id


@tool
def get_audiences(
    view: AudiencesRead = "audiences",
    audience_id: str | None = None,
    statement_id: str | None = None,
    visibility: store.audience_labels.Visibility | None = None,
    state: store.audience_labels.LabelState | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, JsonValue]:
    """Read audiences and statement audience labels, as Settings → Audiences
    and the Audiences screen show them.

    `audiences`: every audience with its scope, description, `version`,
    includes and counts, and the labelling backfill's progress.
    `statement`: one statement's label (`statement_id`) and which audiences
    see it. `statements`: statements by label `state` (unlabelled, ai,
    curator, text_changed, pending, queued) and, with a live `audience_id`,
    by `visibility` (visible or hidden) to it; page with `offset` and
    `limit` (1 to 200). `pending`: an audience's external grants waiting
    for a curator, grouped by concept. `pending_sample`: a fresh random
    sample of them, to judge before accepting the rest. `spot_checks`:
    edited statements whose confirmed external grants stayed in force."""
    return _read(
        view, audience_id, statement_id, visibility, state, offset, limit
    ).model_dump(mode="json")


def _read(
    view: AudiencesRead,
    audience_id: str | None,
    statement_id: str | None,
    visibility: store.audience_labels.Visibility | None,
    state: store.audience_labels.LabelState | None,
    offset: int,
    limit: int,
) -> BaseModel:
    principal = _caller()
    if view == "audiences":
        return audiences_view(principal)
    if view == "statement":
        if statement_id is None:
            raise ValueError("Give the statement_id.")
        return statement_audiences(statement_id, principal)
    if view == "statements":
        return labelled_statements(
            principal,
            audience=audience_id,
            visibility=visibility,
            state=state,
            offset=offset,
            limit=limit,
        )
    if view == "pending":
        return pending_grants(_audience_id(audience_id), principal)
    if view == "pending_sample":
        return pending_sample(_audience_id(audience_id))
    return spot_checks(principal)


class CreateAudience(audiences.CreateAudience):
    action: Literal["create"]


class SaveAudience(audiences.SaveAudience):
    action: Literal["save"]
    audience_id: str


class RetireAudience(audiences.RetireAudience):
    model_config = ConfigDict(extra="forbid")
    action: Literal["retire"]
    audience_id: str


class Backfill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["backfill"]
    #: Also relabel statements the AI already labelled.
    relabel_ai: bool = False


AudienceChange = Annotated[
    CreateAudience | SaveAudience | RetireAudience | Backfill,
    Field(discriminator="action"),
]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_audience_change: TypeAdapter[AudienceChange] = TypeAdapter(AudienceChange)


class AudienceSaved(BaseModel):
    id: str | None = None
    retired: bool | None = None
    backfill: audience_labelling.Backfill | None = None


@tool(role="admin", real_role=True)
def manage_audiences(request: AudienceChange) -> dict[str, JsonValue]:
    """Configure audiences as Settings → Audiences does. Real admins only.

    `create` (name, scope internal or external, description, includes,
    optional id) adds an audience; `save` (audience_id, the same fields and
    the `version` from `get_audiences` as `revision`) edits one or restores
    a retired one; `retire` (audience_id, revision) retires one; `backfill`
    queues every unlabelled statement, and with `relabel_ai` the AI-labelled
    ones too, for the AI labeller."""
    request = _audience_change.validate_python(request)
    return _manage(request).model_dump(mode="json", exclude_none=True)


def _manage(request: AudienceChange) -> AudienceSaved:
    principal = _caller()
    if isinstance(request, Backfill):
        return AudienceSaved(
            backfill=audience_labelling.backfill(relabel_ai=request.relabel_ai)
        )
    # The domain functions take the web app's request bodies, which forbid
    # the fields only this tool adds.
    body = request.model_dump(exclude={"action", "audience_id"})
    if isinstance(request, CreateAudience):
        created = audiences.create(audiences.CreateAudience(**body), principal)
        return AudienceSaved(id=created.id)
    if isinstance(request, SaveAudience):
        saved = audiences.save(
            request.audience_id, audiences.SaveAudience(**body), principal
        )
        return AudienceSaved(id=saved.id)
    audiences.retire(request.audience_id, audiences.RetireAudience(**body), principal)
    return AudienceSaved(retired=True)


class SetLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["set_label"]
    statement_id: str
    audiences: list[str] = Field(max_length=50)
    reason: str = Field(default="", max_length=500)


class ConfirmLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm_label"]
    statement_id: str


class ClearLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["clear_label"]
    statement_id: str


class DecideSpotCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["spot_check"]
    statement_id: str
    decision: Literal["confirm", "narrow"]


class DecidePending(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["decide_pending"]
    audience_id: str
    statement_ids: list[str] = Field(min_length=1, max_length=2000)
    decision: Literal["confirm", "reject"]


class AcceptRest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept_rest"]
    audience_id: str
    #: The statement ids of the sample the curator judged.
    sample: list[str] = Field(min_length=1, max_length=500)


AudienceCuration = Annotated[
    SetLabel | ConfirmLabel | ClearLabel | DecideSpotCheck | DecidePending | AcceptRest,
    Field(discriminator="action"),
]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_audience_curation: TypeAdapter[AudienceCuration] = TypeAdapter(AudienceCuration)


class Decided(BaseModel):
    decided: int


def decide_pending(
    audience_id: str,
    statement_ids: list[str],
    decision: Literal["confirm", "reject"],
    curator: str,
) -> Decided:
    return Decided(
        decided=grant_confirmation.decide(
            audience_id,
            statement_ids,
            confirm=decision == "confirm",
            curator=curator,
        )
    )


def decide_spot_check(
    statement_id: str, decision: Literal["confirm", "narrow"], curator: str
) -> Decided:
    return Decided(
        decided=int(
            grant_confirmation.decide_spot_check(
                statement_id, confirm=decision == "confirm", curator=curator
            )
        )
    )


@tool(role="writer", real_role=True)
def curate_audiences(request: AudienceCuration) -> dict[str, JsonValue]:
    """Make a curator's audience decisions, recorded as the caller's, as the
    Audiences screen does. Real writers and admins only.

    On one statement: `set_label` (audiences, reason) replaces its label with
    a curator's; `confirm_label` confirms the AI's label as it is;
    `clear_label` drops the curator's label so the AI labels it again
    (these three return the statement's audiences); `spot_check` (decision
    confirm or narrow) keeps or withdraws the external grants an edit kept.
    On an audience's pending external grants: `decide_pending`
    (audience_id, statement_ids, decision confirm or reject), or
    `accept_rest` (audience_id, the `sample` judged), which confirms the
    rest when the sample's precision meets the saved minimum."""
    request = _audience_curation.validate_python(request)
    return _curate(request).model_dump(mode="json")


def _curate(request: AudienceCuration) -> BaseModel:
    principal = _caller()
    if isinstance(request, DecidePending):
        return decide_pending(
            request.audience_id, request.statement_ids, request.decision, principal.id
        )
    if isinstance(request, AcceptRest):
        return grant_confirmation.accept_rest(
            request.audience_id, request.sample, curator=principal.id
        )
    if isinstance(request, DecideSpotCheck):
        return decide_spot_check(request.statement_id, request.decision, principal.id)
    if isinstance(request, SetLabel):
        audience_labelling.set_curator_label(
            request.statement_id,
            request.audiences,
            request.reason,
            curator=principal.id,
        )
    elif isinstance(request, ConfirmLabel):
        audience_labelling.confirm_curator_label(
            request.statement_id, curator=principal.id
        )
    else:
        audience_labelling.clear_curator_label(request.statement_id)
    return statement_audiences(request.statement_id, principal)
