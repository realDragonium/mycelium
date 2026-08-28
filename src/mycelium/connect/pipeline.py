"""Orchestrate read-only connection discovery over an injected substrate view.

NLI unavailability degrades to similarity proposals without changing the funnel.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from mycelium.connect import nli
from mycelium.connect.funnel import (
    BatchStatement,
    FunnelResult,
    SubstrateView,
    find_candidates,
)
from mycelium.connect.nli import NliModel, NliUnavailable, PairVerdict
from mycelium.connect.rules import LinkProposal, propose_links

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NliPairs:
    classified: int
    skipped: int
    budget: int


@dataclass(frozen=True)
class PipelineResult:
    funnel: FunnelResult
    link_proposals: list[LinkProposal]
    verdicts: list[PairVerdict] | None
    nli: Literal["ran", "unavailable", "nothing_to_classify"]
    nli_reason: str | None
    nli_pairs: NliPairs


def run(
    batch: list[BatchStatement],
    view: SubstrateView,
    *,
    text_of: Callable[[str], str | None],
    nli_model: NliModel | None = None,
) -> PipelineResult:
    """Run candidate, rule, and optional NLI discovery without writing."""
    funnel = find_candidates(batch, view)
    link_proposals = propose_links(batch, funnel, view, aliases=view.aliases_by_type())
    pair_budget = nli.max_pairs()
    # Resolve text before budgeting so each candidate counted here costs two pairs.
    # The request-scoped reader is memoized, so classify_candidates can read it again.
    resolvable_candidates = [
        candidate
        for candidate in funnel.candidates
        if text_of(candidate.statement_id) is not None
    ]
    if not resolvable_candidates:
        return PipelineResult(
            funnel,
            link_proposals,
            [],
            "nothing_to_classify",
            None,
            NliPairs(classified=0, skipped=0, budget=pair_budget),
        )

    candidate_limit = pair_budget // 2
    classified_candidates = resolvable_candidates[:candidate_limit]
    skipped_pairs = 2 * (len(resolvable_candidates) - len(classified_candidates))
    try:
        model = nli_model if nli_model is not None else nli.default_model()
        verdicts = nli.classify_candidates(
            batch,
            classified_candidates,
            model,
            text_of=text_of,
        )
    except NliUnavailable as error:
        reason = str(error)
        logger.warning("NLI unavailable: %s", reason)
        return PipelineResult(
            funnel,
            link_proposals,
            None,
            "unavailable",
            reason,
            NliPairs(classified=0, skipped=skipped_pairs, budget=pair_budget),
        )
    classified_pairs = 2 * len(verdicts)
    return PipelineResult(
        funnel,
        link_proposals,
        verdicts,
        "ran",
        None,
        NliPairs(
            classified=classified_pairs,
            skipped=skipped_pairs,
            budget=pair_budget,
        ),
    )
