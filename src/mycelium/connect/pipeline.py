"""Orchestrate read-only connection discovery over an injected substrate view.

NLI unavailability degrades to similarity proposals without changing the funnel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mycelium.connect import nli
from mycelium.connect.funnel import (
    BatchStatement,
    FunnelResult,
    SubstrateView,
    find_candidates,
)
from mycelium.connect.nli import NliModel, NliUnavailable, PairVerdict
from mycelium.connect.rules import LinkProposal, propose_links


@dataclass(frozen=True)
class PipelineResult:
    funnel: FunnelResult
    link_proposals: list[LinkProposal]
    verdicts: list[PairVerdict] | None
    nli: str


def run(
    batch: list[BatchStatement],
    view: SubstrateView,
    *,
    text_of: Callable[[str], str | None],
    nli_model: NliModel | None = None,
) -> PipelineResult:
    """Run candidate, rule, and optional NLI discovery without writing."""
    funnel = find_candidates(batch, view)
    link_proposals = propose_links(batch, funnel, view)
    try:
        model = nli_model if nli_model is not None else nli.default_model()
        verdicts = nli.classify_candidates(
            batch,
            funnel.candidates,
            model,
            text_of=text_of,
        )
    except NliUnavailable:
        return PipelineResult(funnel, link_proposals, None, "unavailable")
    return PipelineResult(funnel, link_proposals, verdicts, "ran")
