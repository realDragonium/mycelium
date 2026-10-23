"""The activity feed: recent knowledge changes, newest first.

Reads the transactional audit log when one is attached, and otherwise falls
back to the live tables' timestamps, which cannot see deletes.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from .. import principal_audience, store
from .access import _require_principal

router = APIRouter()


_ALLOWED_OPS = {
    "create",
    "update",
    "delete",
    "link",
    "unlink",
    "attach",
    "detach",
}
_ALLOWED_KINDS = {
    "entity",
    "statement",
    "name",
    "statement_link",
    "entity_link",
    "entity_statement_link",
}


def _csv_set(raw: str | None, allowed: set[str]) -> set[str]:
    if not raw:
        return set()
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return parts & allowed


# The audit log addresses `statement_link` / `entity_statement_link` rows by
# their numeric `link_id`, keeping the endpoints in the before/after payload.
# The activity feed (and the UI's `describeTarget`) instead address links by a
# pipe-delimited composite of their endpoints. `entity_link` already records
# that composite as its target_id, so it needs no rebuild. Fields here mirror
# the `after`/`before` payloads written by `store/links.py` and
# `store/entity_links.py`.
_LINK_TARGET_FIELDS = {
    "statement_link": ("from_id", "to_id", "link_type"),
    "entity_statement_link": ("entity_id", "statement_id", "direction", "link_type"),
}


def _history_target_id(
    target_kind: str, target_id: str, payload: dict[str, Any] | None
) -> str:
    """Present a link event's target by its endpoints, matching the feed's
    pre-audit contract. Non-link kinds (and link kinds whose payload is
    missing a field) pass their stored `target_id` through unchanged."""
    fields = _LINK_TARGET_FIELDS.get(target_kind)
    if fields is None or payload is None:
        return target_id
    parts = [payload.get(f) for f in fields]
    if any(p is None for p in parts):
        return target_id
    return "|".join(str(p) for p in parts)


@router.get("/api/history")
def get_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    op: str | None = None,
    target_kind: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Recent knowledge changes, newest first.

    Read from the attached transactional audit log
    (`history.history_events`) when one is present — so deletes, unlinks,
    and every superseded update are included, each with `before`/`after`
    context. Only when no history DB is attached (history disabled) does
    this fall back to reconstructing events from the live tables'
    `created_at`/`updated_at`, which cannot see deletes.

    Each event has `event_id`, `at`, `op`, `target_kind`, `target_id`,
    `actor`, and — on the audit-log path — `before`/`after`/`context`
    snapshots. The UI resolves richer detail for surviving rows from the
    `/api/data` snapshot; the `before` snapshot is what a future UI step
    will use to show a deleted row's old content (not yet rendered).

    Query params:
      - op: comma-separated subset of
        {create,update,delete,link,unlink,attach,detach}
      - target_kind: comma-separated subset of the target kinds
      - q: case-insensitive substring match on target_id

    A caller scoped to an audience sees only events about statements,
    concepts and names its audience may see now, without their
    `before`/`after`/`context` snapshots: an old version of a visible
    statement may hold text its audience was never meant to read.
    """
    principal = _require_principal(request)
    with principal_audience.reads(principal):
        return _history(
            limit, offset, op, target_kind, q, scoped=principal.audience_id is not None
        )


def _history(
    limit: int,
    offset: int,
    op: str | None,
    target_kind: str | None,
    q: str | None,
    *,
    scoped: bool,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    ops = _csv_set(op, _ALLOWED_OPS)
    kinds = _csv_set(target_kind, _ALLOWED_KINDS)
    query = (q or "").strip()

    conn = store.substrate_connection()
    if store.has_history(conn):
        rows, total = store.history_feed(
            conn,
            limit=limit,
            offset=offset,
            ops=ops,
            kinds=kinds,
            query=query,
            visible_only=scoped,
        )
        events = []
        for r in rows:
            before = json.loads(r["before_json"]) if r["before_json"] else None
            after = json.loads(r["after_json"]) if r["after_json"] else None
            context = json.loads(r["context_json"]) if r["context_json"] else None
            if scoped:
                before = after = context = None
            events.append(
                {
                    "event_id": r["event_id"],
                    "at": r["at"],
                    "actor": r["actor"],
                    "op": r["op"],
                    "target_kind": r["target_kind"],
                    # The audit log keys link rows by numeric link_id, but the
                    # UI (and the pre-audit feed) address them by their
                    # endpoints. Rebuild the pipe-delimited composite so the
                    # feed's target_id stays stable across the reader switch.
                    "target_id": _history_target_id(
                        r["target_kind"], r["target_id"], after or before
                    ),
                    "before": before,
                    "after": after,
                    "context": context,
                }
            )
    else:
        rows, total = store.activity_feed(
            conn, limit=limit, offset=offset, ops=ops, kinds=kinds, query=query
        )
        events = [
            {
                "event_id": f"{r['target_kind']}:{r['target_id']}:{r['op']}:{r['at']}",
                "at": r["at"],
                "actor": r["actor"],
                "op": r["op"],
                "target_kind": r["target_kind"],
                "target_id": r["target_id"],
            }
            for r in rows
        ]
    return {"events": events, "total": total, "limit": limit, "offset": offset}
