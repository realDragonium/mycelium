"""Turn raw prose into classified items plus flags.

An unresolved fragment becomes a flag rather than a guessed statement, so
nothing is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from mycelium import phrasing

from . import shapes
from .segment import segment


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


FLAG_SOURCES = {
    "unsplit": "segmenter",
    "ambiguous": "shapes",
    "unmatched": "shapes",
    "phrasing": "phrasing",
    "flip": "planner",
    "depends_on_rejected": "planner",
}


def _atomicity_detail(text: str) -> str:
    """Render the atomicity evidence for an unsplit fragment."""
    violations = phrasing.atomicity_violations(text)
    return (
        "; ".join(
            f"{violation['category']}: {violation['matched_text']}"
            for violation in violations
        )
        or "compound remnant"
    )


def _classification_detail(classification: shapes.Classification) -> str:
    """Render the positive shapes behind an ambiguous classification."""
    return "; ".join(
        f"{match.kind} ({match.shape}: {match.evidence})"
        for match in classification.matches
    )


def extract(text: str) -> Extraction:
    """Extract classified items and explicit flags from raw prose."""
    segmentation = segment(text)
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

    return Extraction(items, flags, condition_links)
