"""Turn raw prose into classified items, cut links, and flags.

An unresolved fragment becomes a flag rather than a guessed statement, so
nothing is dropped and no link retains an unresolved endpoint.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from mycelium import phrasing, phrasing_cues

from . import shapes
from .cue_gate import ABSORBING_DECISIONS, CueResolution
from .segment import (
    UNTYPED_CUT_KINDS,
    Cut,
    Segmentation,
    connective_cue,
    segment,
)


@dataclass(frozen=True)
class ExtractedItem:
    fragment_index: int
    kind: str
    text: str
    sentence: int
    span: tuple[int, int]
    note: str = ""


@dataclass(frozen=True)
class FlagInput:
    fragment_index: int
    text: str
    reason: str
    detail: str
    sentence: int
    span: tuple[int, int]
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class Extraction:
    items: list[ExtractedItem]
    flags: list[FlagInput]
    condition_links: list[tuple[int, int]]
    cut_links: list[tuple[int, int, str]]
    cue_resolutions: list[CueResolution] = field(default_factory=list)


FLAG_SOURCES = {
    "unsplit": "segmenter",
    "ambiguous": "shapes",
    "unmatched": "shapes",
    "phrasing": "phrasing",
    "flip": "planner",
    "depends_on_rejected": "planner",
    "cue": "cue-gate",
}

#: Connectives that are never a cue candidate however they are segmented: the
#: bare coordinator expresses no relation, and a conditional or causal opener
#: already has its orientation decided by the condition proposal.
_NEVER_A_CUE = (
    frozenset({"and"})
    | {opener.casefold() for opener in phrasing_cues.SUBORDINATOR_STRIP}
    | {word.casefold() for word in phrasing_cues.CAUSAL_SCONJ}
)


def violations_detail(violations: list[dict]) -> str:
    """Render phrasing violations as curator-facing detail text."""
    return "; ".join(
        f"{violation['category']}: {violation['matched_text']}"
        for violation in violations
    )


def _atomicity_detail(text: str) -> str:
    """Render the atomicity evidence for an unsplit fragment."""
    return violations_detail(phrasing.atomicity_violations(text)) or "compound remnant"


def _classification_detail(classification: shapes.Classification) -> str:
    """Render the positive shapes behind an ambiguous classification."""
    return "; ".join(
        f"{match.kind} ({match.shape}: {match.evidence})"
        for match in classification.matches
    )


def _cut_links(
    segmentation: Segmentation,
    item_position: dict[int, int],
    condition_links: list[tuple[int, int]],
) -> list[tuple[int, int, str]]:
    """Collect resolved cut links whose endpoints both classified as items."""
    links: list[tuple[int, int, str]] = []
    condition_pairs = set(condition_links)
    for cut in segmentation.cuts:
        if cut.link_type is None:
            continue
        left = item_position.get(cut.left)
        right = item_position.get(cut.right)
        # A missing endpoint is already visible to the curator as a flag.
        if left is None or right is None:
            continue
        if (left, right) in condition_pairs:
            continue
        links.append((left, right, cut.link_type))
    return links


def _cue_candidates(segmentation: Segmentation) -> list[tuple[Cut, str]]:
    """Pair each unresolved, non-punctuation cut with the cue it carries."""
    candidates: list[tuple[Cut, str]] = []
    for cut in segmentation.cuts:
        if cut.link_type is not None or cut.kind in UNTYPED_CUT_KINDS:
            continue
        cue = connective_cue(cut.connective)
        if not cue or cue in _NEVER_A_CUE:
            continue
        candidates.append((cut, cue))
    return candidates


def _resolve_cues(
    candidates: list[tuple[Cut, str]],
    resolve: Callable[[str], CueResolution],
) -> dict[str, CueResolution]:
    """Resolve each distinct cue once, in first-appearance order."""
    resolutions: dict[str, CueResolution] = {}
    for _cut, cue in candidates:
        if cue not in resolutions:
            resolutions[cue] = resolve(cue)
    return resolutions


def _cue_detail(resolution: CueResolution) -> str:
    """Render an unresolved cue and what it was nearest to."""
    nearest = ", ".join(
        f"{link_type} ({alias}) {score:.2f}"
        for link_type, alias, score in resolution.candidates
    )
    return f'unknown connective "{resolution.cue}"' + (
        f"; nearest: {nearest}" if nearest else "; no alias embeddings to compare"
    )


def _gate_cuts(
    segmentation: Segmentation,
    item_position: dict[int, int],
    condition_links: list[tuple[int, int]],
    resolve: Callable[[str], CueResolution],
) -> tuple[list[tuple[int, int, str]], list[FlagInput], list[CueResolution]]:
    """Apply cue decisions to unresolved cuts and render curator flags."""
    candidates = _cue_candidates(segmentation)
    resolutions = _resolve_cues(candidates, resolve)
    condition_pairs = set(condition_links)
    fragments = {fragment.index: fragment for fragment in segmentation.fragments}
    links: list[tuple[int, int, str]] = []
    flags: list[FlagInput] = []
    for cut, cue in candidates:
        resolution = resolutions[cue]
        if resolution.decision in ABSORBING_DECISIONS:
            left = item_position.get(cut.left)
            right = item_position.get(cut.right)
            if (
                left is not None
                and right is not None
                and (left, right) not in condition_pairs
            ):
                links.append((left, right, resolution.link_type))
            continue

        fragment = fragments[cut.left]
        flags.append(
            FlagInput(
                fragment_index=cut.left,
                text=fragment.text,
                reason="cue",
                detail=_cue_detail(resolution),
                sentence=fragment.sentence,
                span=cut.span,
                provenance={
                    "cue": resolution.cue,
                    "decision": resolution.decision,
                    "candidates": [
                        list(candidate) for candidate in resolution.candidates
                    ],
                },
            )
        )
    return links, flags, list(resolutions.values())


def extract(
    text: str,
    *,
    aliases: Mapping[str, frozenset[str]] | None = None,
    resolve_cue: Callable[[str], CueResolution] | None = None,
) -> Extraction:
    """Extract classified items and explicit flags from raw prose."""
    segmentation = segment(text, aliases=aliases)
    items: list[ExtractedItem] = []
    flags: list[FlagInput] = []
    item_position: dict[int, int] = {}
    flag_position: dict[int, int] = {}

    for fragment in segmentation.fragments:
        if fragment.unsplit:
            flag_position[fragment.index] = len(flags)
            flags.append(
                FlagInput(
                    fragment_index=fragment.index,
                    text=fragment.text,
                    reason="unsplit",
                    detail=_atomicity_detail(fragment.text),
                    sentence=fragment.sentence,
                    span=fragment.span,
                )
            )
            continue

        classification = shapes.classify(fragment.text)
        if classification.kind is not None:
            item_position[fragment.index] = len(items)
            items.append(
                ExtractedItem(
                    fragment_index=fragment.index,
                    kind=classification.kind,
                    text=fragment.text,
                    sentence=fragment.sentence,
                    span=fragment.span,
                )
            )
            continue

        reason = classification.status
        detail = (
            _classification_detail(classification)
            if reason == "ambiguous"
            else "no phrasing shape matched"
        )
        flag_position[fragment.index] = len(flags)
        flags.append(
            FlagInput(
                fragment_index=fragment.index,
                text=fragment.text,
                reason=reason,
                detail=detail,
                sentence=fragment.sentence,
                span=fragment.span,
            )
        )

    condition_links: list[tuple[int, int]] = []
    for proposal in segmentation.proposals:
        claim_item = item_position.get(proposal.claim)
        condition_item = item_position.get(proposal.condition)
        if claim_item is not None and condition_item is not None:
            condition_links.append((claim_item, condition_item))
            continue

        note = (
            f"dropped requires link: claim fragment {proposal.claim} "
            f"→ condition fragment {proposal.condition}"
        )
        for fragment_index, position in (
            (proposal.claim, claim_item),
            (proposal.condition, condition_item),
        ):
            if position is not None:
                items[position] = replace(items[position], note=note)
                continue
            flagged = flag_position.get(fragment_index)
            if flagged is not None:
                flags[flagged] = replace(
                    flags[flagged], detail=f"{flags[flagged].detail} — {note}"
                )

    cut_links = _cut_links(segmentation, item_position, condition_links)
    cue_resolutions: list[CueResolution] = []
    if resolve_cue is not None:
        cue_links, cue_flags, cue_resolutions = _gate_cuts(
            segmentation,
            item_position,
            condition_links,
            resolve_cue,
        )
        cut_links.extend(cue_links)
        flags.extend(cue_flags)

    return Extraction(items, flags, condition_links, cut_links, cue_resolutions)
