"""Routing draftable tool calls onto a draft instead of the live substrate.

A tool is draftable by name: a mutation prefix makes its writes queueable, and
an entry in `_LIST_TOOL_KINDS` lets a list read show what a draft has queued.
Such a tool is registered with `draftable_tool` or `draft_listing_tool`, whose
wrapper consults this module before running the tool body, so a drafter's
writes land on their draft whichever transport they arrive on.
"""

from __future__ import annotations

import json as _json
import sqlite3
from typing import Any, TypedDict

from pydantic import JsonValue

from .. import store
from ..auth import Principal as AuthPrincipal
from .runtime import _drafts_db

# Prefixes that mark a tool as a substrate mutation. Tools whose name
# starts with one of these become "draftable": they accept an optional
# `draft_id` kwarg, and a drafter principal automatically routes them
# to a session-scoped draft instead of touching the substrate.
_MUTATION_PREFIXES = (
    "upsert_",
    "add_",
    "delete_",
    "remove_",
    "replace_",
    "patch_",
    "rename_",
    "move_",
    "merge_",
)


# List tools that have a natural "what's queued in this draft" view: when
# they're called with an explicit `draft_id`, the wrapper returns the
# draft's ops of matching kinds instead of hitting the substrate. The
# return shape is `list[dict]` either way; with draft_id, each dict is
# the op payload plus `_seq` and `_kind` markers so callers can tell
# which queued op produced it.
#
# Get / search / discover tools aren't here on purpose — most have a
# single-item return shape, and matching by name/id against arbitrary
# op payloads gets fragile fast. Use `get_draft(draft_id)` if you need
# the full op list for one draft.
_LIST_TOOL_KINDS: dict[str, tuple[str, ...]] = {
    "list_statements": ("upsert_statement",),
    "list_entities": ("upsert_entity",),
    "list_link_types": ("upsert_link_type",),
    "list_entity_link_types": ("upsert_entity_link_type",),
    "list_statement_kinds": ("upsert_statement_kind",),
}


class DraftReceipt(TypedDict):
    """What a write redirected onto a draft returns in place of its result."""

    draft_id: str
    seq: int
    #: The queued op's stable reference, for `set_operation_evidence`.
    operation_ref: str
    queued: str
    revision: int


#: A queued op as a draft-listing read returns it: the op payload plus the
#: `_seq` / `_kind` markers that name the op it came from.
QueuedOp = dict[str, JsonValue]


def _require_draft_owner(principal: AuthPrincipal | None, row: sqlite3.Row) -> None:
    """Refuse a change to someone else's draft unless the caller curates.

    A curator approving a draft applies its ops as its creator's work, so an
    op slipped into another person's draft, or one struck from it, would be
    applied or lost under their name. Curators (real writers) edit any draft;
    no principal means an in-process or stdio call, which is trusted."""
    from .. import auth as _auth

    if principal is None or _auth.principal_has_real_role(principal, "writer"):
        return
    if row["created_by"] != principal.id:
        raise _auth.RoleRequired(
            f"draft '{row['id']}' belongs to another user; only its creator "
            "or a writer can change it"
        )


def auto_draft_session(principal: AuthPrincipal) -> str:
    """The key of the open draft a drafter's writes go onto without a
    `draft_id`: their MCP session, or the principal when there is none."""
    from .. import auth as _auth

    return _auth.current_session_id.get() or f"actor:{principal.id}"


def _resolve_draft_target(
    principal: AuthPrincipal | None, draft_id: str | None
) -> str | None:
    """Decide whether this tool call should be redirected to a draft.

    Returns the target draft_id, or None to mean 'execute against the
    substrate normally'. Three cases:

      1. Explicit `draft_id` from the caller — must reference an open
         draft. Raises if missing/non-open.
      2. Drafter principal, no explicit draft_id — find or create the
         session-scoped open draft. Requires a session id.
      3. Anything else — return None.
    """
    from .. import drafts_store

    if draft_id is not None:
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None:
            raise ValueError(f"draft_id '{draft_id}' not found")
        if drafts_store.status_for(row) != "open":
            raise ValueError(
                f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
                f"only open drafts accept new ops"
            )
        _require_draft_owner(principal, row)
        return draft_id

    if principal is not None and principal.role == "drafter":
        # Prefer the MCP session id when there is one (one auto-draft per
        # active conversation), and fall back to a principal-scoped key
        # when there isn't. The fallback is the common case, not the edge
        # one: the 2026-07-28 protocol has no sessions at all, many 2025
        # clients don't echo `Mcp-Session-Id` back on tool calls, and the
        # REST mirror never had one. Net effect: a drafter has at most one
        # open auto-draft at a time across all their clients, and must
        # submit it before another opens. A drafter who wants two at once
        # passes `draft_id` explicitly, which always wins over
        # auto-targeting.
        session_id = auto_draft_session(principal)
        row = drafts_store.find_open_session_draft(
            _drafts_db(), session_id, principal.id
        )
        if row is not None:
            open_draft_id: str = row["id"]
            return open_draft_id
        with store.transaction(_drafts_db()):
            return drafts_store.create_draft(
                _drafts_db(),
                created_by=principal.id,
                session_id=session_id,
            )

    return None


def _list_from_draft(draft_id: str, kinds: tuple[str, ...]) -> list[QueuedOp]:
    """Return queued ops in a draft whose kind is in `kinds`, each shaped
    as the op payload plus `_seq`/`_kind` markers so the caller can map
    items back to specific ops. Raises if the draft id doesn't resolve."""
    from .. import drafts_store

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft_id '{draft_id}' not found")
    ops = drafts_store.list_ops(_drafts_db(), draft_id)
    out: list[QueuedOp] = []
    for op in ops:
        if op["kind"] not in kinds:
            continue
        item: QueuedOp = {"_seq": op["seq"], "_kind": op["kind"]}
        item.update(_json.loads(op["payload_json"]))
        out.append(item)
    return out


def _queue_draft_op(
    draft_id: str, kind: str, payload: dict[str, Any], principal: AuthPrincipal | None
) -> DraftReceipt:
    """Append a queued op to the draft and return a JSON-friendly
    receipt. Used as the return value of the redirected tool call so the
    agent sees what happened instead of a normal substrate response."""
    from .. import drafts_store

    actor = principal.id if principal is not None else None
    # Drop None defaults so the stored payload only carries the args the
    # caller actually supplied — replay re-applies defaults at apply time.
    clean = {k: v for k, v in payload.items() if v is not None}
    with store.transaction(_drafts_db()):
        seq = drafts_store.add_op(
            _drafts_db(),
            draft_id=draft_id,
            kind=kind,
            payload=clean,
            created_by=actor,
        )
        revision = drafts_store.current_revision(_drafts_db(), draft_id)
        operation_ref = (
            _drafts_db()
            .execute(
                "SELECT id FROM draft_ops WHERE draft_id = ? AND seq = ?",
                (draft_id, seq),
            )
            .fetchone()[0]
        )
    return {
        "draft_id": draft_id,
        "seq": seq,
        "operation_ref": str(operation_ref),
        "queued": kind,
        "revision": revision,
    }
