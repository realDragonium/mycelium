"""Rank existing statements surfaced by vector and materialized-mention lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

RELATED_THRESHOLD = 0.6
# Mirrors server.NEAR_DUPLICATE_THRESHOLD without importing the server into the core.
DUPLICATE_THRESHOLD = 0.85
DEFAULT_K = 10
DEFAULT_MAX_CANDIDATES = 20


@dataclass(frozen=True)
class BatchStatement:
    index: int
    kind: str
    text: str


class SubstrateView(Protocol):
    """The substrate reads the funnel needs, so the core stays pure."""

    def embed(self, text: str) -> list[float]: ...

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        """(statement_id, cosine similarity), best first, unresolvable ids dropped."""
        ...

    def similarity(self, vec: list[float], statement_id: str) -> float | None:
        """Cosine similarity to the statement's stored vector; None if it has none."""
        ...

    def entities_in(self, text: str) -> frozenset[str]:
        """Entity ids of the mentions derived from text."""
        ...

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        """statement_id -> the subset of entity_ids it mentions; {} for empty input."""
        ...

    def kind_of(self, statement_id: str) -> str | None: ...


@dataclass(frozen=True)
class Candidate:
    new_index: int
    statement_id: str
    kind: str
    score: float
    via: frozenset[str]
    shared_entities: frozenset[str]
    relation: str


@dataclass(frozen=True)
class FunnelResult:
    embeddings: dict[int, list[float]]
    entities: dict[int, frozenset[str]]
    candidates: list[Candidate]


RawCandidate = tuple[float, frozenset[str], frozenset[str]]


def _score_candidates(
    vec: list[float],
    entity_ids: frozenset[str],
    view: SubstrateView,
    k: int,
) -> dict[str, RawCandidate]:
    """Union vector and mention candidates with their available scores."""
    scored: dict[str, RawCandidate] = {
        statement_id: (score, frozenset({"vector"}), frozenset())
        for statement_id, score in view.neighbours(vec, k)
    }
    sharing = view.statements_sharing(entity_ids) if entity_ids else {}
    for statement_id, shared_entities in sharing.items():
        mention_score = view.similarity(vec, statement_id)
        if mention_score is None:
            continue
        previous = scored.get(statement_id)
        if previous is None:
            scored[statement_id] = (
                mention_score,
                frozenset({"mention"}),
                shared_entities,
            )
            continue
        # Maximum route score makes union results independent of discovery order.
        score, via, previous_entities = previous
        scored[statement_id] = (
            max(score, mention_score),
            via | {"mention"},
            previous_entities | shared_entities,
        )
    return scored


def _rank(
    raw: dict[str, RawCandidate],
    statement: BatchStatement,
    view: SubstrateView,
    related_threshold: float,
    duplicate_threshold: float,
    max_candidates: int,
) -> list[Candidate]:
    """Threshold, classify, rank, and cap candidates for one statement."""
    candidates: list[Candidate] = []
    for statement_id, (score, via, shared_entities) in raw.items():
        if score < related_threshold:
            continue
        kind = view.kind_of(statement_id)
        if kind is None:
            continue
        relation = (
            "duplicate"
            if kind == statement.kind and score >= duplicate_threshold
            else "related"
        )
        candidates.append(
            Candidate(
                new_index=statement.index,
                statement_id=statement_id,
                kind=kind,
                score=score,
                via=via,
                shared_entities=shared_entities,
                relation=relation,
            )
        )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.statement_id))
    return candidates[:max_candidates]


def find_candidates(
    batch: list[BatchStatement],
    view: SubstrateView,
    *,
    k: int = DEFAULT_K,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    related_threshold: float = RELATED_THRESHOLD,
    duplicate_threshold: float = DUPLICATE_THRESHOLD,
) -> FunnelResult:
    """Find ranked existing-statement candidates for every batch statement."""
    if duplicate_threshold < related_threshold:
        raise ValueError(
            "duplicate_threshold must be >= related_threshold "
            f"(got {duplicate_threshold} < {related_threshold})"
        )
    # embeddings, entities and Candidate.new_index all key off index, so a repeat
    # would silently drop one statement's results.
    indexes = [statement.index for statement in batch]
    if len(indexes) != len(set(indexes)):
        raise ValueError("batch statement indexes must be unique")

    embeddings: dict[int, list[float]] = {}
    entities: dict[int, frozenset[str]] = {}
    candidates: list[Candidate] = []
    for statement in batch:
        vec = view.embed(statement.text)
        entity_ids = view.entities_in(statement.text)
        embeddings[statement.index] = vec
        entities[statement.index] = entity_ids
        raw = _score_candidates(vec, entity_ids, view, k)
        candidates.extend(
            _rank(
                raw,
                statement,
                view,
                related_threshold,
                duplicate_threshold,
                max_candidates,
            )
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.new_index,
            -candidate.score,
            candidate.statement_id,
        )
    )
    return FunnelResult(embeddings, entities, candidates)


def candidates_for(result: FunnelResult, new_index: int) -> list[Candidate]:
    """Convenience filter: the candidates for one batch index, already ranked."""
    return [
        candidate for candidate in result.candidates if candidate.new_index == new_index
    ]
