"""Deciding a draft: approve it, approve it with corrections, reject it, ask
a person, or reopen a rejected one.

The web app's routes and the `review_draft` and `reopen_draft` tools reach the
same functions, so a decision has one effect whichever way it arrives and is
logged with who made it. The draft-review setting only decides who reviews
automatically; a real writer or admin can decide under any setting.
"""

from __future__ import annotations

import sqlite3
from typing import Literal, NotRequired, TypedDict

from pydantic import JsonValue, TypeAdapter

from .. import auth as _auth
from .. import drafts_store, store
from ..draft_review_store import Correction
from ..drafts_store import DecisionNote, Evidence
from .draft_application import approve_draft
from .drafts import _identified_principal
from .registry import tool
from .runtime import _drafts_db

Verdict = Literal["approve", "approve_with_corrections", "reject", "needs_context"]

_corrections = TypeAdapter(list[Correction])
_evidence = TypeAdapter(list[Evidence])

MAX_REASON = 6000
MAX_QUESTION = 2000


class DraftDecision(TypedDict):
    draft_id: str
    status: str
    #: Applied and skipped operations and their results, after an approval.
    applied: NotRequired[int]
    skipped: NotRequired[int]
    results: NotRequired[list[dict[str, JsonValue]]]


def _draft(draft_id: str) -> sqlite3.Row:
    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    return row


def _text(value: str | None, name: str, limit: int) -> str:
    text = (value or "").strip()
    if not text or len(text) > limit:
        raise ValueError(f"{name} must be 1 to {limit} characters")
    return text


def reject(draft_id: str, note: DecisionNote) -> None:
    """Close an open or submitted draft without applying it."""
    conn = _drafts_db()
    with store.transaction(conn):
        row = _draft(draft_id)
        if drafts_store.status_for(row) not in ("open", "submitted"):
            raise ValueError("only open or submitted drafts can be rejected")
        drafts_store.set_decision(conn, draft_id, decision="rejected", by=note["by"])
        drafts_store.record_decision(conn, draft_id, "rejected", note)


def reopen(draft_id: str, note: DecisionNote) -> None:
    """Return a rejected draft to `submitted` so it can be decided again,
    unless applying it now would overwrite knowledge written after it."""
    from .. import draft_review_runs

    with store.write_lock():
        if drafts_store.status_for(_draft(draft_id)) != "rejected":
            raise ValueError("only rejected drafts can be reopened")
        if newer := draft_review_runs.newer_knowledge(draft_id):
            raise ValueError(f"the draft cannot be reopened: {newer}")
        conn = _drafts_db()
        with store.transaction(conn):
            drafts_store.reopen(conn, draft_id)
            drafts_store.record_decision(conn, draft_id, "reopened", note)


def ask(draft_id: str, question: str, note: DecisionNote) -> None:
    """Leave a submitted draft waiting on a person's answer, filed as a
    knowledge gap naming the draft."""
    conn = _drafts_db()
    with store.transaction(conn):
        if drafts_store.status_for(_draft(draft_id)) != "submitted":
            raise ValueError("only submitted drafts can wait on a question")
        drafts_store.record_decision(conn, draft_id, "needs_context", note)
    substrate = store.substrate_connection()
    with store.transaction(substrate):
        store.create_knowledge_gap(
            substrate,
            f"Draft {draft_id} needs context: {question}",
            draft_id=draft_id,
        )


def _decidable_by(principal: _auth.Principal, row: sqlite3.Row) -> None:
    if row["created_by"] == principal.id:
        raise _auth.RoleRequired(
            f"draft '{row['id']}' was created by you; another writer or admin "
            "decides it"
        )


