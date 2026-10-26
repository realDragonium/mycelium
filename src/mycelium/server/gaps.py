"""Knowledge gaps: recording knowledge an agent looked for and could not
find, and the Gaps page's list and status changes.

`report_knowledge_gap` is a write any reader may make: the gap is a note for a
person to act on, not knowledge, so it skips the draft redirect and the writer
role. The documentation loop calls it in-process for the same reason. Changing
a gap's status takes a real writer, as on the Gaps page, whose routes call
these same functions.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, TypeGuard, get_args

from .. import auth, docs_store, drafts_store, store
from .registry import tool
from .runtime import _caller, _db, _drafts_db

GapStatus = Literal["all", "open", "resolved", "dismissed"]
GapAction = Literal["resolve", "dismiss", "reopen"]


def is_gap_status(value: str) -> TypeGuard[GapStatus]:
    return value in get_args(GapStatus)


def is_gap_action(value: str) -> TypeGuard[GapAction]:
    return value in get_args(GapAction)


@tool(role="reader")
def report_knowledge_gap(
    text: str,
    statement_id: str | None = None,
    draft_id: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Flag a gap, inconsistency, or unclear area in the knowledge base
    for a human curator to review.

    Free-form text body; the reporter writes whatever's most useful —
    a missing topic, a contradiction between two statements, an entity
    that looks incomplete, a typo, a stale claim.

    When the report is about a specific statement, draft or generated
    document, pass its id as `statement_id`, `draft_id` or `document_id`:
    the Gaps page links to it, and a report about a draft is resolved
    when that draft is applied. Each id must exist. Name anything else
    (an entity, a second statement) in the text.

    Open reports surface in the UI's Gaps page until a human marks
    them resolved or dismissed; nothing is auto-pruned.

    Returns the assigned `gap_id`.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is required")
    if statement_id is not None and store.get_statement(_db(), statement_id) is None:
        raise ValueError(f"statement '{statement_id}' not found")
    if draft_id is not None and drafts_store.get_draft(_drafts_db(), draft_id) is None:
        raise ValueError(f"draft '{draft_id}' not found")
    if (
        document_id is not None
        and docs_store.get_document(_drafts_db(), document_id) is None
    ):
        raise ValueError(f"document '{document_id}' not found")

    with store.transaction(_db()):
        gap_id = store.create_knowledge_gap(
            _db(),
            text,
            draft_id=draft_id,
            statement_id=statement_id,
            document_id=document_id,
        )
    return {"gap_id": gap_id}


def _serialize_gap(row: sqlite3.Row) -> dict[str, Any]:
    if row["resolved_at"]:
        status = "resolved"
    elif row["dismissed_at"]:
        status = "dismissed"
    else:
        status = "open"
    return {
        "id": row["id"],
        "text": row["text"],
        "status": status,
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
        "dismissed_at": row["dismissed_at"],
        "dismissed_by": row["dismissed_by"],
        "draft_id": row["draft_id"],
        "statement_id": row["statement_id"],
        "document_id": row["document_id"],
        "closing_reason": row["closing_reason"],
    }


@tool
def list_knowledge_gaps(status: GapStatus = "all") -> dict[str, Any]:
    """List knowledge gap reports, newest first, as the Gaps page does:
    `open`, `resolved`, `dismissed` or `all`. Each gap has its text, status,
    who reported and closed it, the statement, draft or document it is
    about and the reason it was closed. `can_write` says whether the caller
    may change a gap's status."""
    rows = store.list_knowledge_gaps(_db(), status=status)
    return {
        "gaps": [_serialize_gap(r) for r in rows],
        "can_write": auth.principal_has_real_role(_caller(), "writer"),
    }


@tool(role="writer", real_role=True)
def update_knowledge_gap(gap_id: str, action: GapAction) -> dict[str, Any]:
    """Resolve, dismiss or reopen a knowledge gap, recorded as the caller's,
    as the Gaps page does. Real writers and admins only. Returns the gap."""
    conn = _db()
    if store.get_knowledge_gap(conn, gap_id) is None:
        raise LookupError("gap not found")
    with store.transaction(conn):
        updated = store.set_knowledge_gap_status(conn, gap_id, action, _caller().id)
    return {"gap": _serialize_gap(updated)}
