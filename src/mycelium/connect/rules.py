"""Propose typed links from lexical cues in new statement text.

Mention overlap is a hard resolution filter when a target phrase names an entity,
not a selector on its own; embeddings rank only candidates that pass that filter.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from .funnel import (
    RELATED_THRESHOLD,
    BatchStatement,
    FunnelResult,
    SubstrateView,
    candidates_for,
)
from .patterns import CueMatch, find_cues

RESOLVE_THRESHOLD = RELATED_THRESHOLD
RESOLVE_THRESHOLD_UNANCHORED = 0.75
TARGET_NEIGHBOURS_K = 10

#: The instance's shipped rule set — pattern name -> kinds it may fire for
#: (None = any kind). Derived from docs/reports/2026-08-15-link-pattern-hit-rate.md;
#: see that file's "Reading the result".
SHIPPED_PATTERNS: dict[str, frozenset[str] | None] = {
    # Selection criterion (from the report's by-pattern table): statement precision
    # >= 50% with >= 3 statements fired, OR precision >= 30% with >= 4 link hits;
    # kind-restricted to where the report shows the signal.
    "configures-capability": frozenset({"capability"}),  # 26/29 (89.7%), 55 link hits
    # 33/86 (38.4%) overall, but the signal is the capability subset; elsewhere ~12%.
    "configures-configured-on": frozenset({"capability"}),
    "composes-formula": frozenset({"rule"}),  # 6/12 (50.0%), 21 link hits
    "restricts-limits": None,  # 2/2 (100.0%), 8 link hits
    "restricts-state": frozenset({"state"}),  # 5/6 (83.3%)
    "proceeds-redirected": frozenset({"event"}),  # 3/9 (33.3%), 4 link hits
    # Not shipped: establishes-event-state (1/2) and proceeds-then (1/2) fire on two
    # statements each — too thin; composes-determined-by (27.3%) and composes-combines
    # (22.2%) miss the precision criterion, as do all 0%-precision patterns and every
    # pattern whose link type has no ground truth in this snapshot.
}


@dataclass(frozen=True)
class LinkProposal:
    """Describe one typed link inferred from a lexical cue."""

    new_index: int
    target: str
    link_type: str
    pattern: str
    cue: str
    target_text: str | None
    score: float
    anchored: bool


class _Resolved(NamedTuple):
    """One target a cue phrase resolved to, before the compatibility matrix."""

    target: str
    score: float
    shared: frozenset[str]
    kind: str


def shipped_cues(
    text: str,
    kind: str,
    shipped: Mapping[str, frozenset[str] | None] = SHIPPED_PATTERNS,
) -> list[CueMatch]:
    """Find cues admitted by the shipped pattern and kind selection."""
    return [
        cue
        for cue in find_cues(text, kind)
        if cue.pattern in shipped
        and (shipped[cue.pattern] is None or kind in shipped[cue.pattern])
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity, treating zero vectors as unrelated."""
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return sum(left * right for left, right in zip(a, b, strict=False)) / (
        norm_a * norm_b
    )


def _eligible(
    phrase_entities: frozenset[str],
    shared: frozenset[str],
    score: float,
    resolve_threshold: float,
    unanchored_threshold: float,
) -> bool:
    """Apply anchored or embedding-only resolution thresholds."""
    if phrase_entities:
        return bool(shared) and score >= resolve_threshold
    return score >= unanchored_threshold


def _resolve_in_batch(
    statement: BatchStatement,
    batch: list[BatchStatement],
    funnel: FunnelResult,
    phrase_entities: frozenset[str],
    phrase_vec: list[float],
    resolve_threshold: float,
    unanchored_threshold: float,
) -> list[_Resolved]:
    """Rank eligible batch targets for one target phrase."""
    ranked: list[tuple[int, float, frozenset[str], str]] = []
    for target in batch:
        if target.index == statement.index:
            continue
        target_vec = funnel.embeddings.get(target.index)
        if target_vec is None:
            continue
        shared = phrase_entities & funnel.entities.get(target.index, frozenset())
        score = _cosine(phrase_vec, target_vec)
        if _eligible(
            phrase_entities,
            shared,
            score,
            resolve_threshold,
            unanchored_threshold,
        ):
            ranked.append((target.index, score, shared, target.kind))
    # Sort on the integer index, not the "@n" label, so ties break numerically.
    ranked.sort(key=lambda candidate: (-candidate[1], candidate[0]))
    return [
        _Resolved(f"@{index}", score, shared, kind)
        for index, score, shared, kind in ranked
    ]


