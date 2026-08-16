"""Turn raw prose into classified items, cut links, and flags.

An unresolved fragment becomes a flag rather than a guessed statement, so
nothing is dropped and no link retains an unresolved endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from mycelium import phrasing

from . import shapes
from .segment import Segmentation, segment


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


@dataclass(frozen=True)
class Extraction:
    items: list[ExtractedItem]
    flags: list[FlagInput]
    condition_links: list[tuple[int, int]]
    cut_links: list[tuple[int, int, str]]


FLAG_SOURCES = {
    "unsplit": "segmenter",
    "ambiguous": "shapes",
    "unmatched": "shapes",
    "phrasing": "phrasing",
    "flip": "planner",
    "depends_on_rejected": "planner",
}


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


def extract(
    text: str, *, aliases: Mapping[str, frozenset[str]] | None = None
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

    return Extraction(
        items,
        flags,
        condition_links,
        _cut_links(segmentation, item_position, condition_links),
    )
