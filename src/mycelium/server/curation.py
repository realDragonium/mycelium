"""The curation work queue over MCP: outside agents claim knowledge-health
items, check them in the product's code, and release them with the outcome.

Proposals go through the caller's draft, so nothing lands without review; the
queue only decides who works on what and remembers what came of it (see
`mycelium.curation`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, TypedDict

from pydantic import Field, JsonValue, TypeAdapter

from .. import auth as _auth
from .. import curation, drafts_store, store
from .registry import tool
from .runtime import _db, _drafts_db
from .search import search_statements
from .vocabulary import list_link_types

#: Statements offered with each item as its nearest neighbours.
NEIGHBOURS = 5
_json_rows = TypeAdapter(list[dict[str, JsonValue]])


class Neighbour(TypedDict):
    id: str
    kind: str
    text: str
    score: float


class WorkItem(TypedDict):
    #: A statement id, or a knowledge gap id for `rephrase` and `gap`.
    id: str
    kind: curation.Kind
    #: The statement's text, or the gap's.
    text: str
    #: The statement the item is about, with the concepts it names.
    statement: dict[str, JsonValue] | None
    neighbours: list[Neighbour]


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
    for a statement to be rephrased) or `gap` (other open knowledge gaps).
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
            }
        )
    return {
        "kind": kind,
        "items": items,
        "renewed": renewed,
        "expires_at": expires,
        "link_types": _json_rows.validate_python(list_link_types()),
    }


@tool(role="drafter")
def release_curation_work(
    item_ids: list[str],
    outcome: curation.Outcome,
    draft_id: str | None = None,
    reason: Annotated[str | None, Field(max_length=300)] = None,
) -> Released:
    """Release items you claimed, saying what came of them.

    `proposed`: your draft `draft_id` proposes a link, a concept or a
    rephrase for them; a gap is resolved when that draft is applied.
    `no_link`: you checked and nothing should change; give a short `reason`.
    Neither is offered again until the item or the statements around it
    change. `skipped`: you did not get to them; they are offered again.
    """
    if outcome == "proposed":
        if draft_id is None:
            raise ValueError("a proposed outcome needs the draft_id proposing it")
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None or row["created_by"] != _claimant():
            raise ValueError(f"draft '{draft_id}' is not one of yours")
    elif draft_id is not None:
        raise ValueError(f"a {outcome} outcome takes no draft_id")
    reason = (reason or "").strip() or None
    if outcome == "no_link" and reason is None:
        raise ValueError("a no_link outcome needs a short reason")
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