@tool(role="writer", real_role=True)
def review_draft(
    draft_id: str,
    verdict: Verdict,
    expected_revision: int,
    reason: str | None = None,
    corrections: list[Correction] | None = None,
    question: str | None = None,
    evidence: list[Evidence] | None = None,
) -> DraftDecision:
    """Decide a submitted draft you did not create, as a curator does in the
    web app, whatever the automatic draft-review setting is.

    - `approve` applies the draft as it is.
    - `approve_with_corrections` makes `corrections` (the reviewer's precise
      shape: edit, add_link, drop_link, drop_statement, strike, append;
      indices and @ references name the draft as submitted) and applies the
      corrected draft. Nothing changes if a correction does not fit or the
      corrected draft still has operation findings.
    - `reject` closes it unapplied; `reason` is required.
    - `needs_context` leaves it submitted and files `question` as a knowledge
      gap naming the draft, for a person.

    `expected_revision` is the draft `revision` you checked (from
    `get_draft`); a draft changed since is refused. An approval is refused
    when a record it changes was rewritten after the draft was written.
    `reason` (why) and `evidence` (what you checked in the product, as in
    `set_operation_evidence`) are recorded with your decision in the draft's
    `decisions`. Use `list_drafts` to find the queue.
    """
    principal = _identified_principal()
    row = _draft(draft_id)
    _decidable_by(principal, row)
    if drafts_store.status_for(row) != "submitted":
        raise ValueError(
            f"draft '{draft_id}' is {drafts_store.status_for(row)}; only "
            "submitted drafts can be decided"
        )
    if int(row["revision"]) != expected_revision:
        raise drafts_store.StaleDraftRevisionError(
            f"draft '{draft_id}' is at revision {row['revision']}, not "
            f"{expected_revision}; read it again with get_draft"
        )
    chosen = _corrections.validate_python(corrections or [])
    if (verdict == "approve_with_corrections") != bool(chosen):
        raise ValueError(
            "approve_with_corrections needs corrections, and only it takes them"
        )
    if (verdict == "needs_context") != (question is not None):
        raise ValueError("needs_context needs a question, and only it takes one")
    if verdict == "reject" and reason is None:
        raise ValueError("reject needs a reason")
    note = drafts_store.decision_note(
        principal.id,
        reason=None if reason is None else _text(reason, "reason", MAX_REASON),
        evidence=_evidence.validate_python(evidence or []),
        corrections=chosen,
    )
    if verdict == "reject":
        reject(draft_id, note)
        return {"draft_id": draft_id, "status": "rejected"}
    if verdict == "needs_context":
        ask(draft_id, _text(question, "question", MAX_QUESTION), note)
        return {"draft_id": draft_id, "status": "submitted"}
    return _approve(draft_id, principal, chosen, note)


def _approve(
    draft_id: str,
    principal: _auth.Principal,
    corrections: list[Correction],
    note: DecisionNote,
) -> DraftDecision:
    from .. import draft_review_runs

    with store.write_lock():
        if newer := draft_review_runs.newer_knowledge(draft_id):
            raise ValueError(f"the draft cannot be approved: {newer}")
        if corrections:
            replay = draft_review_runs.approve_corrected(
                draft_id, corrections, principal, note
            )
        else:
            replay = approve_draft(draft_id, decided_by=principal.id, note=note)
    return {
        "draft_id": draft_id,
        "status": "approved",
        "applied": replay["applied"],
        "skipped": replay["skipped"],
        "results": replay["results"],
    }


@tool(role="writer", real_role=True)
def reopen_draft(draft_id: str, reason: str) -> DraftDecision:
    """Return a rejected draft you did not create to `submitted`, so it can be
    decided again with `review_draft`; the automatic reviewer's rejections
    included. `reason` says why and is recorded in the draft's `decisions`.
    Refused when a record the draft changes was rewritten after the draft was
    written: such a draft has to be submitted again against current
    knowledge."""
    principal = _identified_principal()
    _decidable_by(principal, _draft(draft_id))
    reopen(
        draft_id,
        drafts_store.decision_note(
            principal.id, reason=_text(reason, "reason", MAX_REASON)
        ),
    )
    return {"draft_id": draft_id, "status": "submitted"}
