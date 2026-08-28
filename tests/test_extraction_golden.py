"""Golden ingest cases: explicit input texts with their exact splits and links.

Each case runs the full raw-text pipeline the way `ingest_text` does — real
segmentation, real shape classification, condition proposals, and the alias
vocabulary a fresh substrate is seeded with — and pins the complete output:
every statement with its kind, every flag with its reason, and every link by
surface text. The embedding gate is exercised with injected resolutions, since
its scores depend on a live embedder.

These are documentation as much as regression cover: read a case to see what
the pipeline does to a sentence. The sentences describe mycelium itself, so
the fixtures double as a primer on the system.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from mycelium.connect import extract as ex
from mycelium.connect.cue_gate import CueResolution
from mycelium.connect.funnel import BatchStatement, find_candidates
from mycelium.connect.rules import propose_links
from mycelium.store.link_type_aliases import seed_rows


def _seeded_aliases() -> dict[str, frozenset[tuple[str, str]]]:
    """Invert the seed exactly as `store.alias_lookup` reads it back."""
    lookup: dict[str, set[tuple[str, str]]] = {}
    for link_type, alias, direction in seed_rows():
        lookup.setdefault(alias, set()).add((link_type, direction))
    return {alias: frozenset(pairs) for alias, pairs in lookup.items()}


SEEDED_ALIASES = _seeded_aliases()


@dataclass(frozen=True)
class Golden:
    text: str
    #: (kind, text) per accepted statement, in fragment order.
    statements: tuple[tuple[str, str], ...] = ()
    #: (reason, text) per flag, in fragment order.
    flags: tuple[tuple[str, str], ...] = ()
    #: (source text, link type, target text); condition links first, as
    #: `ingest_text` writes them.
    links: tuple[tuple[str, str, str], ...] = ()


def _observed_links(result: ex.Extraction) -> tuple[tuple[str, str, str], ...]:
    """Render condition and cut links the way `_ingest_specs` types them."""
    texts = [item.text for item in result.items]
    links = [
        (texts[claim], link_type, texts[condition])
        for claim, condition, link_type in result.condition_links
    ]
    links += [
        (texts[left], link_type, texts[right])
        for left, right, link_type in result.cut_links
    ]
    return tuple(links)


GOLDEN: dict[str, Golden] = {
    # -- conditionals: the condition becomes its own statement and the claim
    #    requires it, whichever side of the sentence it sits on.
    "conditional-initial": Golden(
        "When a statement is created, an embedding is queued.",
        statements=(
            ("event", "a statement is created"),
            ("event", "an embedding is queued"),
        ),
        links=(("an embedding is queued", "requires", "a statement is created"),),
    ),
    "conditional-trailing": Golden(
        "An embedding is queued when a statement is created.",
        statements=(
            ("event", "An embedding is queued"),
            ("event", "a statement is created"),
        ),
        links=(("An embedding is queued", "requires", "a statement is created"),),
    ),
    "conditional-if-perfect": Golden(
        "If the draft has expired, the substrate is locked.",
        statements=(
            ("state", "the draft has expired"),
            ("state", "the substrate is locked"),
        ),
        links=(("the substrate is locked", "requires", "the draft has expired"),),
    ),
    "conditional-unless": Golden(
        "Unless the substrate is locked, the draft is created.",
        statements=(
            ("state", "the substrate is locked"),
            ("event", "the draft is created"),
        ),
        links=(("the draft is created", "requires", "the substrate is locked"),),
    ),
    # -- passive ownership: "own" is stative, so the passive states a relation.
    #    Before DRA-427 this sentence flagged "unmatched" and never became a
    #    statement, capping the contains-belongs-to frame to embedded phrasings.
    "plain-passive-owned-by": Golden(
        "The audit log is owned by the compliance charter.",
        statements=(("state", "The audit log is owned by the compliance charter"),),
    ),
    # -- untyped cuts: the sentence splits but no relation is inferred.
    "semicolon": Golden(
        "The draft is created; an embedding is queued.",
        statements=(
            ("event", "The draft is created"),
            ("event", "an embedding is queued"),
        ),
    ),
    "coordination-two-clauses": Golden(
        "The alias worker runs and the sync occurs.",
        statements=(
            ("event", "The alias worker runs"),
            ("event", "the sync occurs"),
        ),
    ),
    # Coordination projects the shared subject into the second conjunct, so its
    # text is not a substring of the source.
    "coordination-subject-copy": Golden(
        "The curator clicks Approve and submits the draft.",
        statements=(
            ("event", "The curator clicks Approve"),
            ("event", "The curator submits the draft"),
        ),
    ),
    # -- typed cuts: a connective that is a seeded alias of exactly one link
    #    type links in the alias's registered direction (forward = left to
    #    right).
    "and-then-proceeds": Golden(
        "The draft is created and then an embedding is queued.",
        statements=(
            ("event", "The draft is created"),
            ("event", "an embedding is queued"),
        ),
        links=(("The draft is created", "proceeds", "an embedding is queued"),),
    ),
    # spaCy does not parse ", then" as verb coordination, but the right side's
    # stand-alone parse proves it is a whole clause, so the conservative check
    # lifts the remnant and preserves the typed link.
    "comma-then-proceeds": Golden(
        "The draft is created, then an embedding is queued.",
        statements=(
            ("event", "The draft is created"),
            ("event", "an embedding is queued"),
        ),
        links=(("The draft is created", "proceeds", "an embedding is queued"),),
    ),
    # -- flags: nothing is dropped and nothing is guessed.
    "unmatched-verb": Golden(
        # "log in" is not in the event verb allow-list: novel vocabulary flags.
        "The curator logs in.",
        flags=(("unmatched", "The curator logs in"),),
    ),
    "ambiguous-shapes": Golden(
        # Imperative "Verify" (check) and the embedded modal (capability) both
        # match, and disagreement is not grounds to pick one.
        "Verify the draft can be applied.",
        flags=(("ambiguous", "Verify the draft can be applied"),),
    ),
    "unsplit-compound-remnant": Golden(
        # The coordination cuts, but the right conjunct still carries a
        # conditional the segmenter cannot cut contiguously, so it flags.
        "The worker starts and records the time when the draft expires.",
        flags=(
            ("unmatched", "The worker starts"),
            ("unsplit", "The worker records the time when the draft expires"),
        ),
    ),
    # -- one bullet per shape: the full kind vocabulary in reading order.
    "kind-showcase": Golden(
        """- Statement kinds can be configured on the substrate.
