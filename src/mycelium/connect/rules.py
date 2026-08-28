"""Propose typed links from lexical cues in new statement text.

Mention overlap is a hard resolution filter when a target phrase names an entity,
not a selector on its own; embeddings rank only candidates that pass that filter.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
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
#: (None = any kind). Derived from the original selection in
#: docs/reports/2026-08-15-link-pattern-hit-rate.md and revised by the alias-aware
#: docs/reports/2026-08-27-link-pattern-hit-rate.md run.
SHIPPED_PATTERNS: dict[str, frozenset[str] | None] = {
    # Selection criterion (from the report's by-pattern table): statement precision
    # >= 50% with >= 3 statements fired, OR precision >= 30% with >= 4 link hits;
    # kind-restricted to where the report shows the signal.
    "configures-capability": frozenset({"capability"}),  # 26/29 (89.7%), 55 link hits
    # 33/86 (38.4%) overall, but the signal is the capability subset; elsewhere ~12%.
    "configures-configured-on": frozenset({"capability"}),
    "composes-formula": frozenset({"rule"}),  # 6/12 (50.0%), 21 link hits
    # Alias-aware restricts-limits: 2/2 -> 6/9 (66.7%), 8 -> 12 link hits, once
    # seeded restricts vocabulary reached the bare slot; rule 2/2, state 4/5,
    # capability 0/2. Its state fires duplicate restricts-state-covered statements.
    # Bare disabled / locked / frozen / read-only / limit stays for restricts-state's
    # framed slot; restricts-limits' rule restriction makes them inert outside rule on
    # the bare slot.
    "restricts-limits": frozenset({"rule"}),
    "restricts-state": frozenset({"state"}),  # 5/6 (83.3%)
    # Carved out of restricts-state's shipped live phrasing: the passive agent
    # already fired there, but with the edge direction reversed.
    "restricts-state-by": frozenset({"state"}),
    "proceeds-redirected": frozenset({"event"}),  # 3/9 (33.3%), 4 link hits
    # Not shipped: establishes-event-state (1/2) is too thin; proceeds-then is
    # undecidable between proceeds and triggers (2 event fires: 1 outgoing proceeds,
    # 1 outgoing triggers); composes-determined-by (27.3%) and composes-combines
    # (22.2%) miss the precision criterion, as do all 0%-precision patterns and every
    # pattern whose link type has no ground truth in this snapshot. The alias-aware
    # 2026-08-27 run found zero governed-by-phrase fires across all 1644 statements
    # and no usable lexical surface on any of the 104 governed-by link endpoints, so
    # it stays unshipped rather than receiving a criterion exception.
    # Shipped outside the report (2026-08-20): the frame postdates the measured
    # catalog, so it has no ground truth either way. It exists so "X is a part
    # of Y" yields the edge the words state — Y contains X — rather than none.
    "contains-part-of": None,
    # Shipped outside the report: this frame postdates the measured catalog, so
    # it has no ground truth either way and the next run scores it. "X belongs
    # to Y" yields Y contains X rather than no edge.
    "contains-belongs-to": None,
}


@dataclass(frozen=True)
class LinkProposal:
    """Describe one typed link inferred from a lexical cue.

    `source` and `target` are edge endpoint refs — "@n" for a batch statement
    or an existing statement id. One of them is always the cue carrier
    (`@new_index`); which one is decided by the frame's phrase role, so the
    words carry the direction.
    """

    new_index: int
    source: str
    target: str
    link_type: str
    pattern: str
    cue: str
    phrase: str | None
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
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> list[CueMatch]:
    """Find cues admitted by the shipped pattern and kind selection."""
    return [
        cue
        for cue in find_cues(text, kind, aliases)
        if cue.pattern in shipped
        and (shipped[cue.pattern] is None or kind in shipped[cue.pattern])
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity, treating zero vectors as unrelated."""
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    # strict: the norms use the full vectors, so a truncated dot product would
    # silently deflate the score instead of surfacing the dimension mismatch.
    return sum(left * right for left, right in zip(a, b, strict=True)) / (
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
    """Union and rank eligible substrate targets for one target phrase.

    Similarities and kinds are fetched in batches, so anchored recall stays uncapped
    without per-candidate substrate round trips.
    """
    neighbour_scores = dict(view.neighbours(phrase_vec, k))
    candidate_ids = (
        set(neighbour_scores)
        | set(sharing)
        | {
            candidate.statement_id
            for candidate in candidates_for(funnel, statement.index)
        }
    )
    unscored_ids = candidate_ids - set(neighbour_scores)
    similarity_scores = (
        view.similarity(phrase_vec, sorted(unscored_ids)) if unscored_ids else {}
    )
    eligible: list[tuple[str, float, frozenset[str]]] = []
    for statement_id in candidate_ids:
        score = neighbour_scores.get(statement_id)
        if score is None:
            score = similarity_scores.get(statement_id)
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
        eligible.append((statement_id, score, shared))
    kinds = view.kinds_of(sorted(statement_id for statement_id, _, _ in eligible))
    resolved = [
        _Resolved(statement_id, score, shared, kinds[statement_id])
        for statement_id, score, shared in eligible
        if statement_id in kinds
    ]
    resolved.sort(key=lambda candidate: (-candidate.score, candidate.target))
    return resolved


def _pick(
    candidates: list[_Resolved],
    statement_kind: str,
    link_type: str,
    view: SubstrateView,
    *,
    phrase_role: str,
) -> _Resolved | None:
    """Pick the best candidate whose kind pair admits the proposed type.

    The matrix is directional: the resolved candidate fills the frame's
    phrase slot, so it is the edge's source when that slot is "from".
    """
    for candidate in candidates:
        from_kind, to_kind = (
            (candidate.kind, statement_kind)
            if phrase_role == "from"
            else (statement_kind, candidate.kind)
        )
        if link_type in view.admissible_link_types(from_kind, to_kind):
            return candidate
    return None


def propose_links(
    batch: list[BatchStatement],
    funnel: FunnelResult,
    view: SubstrateView,
    *,
    shipped: Mapping[str, frozenset[str] | None] = SHIPPED_PATTERNS,
    aliases: Mapping[str, Sequence[str]] | None = None,
    resolve_threshold: float = RESOLVE_THRESHOLD,
    unanchored_threshold: float = RESOLVE_THRESHOLD_UNANCHORED,
    k: int = TARGET_NEIGHBOURS_K,
) -> list[LinkProposal]:
    """Resolve shipped lexical cues batch-first and propose admissible links.

    Each nonblank target phrase is embedded and mention-resolved once. Eligible batch
    siblings are ranked before the compatibility matrix is applied. The substrate is
    consulted when the batch yields no admissible target, so an admissible sibling wins
    the tier rather than one that merely resolved.
    """
    phrase_cache: dict[
        str, tuple[frozenset[str], list[float], dict[str, frozenset[str]]]
    ] = {}
    proposals: dict[tuple[str, str, str], LinkProposal] = {}
    for statement in batch:
        for cue in shipped_cues(statement.text, statement.kind, shipped, aliases):
            if not cue.phrase:
                continue
            if cue.phrase not in phrase_cache:
                phrase_entities = view.entities_in(cue.phrase)
                sharing = (
                    view.statements_sharing(phrase_entities) if phrase_entities else {}
                )
                phrase_cache[cue.phrase] = (
                    phrase_entities,
                    view.embed(cue.phrase),
                    sharing,
                )
            phrase_entities, phrase_vec, sharing = phrase_cache[cue.phrase]
            batch_candidates = _resolve_in_batch(
                statement,
                batch,
                funnel,
                phrase_entities,
                phrase_vec,
                resolve_threshold,
                unanchored_threshold,
            )
            winner = _pick(
                batch_candidates,
                statement.kind,
                cue.link_type,
                view,
                phrase_role=cue.phrase_role,
            )
            if winner is None:
                substrate_candidates = _resolve_in_substrate(
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
                winner = _pick(
                    substrate_candidates,
                    statement.kind,
                    cue.link_type,
                    view,
                    phrase_role=cue.phrase_role,
                )
            if winner is None:
                continue
            # Keep the no-self-link invariant explicit at the emission boundary.
            if winner.target == f"@{statement.index}":
                continue
            carrier = f"@{statement.index}"
            source, target = (
                (winner.target, carrier)
                if cue.phrase_role == "from"
                else (carrier, winner.target)
            )
            proposal = LinkProposal(
                new_index=statement.index,
                source=source,
                target=target,
                link_type=cue.link_type,
                pattern=cue.pattern,
                cue=cue.cue,
                phrase=cue.phrase,
                score=winner.score,
                anchored=bool(winner.shared),
            )
            # Edge identity ignores which sibling carried the cue, so the
            # same edge found from both ends keeps only the higher score.
            key = (source, target, proposal.link_type)
            previous = proposals.get(key)
            if previous is None or proposal.score > previous.score:
                proposals[key] = proposal
    return list(proposals.values())
