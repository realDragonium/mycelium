"""The curation work queue over MCP: outside agents claim knowledge-health
items, check them in the product's code, and release them with the outcome.

Proposals go through the caller's draft, so nothing lands without review; the
queue only decides who works on what and remembers what came of it (see
`mycelium.curation`). Answering a reviewer's question and closing a gap are a
curator's decisions, so they take a real writer, as they do for a person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, TypedDict

from pydantic import Field, JsonValue, TypeAdapter

from .. import auth as _auth
from .. import (
    curation,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    media,
    store,
)
from .registry import tool
from .runtime import _db, _drafts_db
from .search import search_statements
from .vocabulary import list_link_types

#: Statements offered with each item as its nearest neighbours.
NEIGHBOURS = 5
_json_rows = TypeAdapter(list[dict[str, JsonValue]])
_evidence = TypeAdapter(list[drafts_store.Evidence])


class Neighbour(TypedDict):
    id: str
    kind: str
    text: str
    score: float


class Question(TypedDict):
    """What the draft reviewer asked a person, for a `question` item."""

    draft_id: str
    draft_title: str | None
    #: The review attempt that asked; answering refers to it.
    run_id: str
    questions: list[str]
    rationale: str | None


class WorkItem(TypedDict):
    #: A statement id, or a knowledge gap id for `rephrase` and `gap`.
    id: str
    kind: curation.Kind
    #: The statement's text, or the gap's.
    text: str
    #: The statement the item is about, with the concepts it names.
    statement: dict[str, JsonValue] | None
    neighbours: list[Neighbour]
    #: For a `question` item: the review waiting for an answer.
    question: Question | None


class WorkBatch(TypedDict):
    kind: curation.Kind
    items: list[WorkItem]
    #: Items of this kind you already held, whose lease this call extended.
    renewed: list[str]
    expires_at: str
    link_types: list[dict[str, JsonValue]]


class Released(TypedDict):
    released: list[str]
    outcome: curation.Outcome


def _claimant() -> str:
    principal = _auth.current_principal.get()
    return principal.id if principal is not None else _auth.LOCAL_ADMIN_ID


def _question(gap_id: str) -> Question | None:
    gap = store.get_knowledge_gap(_db(), gap_id)
    draft_id = None if gap is None else gap["draft_id"]
    if draft_id is None:
        return None
    run = draft_review_store.latest(_drafts_db(), draft_id)
    draft = drafts_store.get_draft(_drafts_db(), draft_id)
    if run is None or draft is None:
        return None
    return {
        "draft_id": draft_id,
        "draft_title": draft["title"],
        "run_id": run.run_id,
        "questions": run.questions,
        "rationale": run.rationale,
    }


def _neighbours(item: curation.Candidate) -> list[Neighbour]:
    hits = search_statements(item.text, limit=NEIGHBOURS + 1)
    own = {item.id, item.statement.id if item.statement else item.id}
    return [
        Neighbour(
            id=str(hit["id"]),
            kind=str(hit["kind"]),
            text=str(hit["text"]),
            score=round(float(hit["score"]), 3),
        )
        for hit in hits
        if hit["id"] not in own
    ][:NEIGHBOURS]


@tool(role="drafter")
def claim_curation_work(
    kind: curation.Kind,
    limit: Annotated[int, Field(ge=0, le=curation.MAX_BATCH)] = 5,
) -> WorkBatch:
    """Claim a batch of curation work for 30 minutes, to check in the
    product's code what the knowledge base alone cannot settle.

    `kind` picks the knowledge-health list: `isolated` (statements with no
    links), `unnamed` (statements naming no concept), `rephrase` (gaps asking
    for a statement to be rephrased), `gap` (other open knowledge gaps) or
    `question` (a draft reviewer's questions for a person, with the draft
    and the questions in `question`).
    Items nobody holds, no undecided draft covers, and nobody has looked at
    since they or the statements around them last changed come first, in id
    order. Each carries its text, the statement it is about with the concepts
    it names, and its nearest statements; `link_types` is the vocabulary
    with each type's direction.

    Each call also extends your lease on every item of `kind` you still hold
    (`limit=0` only renews). Propose what you find through your draft, attach
    `set_operation_evidence` to each operation, submit the draft, then
    `release_curation_work`. An item whose lease runs out is offered again.
    """
    claimant = _claimant()
    with store.transaction(_db()):
        chosen, renewed, expires = curation.claim(
            _db(),
            _drafts_db(),
            kind,
            limit=limit,
            claimant=claimant,
            now=datetime.now(UTC),
        )
    items: list[WorkItem] = []
    for candidate in chosen:
        neighbours = _neighbours(candidate)
        with store.transaction(_db()):
            curation.offered(_db(), candidate.id, [n["id"] for n in neighbours])
        items.append(
            {
                "id": candidate.id,
                "kind": kind,
                "text": candidate.text,
                "statement": (
                    None
                    if candidate.statement is None
                    else candidate.statement.model_dump(mode="json")
                ),
                "neighbours": neighbours,
                "question": _question(candidate.id) if kind == "question" else None,
            }
        )
    return {
        "kind": kind,
        "items": items,
        "renewed": renewed,
        "expires_at": expires,
        "link_types": _json_rows.validate_python(list_link_types()),
    }


_CURATOR_OUTCOMES = frozenset({"answered", "resolved", "not_applicable"})


@tool(role="drafter")
def release_curation_work(
    item_ids: list[str],
    outcome: curation.Outcome,
    draft_id: str | None = None,
    reason: Annotated[str | None, Field(max_length=300)] = None,
    answer: Annotated[str | None, Field(max_length=6000)] = None,
    evidence: Annotated[
        list[drafts_store.Evidence] | None, Field(max_length=drafts_store.MAX_EVIDENCE)
    ] = None,
) -> Released:
    """Release items you claimed, saying what came of them.

    `proposed`: your draft `draft_id` proposes a link, a concept or a
    rephrase for them; a gap is resolved when that draft is applied.
    `no_link`: you checked and nothing should change; give a short `reason`.
    Neither is offered again until the item or the statements around it
    change. `skipped`: you did not get to them; they are offered again.

    These take a real writer or admin, as they do for a person:
    `answered` (one `question` item): your `answer` to the reviewer's
    questions with the `evidence` you checked, in `set_operation_evidence`'s
    shape (one to five items); the draft is reviewed again with it. Not for
    a draft you created. `resolved` (gaps): the applied draft `draft_id`
    settled it; the gap is resolved. `not_applicable` (gaps): nothing should
    change, for the `reason` you give; the gap is dismissed.
    """
    claimant = _claimant()
    principal = _auth.current_principal.get()
    if outcome in _CURATOR_OUTCOMES:
        if principal is None or not _auth.principal_has_real_role(principal, "writer"):
            raise _auth.RoleRequired(
                f"releasing as {outcome} takes a real writer or admin, as a "
                "person's gap decision does"
            )
    if outcome != "answered" and (answer is not None or evidence is not None):
        raise ValueError("only an answered outcome takes an answer and evidence")
    if outcome == "proposed":
        if draft_id is None:
            raise ValueError("a proposed outcome needs the draft_id proposing it")
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None or row["created_by"] != claimant:
            raise ValueError(f"draft '{draft_id}' is not one of yours")
    elif outcome == "resolved":
        if draft_id is None:
            raise ValueError("a resolved outcome needs the applied draft_id")
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None or drafts_store.status_for(row) != "approved":
            raise ValueError(f"draft '{draft_id}' has not been applied")
    elif draft_id is not None:
        raise ValueError(f"a {outcome} outcome takes no draft_id")
    reason = (reason or "").strip() or None
    if outcome in ("no_link", "not_applicable") and reason is None:
        raise ValueError(f"a {outcome} outcome needs a short reason")
    if outcome == "answered":
        assert principal is not None
        draft_id = _answer(item_ids, principal, answer, evidence)
    with store.transaction(_db()):
        released = curation.release(
            _db(),
            item_ids,
            outcome,
            claimant=_claimant(),
            now=datetime.now(UTC),
            reason=reason,
            draft_id=draft_id,
        )
    return {"released": released, "outcome": outcome}


def _answer(
    item_ids: list[str],
    principal: _auth.Principal,
    answer: str | None,
    evidence: list[drafts_store.Evidence] | None,
) -> str:
    """Answer the questions of the one held `question` item and start the
    draft's fresh review. Returns the draft's id."""
    if len(set(item_ids)) != 1:
        raise ValueError("answer one question item at a time")
    [gap_id] = set(item_ids)
    curation.held_kinds(_db(), [gap_id], principal.id, "answered")
    text = (answer or "").strip()
    if not text:
        raise ValueError("an answered outcome needs the answer")
    if not evidence:
        raise ValueError(
            "an answer needs evidence: what you checked in the product's code, "
            "UI or docs, in set_operation_evidence's shape"
        )
    question = _question(gap_id)
    if question is None:
        raise ValueError("the reviewer no longer waits for this answer")
    draft = drafts_store.get_draft(_drafts_db(), question["draft_id"])
    if draft is not None and draft["created_by"] == principal.id:
        raise ValueError(
            "you created this draft; its reviewer's questions are for someone else"
        )
    draft_review_runs.answer(
        question["draft_id"],
        question["run_id"],
        text,
        principal,
        media.describe_evidence(_evidence.validate_python(evidence)),
    )
    return question["draft_id"]
