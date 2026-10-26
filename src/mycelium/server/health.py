"""Knowledge health over every transport: the counts and lists the Knowledge
health screen shows, and an admin's freeing of stuck automatic work.

The web app's `/api/knowledge-health` routes call these same functions, so a
person and an agent read the same view and pass the same gates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import auth as _auth
from .. import (
    automation_stops,
    curation,
    documentation_planning,
    knowledge_health,
    model_settings,
    product_settings,
    store,
)
from .registry import tool
from .runtime import _auth_db, _db, _drafts_db


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
    #: How much knowledge there is, as Home shows it.
    substrate: store.SubstrateCounts
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
    for summary in curation.summaries(_db(), _drafts_db(), datetime.now(UTC)):
        holders = []
        for holder in summary.claims:
            if holder.claimed_by not in names:
                user = _auth.get_user(_auth_db(), holder.claimed_by)
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


def _connect() -> tuple[ConnectLimits | None, str | None]:
    try:
        limits = product_settings.get(product_settings.ConnectSettings)
        selected = model_settings.get("connect")
    except model_settings.Unavailable as exc:
        return None, str(exc)
    if reason := model_settings.credentials_error("connect"):
        return None, reason
    return (
        ConnectLimits(
            batch_size=limits.batch_size,
            max_run_tokens=limits.max_run_tokens,
            provider=selected.provider,
            model=selected.model,
            external_agent=selected.external_agent,
        ),
        None,
    )


def health_view() -> HealthView:
    connect, connect_error = _connect()
    return HealthView(
        counts=knowledge_health.counts(_db(), _drafts_db(), store.substrate_connection),
        substrate=store.substrate_counts(_db()),
        connect=connect,
        connect_error=connect_error,
        curation=_curation(),
        uncovered_by_profile=documentation_planning.uncovered_counts(
            _drafts_db(), _db()
        ),
        stopped=automation_stops.stops(_db()),
    )


def health_list(
    which: knowledge_health.Filter,
    *,
    after: str | None = None,
    limit: int = 50,
    to_connect: bool = False,
) -> knowledge_health.StatementPage | knowledge_health.EntityPage:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if which == "undescribed" or which == "unused":
        if to_connect:
            raise ValueError("to_connect applies to statement lists only")
        return knowledge_health.entities(_db(), which, after=after, limit=limit)
    if to_connect:
        return knowledge_health.to_connect(_db(), _drafts_db(), which, limit=limit)
    return knowledge_health.statements(
        _db(), _drafts_db(), which, after=after, limit=limit
    )


@tool(role="reader")
def get_knowledge_health(
    which: knowledge_health.Filter | None = None,
    after: str | None = None,
    limit: int = 50,
    to_connect: bool = False,
) -> dict[str, JsonValue]:
    """Read the Knowledge health screen.

    Without `which`: the counts of each kind of curation work, how much
    knowledge there is (`substrate`), whether the connect pass can run and
    its limits, who holds curation claims and what came of them, statements
    no document covers per writing profile, and `stopped`: automatic work
    that failed too often and waits for an admin (`unblock_automation`).

    With `which`, one page of that list: statements `isolated`,
    `unmentioned` (naming no concept) or `unlabelled` (no audience label),
    or concepts `undescribed` or `unused`. Pass `next_after` back as
    `after` for the next page; `limit` is 1 to 200. `to_connect` (statement
    lists only) returns the batch the connect pass would take next."""
    if which is None:
        return health_view().model_dump(mode="json")
    return health_list(
        which, after=after, limit=limit, to_connect=to_connect
    ).model_dump(mode="json")


class FreeClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["free_claims"]
    kind: curation.Kind
    claimed_by: str


class RetryStopped(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["retry_stopped"]
    kind: automation_stops.Kind
    item_id: str


Unblock = Annotated[FreeClaims | RetryStopped, Field(discriminator="action")]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_unblock: TypeAdapter[Unblock] = TypeAdapter(Unblock)


class Unblocked(BaseModel):
    #: Claims dropped, for `free_claims`.
    freed: int | None = None
    #: Whether the item was stopped and is now retried, for `retry_stopped`.
    retried: bool | None = None


def free_claims(kind: curation.Kind, claimed_by: str) -> int:
    with store.transaction(_db()):
        return curation.free(_db(), kind, claimed_by)


def retry_stopped(kind: automation_stops.Kind, item_id: str) -> bool:
    with store.transaction(_db()):
        return automation_stops.retry(_db(), kind, item_id)


@tool(role="admin", real_role=True)
def unblock_automation(request: Unblock) -> dict[str, JsonValue]:
    """Free work an agent abandoned, or retry automatic work that stopped.

    `{"action": "free_claims", "kind", "claimed_by"}` drops that holder's
    curation claims on `kind` without recording an attempt, so the items are
    offered again. `{"action": "retry_stopped", "kind", "item_id"}` clears a
    `stopped` entry `get_knowledge_health` lists, so the automation tries it
    again with a fresh failure count. Real admins only."""
    request = _unblock.validate_python(request)
    if isinstance(request, FreeClaims):
        result = Unblocked(freed=free_claims(request.kind, request.claimed_by))
    else:
        result = Unblocked(retried=retry_stopped(request.kind, request.item_id))
    return result.model_dump(mode="json", exclude_none=True)
