"""Resolve an unknown connective cue to a link type by embedding comparison.

Calibrated on the 118 seeded aliases with `nomic-embed-text` and the
`X {alias} Y` carrier, leave-one-out: the threshold is the 10th percentile
of each alias's best same-type cosine (p10 = 0.705), and at margin 0.10
4.2% of cases auto-type to the wrong link type against 82% precision inside
`auto`. The margin only labels confidence — a low-confidence decision still
types the link — so it is set for the accepted wrong-routing rate, not for
coverage: a margin wide enough to make most decisions `auto` would carry a
43% misroute rate.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .. import store
from .aliases import AliasVector, carrier_text, nearest_aliases

RESOLVE_THRESHOLD = 0.70
RESOLVE_MARGIN = 0.10
MODE_ENV = "MYCELIUM_CUE_RESOLUTION"
MODES = ("strict", "open")
DEFAULT_MODE = "open"
ABSORBING_DECISIONS = ("auto", "auto:low-confidence")


@dataclass(frozen=True)
class CueResolution:
    cue: str
    decision: str
    link_type: str | None
    alias: str | None
    score: float | None
    candidates: tuple[tuple[str, str, float], ...]
    #: How the absorbed cue reads the edge, inherited from the nearest alias
    #: of the winning type: "forward" (left to right) or "reverse". None when
    #: nothing was absorbed.
    direction: str | None = None


def _validate_mode(value: str) -> str:
    """Accept a configured cue-resolution mode or reject it consistently."""
    if value not in MODES:
        raise ValueError(f"{MODE_ENV} must be one of {', '.join(MODES)}: {value!r}")
    return value


def resolution_mode() -> str:
    """Read the configured cue-resolution mode, rejecting unknown values."""
    value = (os.environ.get(MODE_ENV) or "").strip()
    return DEFAULT_MODE if not value else _validate_mode(value)


def _best_per_type(
    ranked: list[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    """Keep each link type's nearest alias, preserving the ranking order."""
    # The margin and the flag are both about *types*, so a type that owns
    # several near aliases must not crowd its rivals out of the ranking.
    seen: set[str] = set()
    best: list[tuple[str, str, float]] = []
    for link_type, alias, score in ranked:
        if link_type in seen:
            continue
        seen.add(link_type)
        best.append((link_type, alias, score))
    return best


def resolve_cue(
    cue: str,
    vectors: Sequence[AliasVector],
    *,
    embed_text: Callable[[str], list[float]],
    threshold: float = RESOLVE_THRESHOLD,
    margin: float = RESOLVE_MARGIN,
    k: int = 5,
    mode: str | None = None,
) -> CueResolution:
    """Decide which link type an unknown connective cue names."""
    cue = store.normalize_alias(cue)
    mode = resolution_mode() if mode is None else _validate_mode(mode)
    if mode == "strict":
        return CueResolution(cue, "strict", None, None, None, ())
    if not vectors:
        return CueResolution(cue, "unresolved", None, None, None, ())

    vector = embed_text(carrier_text(cue))
    all_ranked = nearest_aliases(vector, vectors, k=len(vectors))
    ranked = _best_per_type(all_ranked)
    candidates = tuple(ranked[:k])
    best_type, best_alias, best_score = ranked[0]
    second = ranked[1][2] if len(ranked) > 1 else None
    if best_score < threshold:
        return CueResolution(cue, "unresolved", None, None, None, candidates)

    direction = _inherited_direction(all_ranked, vectors, best_type, best_score, margin)
    if direction is None:
        # The winning type's near aliases disagree on which way the edge
        # reads; similarity cannot break that tie, so nothing is absorbed.
        return CueResolution(cue, "unresolved", None, None, None, candidates)

    decision = (
        "auto"
        if second is None or best_score - second >= margin
        else "auto:low-confidence"
    )
    return CueResolution(
        cue,
        decision,
        best_type,
        best_alias,
        best_score,
        candidates,
        direction,
    )


def _inherited_direction(
    ranked: list[tuple[str, str, float]],
    vectors: Sequence[AliasVector],
    link_type: str,
    best_score: float,
    margin: float,
) -> str | None:
    """Read the direction off the winning type's nearest alias.

    Embedding similarity is direction-blind, so the direction is inherited
    from the lexicon: the nearest same-type alias supplies it, and a same-type
    rival within the margin that reads the other way makes the inheritance
    unjustifiable — the caller flags instead.
    """
    direction_of = {
        (vector.link_type, vector.alias): vector.direction for vector in vectors
    }
    same_type = [
        (alias, score)
        for candidate_type, alias, score in ranked
        if candidate_type == link_type
    ]
    winner = direction_of[(link_type, same_type[0][0])]
    for alias, score in same_type[1:]:
        if best_score - score >= margin:
            break
        if direction_of[(link_type, alias)] != winner:
            return None
    return winner