- The snapshot is archived.
- The migration runs.
- The substrate is locked.
- The draft has expired.
- The embedding queue is empty.
- The statement has a canonical name.
- No open drafts.
- The final score equals the base score plus the boost.
- The candidate cap is 50.
- The similarity score is weighted.
- Draft ops.
- Click Approve to apply the draft.
- Verify the embedding.
- How to configure the embedding gate.""",
        statements=(
            ("capability", "Statement kinds can be configured on the substrate"),
            ("event", "The snapshot is archived"),
            ("event", "The migration runs"),
            ("state", "The substrate is locked"),
            ("state", "The draft has expired"),
            ("state", "The embedding queue is empty"),
            ("state", "The statement has a canonical name"),
            ("state", "No open drafts"),
            ("rule", "The final score equals the base score plus the boost"),
            ("rule", "The candidate cap is 50"),
            ("rule", "The similarity score is weighted"),
            ("property", "Draft ops"),
            ("action", "Click Approve to apply the draft"),
            ("check", "Verify the embedding"),
            ("procedure", "How to configure the embedding gate"),
        ),
    ),
    # -- a document: conditional, typed chain, and bullets in one input. The
    #    middle statement carries both its condition and its successor.
    "mixed-document": Golden(
        """When the text is submitted, a draft is created and then an embedding is queued.

