"""Recording knowledge an agent looked for and could not find.

`report_knowledge_gap` is a write any reader may make: the gap is a note for a
person to act on, not knowledge, so it skips the draft redirect and the writer
role. The documentation loop calls it in-process for the same reason.
"""

from __future__ import annotations

from typing import Any

from .. import docs_store, drafts_store, store
from .registry import tool
from .runtime import _db, _drafts_db


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
