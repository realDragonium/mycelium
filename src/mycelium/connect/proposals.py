"""Pure proposal normalization for connected statement batches.

Only one merge may survive per new statement because replay deletes its source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .funnel import FunnelResult
from .nli import PairVerdict
from .rules import LinkProposal


@dataclass(frozen=True)
class Proposal:
    kind: str
    new_index: int
    target: str
    link_type: str | None
    provenance: dict[str, Any]
    #: Link proposals only: the edge's source ref. The frame's phrase role
    #: decides which endpoint is the cue carrier, so this is not always
    #: `@new_index`. None for merge and conflict proposals.
    source: str | None = None


@dataclass(frozen=True)
class ProposalSet:
    proposals: list[Proposal]
    dropped_merges: list[Proposal]
    suppressed_conflicts: int = 0


def _label_provenance(verdict: PairVerdict) -> dict[str, Any]:
    """Convert an NLI verdict into stable JSON-shaped provenance."""
    return {
        "source": "nli",
        "score": verdict.score,
        "forward": {
            "label": verdict.forward.label,
            "confidence": verdict.forward.confidence,
        },
        "backward": {
            "label": verdict.backward.label,
            "confidence": verdict.backward.confidence,
        },
    }


def _link_proposals(links: list[LinkProposal]) -> list[Proposal]:
    """Deduplicate rule proposals while preserving their ranked order."""
    seen: set[tuple[str, str, str]] = set()
    proposals: list[Proposal] = []
    for link in links:
        key = (link.source, link.target, link.link_type)
        if key in seen:
            continue
        seen.add(key)
        proposals.append(
            Proposal(
                kind="link",
                new_index=link.new_index,
                target=link.target,
                link_type=link.link_type,
                provenance={
                    "source": "rule",
                    "pattern": link.pattern,
                    "cue": link.cue,
                    "phrase": link.phrase,
                    "score": link.score,
                    "link_type": link.link_type,
                },
                source=link.source,
            )
        )
    return proposals


def _machine_proposals(
    funnel: FunnelResult, verdicts: list[PairVerdict] | None
) -> tuple[list[Proposal], list[Proposal], int]:
    """Build merge and conflict proposals from the available machine pass."""
    if verdicts is None:
        merges = [
            Proposal(
                kind="merge",
                new_index=candidate.new_index,
                target=candidate.statement_id,
                link_type=None,
                provenance={"source": "similarity", "score": candidate.score},
            )
            for candidate in funnel.candidates
            if candidate.relation == "duplicate"
        ]
        return merges, [], 0

    shared_entities = {
        (candidate.new_index, candidate.statement_id): candidate.shared_entities
        for candidate in funnel.candidates
    }
    merges: list[Proposal] = []
    conflicts: list[Proposal] = []
    suppressed_conflicts = 0
    for verdict in verdicts:
        if verdict.verdict not in {"duplicate", "contradiction"}:
            continue
        if verdict.verdict == "contradiction" and not shared_entities.get(
            (verdict.new_index, verdict.statement_id)
        ):
            suppressed_conflicts += 1
            continue
        proposal = Proposal(
            kind="merge" if verdict.verdict == "duplicate" else "conflict",
            new_index=verdict.new_index,
            target=verdict.statement_id,
            link_type=None,
            provenance=_label_provenance(verdict),
        )
        if proposal.kind == "merge":
            merges.append(proposal)
        else:
            conflicts.append(proposal)
    return merges, conflicts, suppressed_conflicts


def _merge_rank(proposal: Proposal) -> tuple[float, float, str]:
    """Rank merges by score, NLI confidence, then target id."""
    forward = proposal.provenance.get("forward", {})
    backward = proposal.provenance.get("backward", {})
    confidence = float(forward.get("confidence", 0.0)) + float(
        backward.get("confidence", 0.0)
    )
    return (-float(proposal.provenance["score"]), -confidence, proposal.target)


def _select_merges(merges: list[Proposal]) -> tuple[list[Proposal], list[Proposal]]:
    """Keep the highest-ranked merge for each new statement."""
    by_index: dict[int, list[Proposal]] = {}
    index_order: list[int] = []
    for proposal in merges:
        if proposal.new_index not in by_index:
            by_index[proposal.new_index] = []
            index_order.append(proposal.new_index)
        by_index[proposal.new_index].append(proposal)

    kept: list[Proposal] = []
    dropped: list[Proposal] = []
    for new_index in index_order:
        ranked = sorted(by_index[new_index], key=_merge_rank)
        kept.append(ranked[0])
        dropped.extend(ranked[1:])
    return kept, dropped


def proposals_from(
    *,
    funnel: FunnelResult,
    links: list[LinkProposal],
    verdicts: list[PairVerdict] | None,
) -> ProposalSet:
    """Normalize rule, similarity, and NLI outputs into ordered proposals."""
    link_proposals = _link_proposals(links)
    merge_candidates, conflicts, suppressed_conflicts = _machine_proposals(
        funnel, verdicts
    )
    merges, dropped_merges = _select_merges(merge_candidates)
    return ProposalSet(
        link_proposals + merges + conflicts,
        dropped_merges,
        suppressed_conflicts,
    )
