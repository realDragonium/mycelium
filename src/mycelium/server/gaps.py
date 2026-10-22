"""Recording knowledge an agent looked for and could not find.

`report_knowledge_gap` is a write any reader may make: the gap is a note for a
person to act on, not knowledge, so it skips the draft redirect and the writer
role. The documentation loop calls it in-process for the same reason.
"""

from __future__ import annotations

from typing import Any

from .. import store
from .registry import tool
from .runtime import _db


@tool(role="reader")
def report_knowledge_gap(text: str) -> dict[str, Any]:
    """Flag a gap, inconsistency, or unclear area in the knowledge base
    for a human curator to review.

    Free-form text body; the reporter writes whatever's most useful —
    a missing topic, a contradiction between two statements, an entity
    that looks incomplete, a typo, a stale claim. If the report
    references a specific entity or statement, include the id in the
    text so the reviewer can jump to it.

    Open reports surface in the UI's Gaps page until a human marks
    them resolved or dismissed; nothing is auto-pruned.

    Returns the assigned `gap_id`.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is required")

    with store.transaction(_db()):
        gap_id = store.create_knowledge_gap(_db(), text)
    return {"gap_id": gap_id}
