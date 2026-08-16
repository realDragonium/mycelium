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


def _validate_mode(value: str) -> str:
    """Accept a configured cue-resolution mode or reject it consistently."""
    if value not in MODES:
        raise ValueError(f"{MODE_ENV} must be one of {', '.join(MODES)}: {value!r}")
    return value


def resolution_mode() -> str:
    """Read the configured cue-resolution mode, rejecting unknown values."""
    value = (os.environ.get(MODE_ENV) or "").strip()
    return DEFAULT_MODE if not value else _validate_mode(value)


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
    ranked = nearest_aliases(vector, vectors, k=len(vectors))
    candidates = tuple(ranked[:k])
    best_type, best_alias, best_score = ranked[0]
    second = next(
        (score for link_type, _alias, score in ranked if link_type != best_type),
        None,
    )
    if best_score < threshold:
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
    )
