"""The curation work queue over MCP: outside agents claim knowledge-health
items, check them in the product's code, and release them with the outcome.

Proposals go through the caller's draft, so nothing lands without review; the
queue only decides who works on what and remembers what came of it (see
`mycelium.curation`). Answering a reviewer's question and closing a gap are
recorded as the agent's, as a person's are; an answer needs the evidence the
agent checked, and closing a gap the draft or reason that settled it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, TypedDict

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import auth as _auth
from .. import (
    curation,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    media,
    product_settings,
    store,
)
from .names import find_entity_duplicates
from .registry import tool
from .runtime import _db, _drafts_db
from .search import find_duplicates, search_statements
from .vocabulary import list_link_types

#: Statements offered with each item as its nearest neighbours.
NEIGHBOURS = 5
_json_rows = TypeAdapter(list[dict[str, JsonValue]])
_json = TypeAdapter(dict[str, JsonValue])
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
    #: For a duplicate item: both candidates and their similarity evidence.
    pair: dict[str, JsonValue] | None
    #: For an undescribed or unused item: the concept and statements naming it.
    concept: dict[str, JsonValue] | None
    #: For a rephrase or gap item about a draft: the draft under discussion.
    draft: dict[str, JsonValue] | None


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


class _StatementDuplicate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    a_id: str
    a_text: str
    b_id: str
    b_text: str
    score: float


class _ConceptDuplicate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    a_entity_id: str
    b_entity_id: str
    score: float
    matches: list[dict[str, JsonValue]]


def _concept(
    entity_id: str, *, statement_limit: int = 8
) -> dict[str, JsonValue] | None:
    row = (
        _db()
        .execute(
            "SELECT e.description, n.text AS name FROM entities e "
            "LEFT JOIN names n ON n.id = COALESCE(e.preferred_name_id, "
            "(SELECT MIN(id) FROM names WHERE entity_id = e.id)) WHERE e.id = ?",
            (entity_id,),
        )
        .fetchone()
    )
    if row is None:
        return None
    names = [
        str(item[0])
        for item in _db().execute(
            "SELECT text FROM names WHERE entity_id = ? ORDER BY text COLLATE NOCASE, text",
            (entity_id,),
        )
    ]
    statements = [
        {"id": str(item[0]), "kind": str(item[1]), "text": str(item[2])}
        for item in _db().execute(
            "SELECT DISTINCT s.id, s.kind, s.text FROM statements s "
            "JOIN statement_mentions m ON m.statement_id = s.id "
            "JOIN names n ON n.id = m.name_id WHERE n.entity_id = ? "
            "ORDER BY s.id LIMIT ?",
            (entity_id, statement_limit),
        )
    ]
    return _json.validate_python(
        {
            "id": entity_id,
            "name": str(row["name"] or (names[0] if names else entity_id)),
            "names": names,
            "description": str(row["description"] or ""),
            "statements": statements,
        }
    )


STATEMENT_AUDIT_PAIRS = 2_000


def duplicate_candidates(
    *, limit: int = 200, exclude_skipped_by: str | None = None
) -> tuple[list[curation.DuplicateCandidate], dict[str, dict[str, JsonValue]]]:
    """Bounded index-backed duplicate candidates and their agent context."""
    candidates: list[curation.DuplicateCandidate] = []
    contexts: dict[str, dict[str, JsonValue]] = {}
    scores: dict[str, float] = {}
    now = datetime.now(UTC)
    page_size = 200
    # One audit walks every statement, so it runs once with a wide bound
    # rather than once per page.
    parsed: dict[str, _StatementDuplicate] = {}
    statement_candidates: list[curation.DuplicateCandidate] = []
    for raw_statement in find_duplicates(limit=STATEMENT_AUDIT_PAIRS):
        statement_pair = _StatementDuplicate.model_validate(raw_statement)
        a_id, b_id = sorted((statement_pair.a_id, statement_pair.b_id))
        item_id = f"{a_id}~{b_id}"
        text = curation.item_text(_db(), "duplicate", item_id)
        if text is not None:
            parsed[item_id] = statement_pair
            statement_candidates.append(curation.DuplicateCandidate(item_id, text))
    available = curation.available_duplicate_candidates(
        _db(),
        _drafts_db(),
        statement_candidates,
        limit=limit,
        now=now,
        exclude_skipped_by=exclude_skipped_by,
    )
    for candidate in available:
        statement_pair = parsed[candidate.id]
        a_id, b_id = candidate.id.split("~")
        sides: dict[str, dict[str, JsonValue]] = {}
        for statement_id in (a_id, b_id):
            row = store.get_statement(_db(), statement_id)
            if row is not None:
                sides[statement_id] = {
                    "id": statement_id,
                    "kind": str(row["kind"]),
                    "text": str(row["text"]),
                }
        if len(sides) != 2:
            continue
        candidates.append(candidate)
        scores[candidate.id] = statement_pair.score
        contexts[candidate.id] = _json.validate_python(
            {
                "kind": "statement",
                "a": sides[a_id],
                "b": sides[b_id],
                "score": statement_pair.score,
            }
        )

    concept_candidates: list[curation.DuplicateCandidate] = []
    offset = 0
    while len(concept_candidates) < limit:
        page = find_entity_duplicates(limit=page_size, offset=offset)
        parsed_concepts: dict[str, _ConceptDuplicate] = {}
        page_candidates = []
        for raw_concept in page["candidates"]:
            concept_pair = _ConceptDuplicate.model_validate(raw_concept)
            a_id, b_id = sorted((concept_pair.a_entity_id, concept_pair.b_entity_id))
            item_id = f"{a_id}~{b_id}"
            text = curation.item_text(_db(), "duplicate", item_id)
            if text is not None:
                parsed_concepts[item_id] = concept_pair
                page_candidates.append(curation.DuplicateCandidate(item_id, text))
        available = curation.available_duplicate_candidates(
            _db(),
            _drafts_db(),
            page_candidates,
            limit=limit - len(concept_candidates),
            now=now,
            exclude_skipped_by=exclude_skipped_by,
        )
        for candidate in available:
            concept_pair = parsed_concepts[candidate.id]
            a_id, b_id = candidate.id.split("~")
            a = _concept(a_id, statement_limit=3)
            b = _concept(b_id, statement_limit=3)
            if a is None or b is None:
                continue
            concept_candidates.append(candidate)
            scores[candidate.id] = concept_pair.score
            contexts[candidate.id] = _json.validate_python(
                {
                    "kind": "concept",
                    "a": a,
                    "b": b,
                    "score": concept_pair.score,
                    "matches": concept_pair.matches,
                }
            )
        offset += len(page["candidates"])
        if offset >= page["total"] or not page["candidates"]:
            break
    candidates.extend(concept_candidates)
    chosen = sorted(candidates, key=lambda item: (-scores[item.id], item.id))[:limit]
    return chosen, {item.id: contexts[item.id] for item in chosen}


def _draft(gap_id: str) -> dict[str, JsonValue] | None:
    gap = store.get_knowledge_gap(_db(), gap_id)
    draft_id = None if gap is None else gap["draft_id"]
    if draft_id is None:
        return None
    row = drafts_store.get_draft(_drafts_db(), str(draft_id))
    if row is None:
        return None
    review = draft_review_store.latest(_drafts_db(), str(draft_id))
    operations = _json_rows.validate_python(
        [
            {
                "operation_ref": str(op["id"]),
                "kind": str(op["kind"]),
                "payload": _json.validate_json(str(op["payload_json"])),
            }
            for op in drafts_store.list_ops(_drafts_db(), str(draft_id))[:30]
        ]
    )
    return _json.validate_python(
        {
            "draft_id": str(draft_id),
            "title": None if row["title"] is None else str(row["title"]),
            "status": drafts_store.status_for(row),
            "rationale": None if review is None else review.rationale,
            "operations": operations,
        }
    )


def describe_work_item(
    candidate: curation.Candidate,
    kind: curation.Kind,
    *,
    pair: dict[str, JsonValue] | None = None,
) -> WorkItem:
    """Build the same context for an internal or outside curation agent."""
    neighbours = _neighbours(candidate)
    with store.transaction(_db()):
        curation.offered(_db(), candidate.id, [item["id"] for item in neighbours])
    return {
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
        "pair": pair,
        "concept": (
            _concept(candidate.id) if kind in ("undescribed", "unused") else None
        ),
        "draft": _draft(candidate.id) if kind in ("rephrase", "gap") else None,
    }


@tool(role="drafter")
def claim_curation_work(
    kind: curation.Kind,
    limit: Annotated[int, Field(ge=0, le=curation.MAX_BATCH)] = 5,
) -> WorkBatch:
    """Claim a batch of curation work for 30 minutes, to check in the
    product's code what the knowledge base alone cannot settle.

    `kind` picks statements (`isolated`, `unnamed`), gaps (`rephrase`, `gap`,
    `question`), duplicate statement or concept pairs (`duplicate`), or
    concepts needing a decision (`undescribed`, `unused`). Kind-specific
    context is in `pair`, `concept`, `draft`, or `question`; draft-backed gaps
    include the rejected or applied draft an agent may correct or close.
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
    pairs: list[curation.DuplicateCandidate] = []
    pair_context: dict[str, dict[str, JsonValue]] = {}
    if kind == "duplicate" and limit:
        pairs, pair_context = duplicate_candidates()
    with store.transaction(_db()):
        chosen, renewed, expires = curation.claim(
            _db(),
            _drafts_db(),
            kind,
            limit=limit,
            claimant=claimant,
            now=datetime.now(UTC),
            pairs=pairs,
            follow_up_retries=product_settings.get(
                product_settings.ConnectSettings
            ).follow_up_retries,
            answer_retries=product_settings.get(
                product_settings.ReviewSettings
            ).answer_retries,
            skip_retries=product_settings.get(
                product_settings.ConnectSettings
            ).skip_retries,
        )
    items: list[WorkItem] = []
    for candidate in chosen:
        items.append(
            describe_work_item(candidate, kind, pair=pair_context.get(candidate.id))
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
    answer: Annotated[str | None, Field(max_length=6000)] = None,
    evidence: Annotated[
        list[drafts_store.Evidence] | None, Field(max_length=drafts_store.MAX_EVIDENCE)
    ] = None,
) -> Released:
    """Release items you claimed, saying what came of them.

    `proposed`: your draft `draft_id` proposes the change. `no_link`: an
    isolated/unnamed/undescribed/unused item should not change; give a reason.
    Neither is offered again until the item or the statements around it
    change. `skipped`: you did not get to them; they are offered again
    until skipped, or left to run out, more often than the limit.

    `answered` (one `question` item): your `answer` to the reviewer's
    questions with the `evidence` you checked, in `set_operation_evidence`'s
    shape (one to five items); the draft is reviewed again with it. Not for
    a draft you created. `resolved` (gaps): an applied draft settled it.
    `not_applicable` dismisses a gap or records that a duplicate pair is
    distinct; give a reason.
    """
    claimant = _claimant()
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
        principal = _auth.current_principal.get()
        if principal is None:
            raise _auth.RoleRequired("answering a reviewer takes an identified account")
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
            skip_retries=product_settings.get(
                product_settings.ConnectSettings
            ).skip_retries,
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