- Click Approve to apply the draft.
- The alias worker has stopped.""",
        statements=(
            ("event", "the text is submitted"),
            ("event", "a draft is created"),
            ("event", "an embedding is queued"),
            ("action", "Click Approve to apply the draft"),
            ("state", "The alias worker has stopped"),
        ),
        links=(
            ("a draft is created", "requires", "the text is submitted"),
            ("a draft is created", "proceeds", "an embedding is queued"),
        ),
    ),
}


@pytest.mark.parametrize("case", GOLDEN.values(), ids=GOLDEN.keys())
def test_golden_extraction(case: Golden) -> None:
    result = ex.extract(case.text, aliases=SEEDED_ALIASES)

    assert tuple((item.kind, item.text) for item in result.items) == case.statements
    assert tuple((flag.reason, flag.text) for flag in result.flags) == case.flags
    assert _observed_links(result) == case.links


# -- the embedding gate, with the resolution injected: an unknown connective
#    either types the cut or flags it, never both.

UNKNOWN_CUE_TEXT = "The draft is created and also an embedding is queued."


def test_golden_unknown_cue_absorbed() -> None:
    resolution = CueResolution(
        cue="and also",
        decision="auto",
        link_type="proceeds",
        alias="then",
        score=0.91,
        candidates=(),
    )
    result = ex.extract(
        UNKNOWN_CUE_TEXT, aliases=SEEDED_ALIASES, resolve_cue=lambda cue: resolution
    )

    assert tuple((item.kind, item.text) for item in result.items) == (
        ("event", "The draft is created"),
        ("event", "an embedding is queued"),
    )
    assert _observed_links(result) == (
        ("The draft is created", "proceeds", "an embedding is queued"),
    )
    assert result.flags == []
    assert result.cue_resolutions == [resolution]


def test_golden_unknown_cue_unresolved() -> None:
    resolution = CueResolution(
        cue="and also",
        decision="unresolved",
        link_type=None,
        alias=None,
        score=None,
        candidates=(("proceeds", "then", 0.61),),
    )
    result = ex.extract(
        UNKNOWN_CUE_TEXT, aliases=SEEDED_ALIASES, resolve_cue=lambda cue: resolution
    )

    # Both statements survive; the connective itself is the flag.
    assert tuple((item.kind, item.text) for item in result.items) == (
        ("event", "The draft is created"),
        ("event", "an embedding is queued"),
    )
    assert _observed_links(result) == ()
    assert tuple((flag.reason, flag.text) for flag in result.flags) == (
        ("cue", "The draft is created"),
    )


# -- linking to EXISTING statements: the funnel relates and deduplicates by
#    embedding similarity, and the rule engine resolves shipped cues to
#    targets. The word-overlap embedder below (the same one the ingest_text
#    tests use) makes similarity a visible property of the sentences: cosine
#    is exactly the word overlap of the two texts, so every score in a case
#    can be read off its wording.


def _word_embed(text: str) -> list[float]:
    vector = [0.0] * 768
    for word in text.lower().split():
        vector[zlib.crc32(word.encode()) % 768] += 1.0
    return vector


def _cosine(a: list[float], b: list[float]) -> float:
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (norm_a * norm_b)


class WordOverlapView:
    """A substrate of existing statements, searched by real cosine ranking.

    Mentions are empty (every resolution takes the unanchored path) and every
    seeded link type is admissible for every kind pair: the kind matrix has its
    own tests, and holding it open keeps similarity the only gate here.
    """

    def __init__(self, existing: tuple[tuple[str, str, str], ...]) -> None:
        self.existing = {
            statement_id: (kind, text, _word_embed(text))
            for statement_id, kind, text in existing
        }

    def embed(self, text: str) -> list[float]:
        return _word_embed(text)

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        scored = sorted(
            (
                (_cosine(vec, stored[2]), statement_id)
                for statement_id, stored in self.existing.items()
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )
        return [(statement_id, score) for score, statement_id in scored[:k]]

    def similarity(
        self, vec: list[float], statement_ids: Sequence[str]
    ) -> dict[str, float]:
        return {
            statement_id: _cosine(vec, self.existing[statement_id][2])
            for statement_id in statement_ids
            if statement_id in self.existing
        }

    def entities_in(self, text: str) -> frozenset[str]:
        return frozenset()

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        return {}

    def kinds_of(self, statement_ids: Sequence[str]) -> dict[str, str]:
        return {
            statement_id: self.existing[statement_id][0]
            for statement_id in statement_ids
            if statement_id in self.existing
        }

    def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
        return frozenset(link_type for link_type, _alias, _dir in seed_rows())

    def aliases_by_type(self) -> dict[str, tuple[str, ...]]:
        # Cue slots take forward aliases only, mirroring store.aliases_by_type.
        grouped: dict[str, list[str]] = {}
        for link_type, alias, direction in seed_rows():
            if direction == "forward":
                grouped.setdefault(link_type, []).append(alias)
        return {
            link_type: tuple(sorted(aliases, key=lambda alias: (-len(alias), alias)))
            for link_type, aliases in grouped.items()
        }


@dataclass(frozen=True)
class SubstrateGolden:
    text: str
    #: (id, kind, text) per pre-existing statement.
    existing: tuple[tuple[str, str, str], ...]
    #: (fragment text, relation, existing id, score to 3 decimals). A pair
    #: below the 0.6 relatedness threshold appears nowhere.
    candidates: tuple[tuple[str, str, str, float], ...] = ()
    #: (fragment text, link type, target, cue): what the rule engine proposed.
    #: The target is an existing id, or the sibling's text for batch targets.
    proposals: tuple[tuple[str, str, str, str], ...] = ()


SUBSTRATE_GOLDEN: dict[str, SubstrateGolden] = {
    # One new statement against the full similarity gradient: an identical
    # same-kind statement is a duplicate (merge material), the same words under
    # a different kind only relate, partial overlap relates, and a disjoint
    # statement is silently out of range.
    "similarity-gradient": SubstrateGolden(
        "An embedding is queued.",
        existing=(
            ("s-dup", "event", "An embedding is queued"),
            ("s-kind", "state", "An embedding is queued"),
            ("s-near", "event", "An embedding is queued for the statement"),
            ("s-far", "event", "The curator approves a draft"),
        ),
        candidates=(
            ("An embedding is queued", "duplicate", "s-dup", 1.0),
            ("An embedding is queued", "related", "s-kind", 1.0),
            ("An embedding is queued", "related", "s-near", 0.756),
        ),
    ),
    # A shipped cue links to an existing statement its TARGET PHRASE resolves
    # to ("the archive policy" against "The archive policy is locked", 0.775,
    # above the 0.75 unanchored floor) even though the whole sentences are too
    # dissimilar to relate — no funnel candidates at all. The weaker statement
    # clears neither bar.
    "cue-resolves-to-substrate": SubstrateGolden(
        "Retention can be configured on the archive policy.",
        existing=(
            ("s-target", "state", "The archive policy is locked"),
            ("s-weak", "state", "The retention window is locked"),
        ),
        proposals=(
            (
                "Retention can be configured on the archive policy",
                "configures",
                "s-target",
                "can be configured on",
            ),
        ),
    ),
    # Resolution is batch-first: the cue's target phrase resolves to the
    # sibling extracted from the same text, and the substrate is never
    # consulted for the link even though it holds an identical statement.
    # The funnel still reports that statement as the sibling's duplicate.
    "cue-prefers-batch-sibling": SubstrateGolden(
        "The cadence can be configured on the locked schedule. The schedule is locked.",
        existing=(("s-twin", "state", "The schedule is locked"),),
        candidates=(
            (
                "The cadence can be configured on the locked schedule",
                "related",
                "s-twin",
                0.603,
            ),
            ("The schedule is locked", "duplicate", "s-twin", 1.0),
        ),
        proposals=(
            (
                "The cadence can be configured on the locked schedule",
                "configures",
                "The schedule is locked",
                "can be configured on",
            ),
        ),
    ),
    # The cue decides the direction, not which statement is new: "X is a part
    # of Y" names the relation from the far side, so the resolved parent is
    # the SOURCE of the `contains` edge and the new child its target. The
    # whole sentences are not even related — only the target phrase carries
    # the resolution.
    "existing-parent-is-the-link-source": SubstrateGolden(
        "The purge schedule is a part of the retention policy.",
        existing=(("s-policy", "rule", "The retention policy applies"),),
        proposals=(
            (
                "s-policy",
                "contains",
                "The purge schedule is a part of the retention policy",
                "is a part of",
            ),
        ),
    ),
    "belongs-to-existing-owner-is-the-link-source": SubstrateGolden(
        "The nightly automated purge schedule belongs to the retention policy.",
        existing=(("s-policy", "rule", "The retention policy applies"),),
        proposals=(
            (
                "s-policy",
                "contains",
                "The nightly automated purge schedule belongs to the retention policy",
                "belongs to",
            ),
        ),
    ),
    "owned-by-existing-owner-is-the-link-source": SubstrateGolden(
        "The monthly archive schedule remains a record that is owned by the "
        "retention policy.",
        existing=(("s-policy", "rule", "The retention policy applies"),),
        proposals=(
            (
                "s-policy",
                "contains",
                "The monthly archive schedule remains a record that is owned by the "
                "retention policy",
                "is owned by",
            ),
        ),
    ),
    # The owner fills the "from" slot, so the existing owner is the contains source.
    # The plain passive now reaches the same frame as the embedded phrasing.
    "plain-passive-owned-by-existing-owner-is-the-link-source": SubstrateGolden(
        "The audit log is owned by the compliance charter.",
        existing=(("s-charter", "rule", "The compliance charter applies"),),
        candidates=(
            (
                "The audit log is owned by the compliance charter",
                "related",
                "s-charter",
                0.603,
            ),
        ),
        proposals=(
            (
                "s-charter",
                "contains",
                "The audit log is owned by the compliance charter",
                "is owned by",
            ),
        ),
    ),
    # The alias-aware 2026-08-27 measurement found zero governed-by-phrase
    # fires across all 1644 statements and no usable lexical surface on any of
    # the 104 governed-by link endpoints, so this no-link is deliberate. The
    # funnel still reports the pair as related.
    "parent-frame-not-shipped": SubstrateGolden(
        "The retention window is purged according to the retention policy.",
        existing=(
            ("s-policy", "rule", "The retention policy is derived from the plan"),
        ),
        candidates=(
            (
                "The retention window is purged according to the retention policy",
                "related",
                "s-policy",
                0.676,
            ),
        ),
    ),
}


@pytest.mark.parametrize("case", SUBSTRATE_GOLDEN.values(), ids=SUBSTRATE_GOLDEN.keys())
def test_golden_substrate_linking(case: SubstrateGolden) -> None:
    extraction = ex.extract(case.text, aliases=SEEDED_ALIASES)
    batch = [
        BatchStatement(index, item.kind, item.text)
        for index, item in enumerate(extraction.items)
    ]
    view = WordOverlapView(case.existing)
    funnel = find_candidates(batch, view)
    proposals = propose_links(batch, funnel, view, aliases=view.aliases_by_type())

    texts = [item.text for item in extraction.items]

    def target_name(target: str) -> str:
        return texts[int(target[1:])] if target.startswith("@") else target

    assert (
        tuple(
            (
                texts[candidate.new_index],
                candidate.relation,
                candidate.statement_id,
                round(candidate.score, 3),
            )
            for candidate in funnel.candidates
        )
        == case.candidates
    )

    # Proposals carry explicit edge refs; render each endpoint by its text
    # when it is a batch statement so the case reads as prose.
    def edge(proposal) -> tuple[str, str, str, str]:
        return (
            target_name(proposal.source),
            proposal.link_type,
            target_name(proposal.target),
            proposal.cue,
        )

    assert tuple(edge(proposal) for proposal in proposals) == case.proposals