def _resolve_in_substrate(
    statement: BatchStatement,
    funnel: FunnelResult,
    view: SubstrateView,
    phrase_entities: frozenset[str],
    phrase_vec: list[float],
    sharing: dict[str, frozenset[str]],
    resolve_threshold: float,
    unanchored_threshold: float,
    k: int,
) -> list[_Resolved]:
    """Union and rank eligible substrate targets for one target phrase."""
    neighbour_scores = dict(view.neighbours(phrase_vec, k))
    candidate_ids = (
        set(neighbour_scores)
        | set(sharing)
        | {
            candidate.statement_id
            for candidate in candidates_for(funnel, statement.index)
        }
    )
    resolved: list[_Resolved] = []
    for statement_id in candidate_ids:
        score = neighbour_scores.get(statement_id)
        if score is None:
            score = view.similarity(phrase_vec, statement_id)
        if score is None:
            continue
        shared = phrase_entities & sharing.get(statement_id, frozenset())
        if not _eligible(
            phrase_entities,
            shared,
            score,
            resolve_threshold,
            unanchored_threshold,
        ):
            continue
        kind = view.kind_of(statement_id)
        if kind is not None:
            resolved.append(_Resolved(statement_id, score, shared, kind))
    resolved.sort(key=lambda candidate: (-candidate.score, candidate.target))
    return resolved


def _pick(
    candidates: list[_Resolved],
    source_kind: str,
    link_type: str,
    view: SubstrateView,
) -> _Resolved | None:
    """Pick the best candidate whose kind pair admits the proposed type."""
    for candidate in candidates:
        if link_type in view.admissible_link_types(source_kind, candidate.kind):
            return candidate
    return None


def propose_links(
    batch: list[BatchStatement],
    funnel: FunnelResult,
    view: SubstrateView,
    *,
    shipped: Mapping[str, frozenset[str] | None] = SHIPPED_PATTERNS,
    resolve_threshold: float = RESOLVE_THRESHOLD,
    unanchored_threshold: float = RESOLVE_THRESHOLD_UNANCHORED,
    k: int = TARGET_NEIGHBOURS_K,
) -> list[LinkProposal]:
    """Resolve shipped lexical cues batch-first and propose admissible links.

    Each nonblank target phrase is embedded and mention-resolved once. Eligible batch
    siblings are ranked before the compatibility matrix is applied. The substrate is
    consulted only when the batch has no eligible target at all.
    """
    phrase_cache: dict[
        str, tuple[frozenset[str], list[float], dict[str, frozenset[str]]]
    ] = {}
    proposals: dict[tuple[int, str, str], LinkProposal] = {}
    for statement in batch:
        for cue in shipped_cues(statement.text, statement.kind, shipped):
            if not cue.target_text:
                continue
            if cue.target_text not in phrase_cache:
                phrase_entities = view.entities_in(cue.target_text)
                sharing = (
                    view.statements_sharing(phrase_entities) if phrase_entities else {}
                )
                phrase_cache[cue.target_text] = (
                    phrase_entities,
                    view.embed(cue.target_text),
                    sharing,
                )
            phrase_entities, phrase_vec, sharing = phrase_cache[cue.target_text]
            candidates = _resolve_in_batch(
                statement,
                batch,
                funnel,
                phrase_entities,
                phrase_vec,
                resolve_threshold,
                unanchored_threshold,
            )
            if not candidates:
                candidates = _resolve_in_substrate(
                    statement,
                    funnel,
                    view,
                    phrase_entities,
                    phrase_vec,
                    sharing,
                    resolve_threshold,
                    unanchored_threshold,
                    k,
                )
            winner = _pick(candidates, statement.kind, cue.link_type, view)
            if winner is None:
                continue
            # Keep the no-self-link invariant explicit at the emission boundary.
            if winner.target == f"@{statement.index}":
                continue
            proposal = LinkProposal(
                new_index=statement.index,
                target=winner.target,
                link_type=cue.link_type,
                pattern=cue.pattern,
                cue=cue.cue,
                target_text=cue.target_text,
                score=winner.score,
                anchored=bool(winner.shared),
            )
            key = (proposal.new_index, proposal.target, proposal.link_type)
            previous = proposals.get(key)
            if previous is None or proposal.score > previous.score:
                proposals[key] = proposal
    return list(proposals.values())
