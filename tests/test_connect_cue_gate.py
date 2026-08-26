"""Exercise cue resolution with exact hand-built embedding geometry."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from mycelium.connect.aliases import AliasVector, carrier_text
from mycelium.connect.cue_gate import resolution_mode, resolve_cue


def _vec(*values: float) -> np.ndarray:
    """Build a normalized float32 vector."""
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def _fake_embed(mapping: dict[str, np.ndarray]) -> Callable[[str], np.ndarray]:
    """Return an embedder restricted to the expected carrier texts."""

    def embed(text: str) -> np.ndarray:
        try:
            return mapping[text]
        except KeyError as error:
            raise AssertionError(f"unexpected embed: {text!r}") from error

    return embed


def _raising_embed(text: str) -> np.ndarray:
    """Reject every embedding call."""
    raise AssertionError(f"unexpected embed: {text!r}")


def test_clear_winner_resolves_automatically(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("proceeds", "then", _vec(1.0, 0.0, 0.0)),
        AliasVector("contains", "includes", _vec(0.0, 1.0, 0.0)),
        AliasVector("requires", "needs", _vec(0.0, 0.0, 1.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0, 0.0)}),
    )

    assert result.decision == "auto"
    assert result.link_type == "proceeds"
    assert result.alias == "then"
    assert result.score == pytest.approx(1.0)
    assert result.candidates[0][:2] == ("proceeds", "then")


def test_two_types_inside_margin_resolve_with_low_confidence(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("proceeds", "then", _vec(1.0, 0.0)),
        AliasVector("contains", "includes", _vec(4.0, 1.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0)}),
    )

    assert result.decision == "auto:low-confidence"
    assert result.link_type == "proceeds"
    assert result.alias == "then"
    assert result.score == pytest.approx(1.0)


def test_runner_up_of_same_type_does_not_cost_margin(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("proceeds", "then", _vec(1.0, 0.0, 0.0)),
        AliasVector("proceeds", "afterwards", _vec(4.0, 3.0, 0.0)),
        AliasVector("contains", "includes", _vec(0.0, 0.0, 1.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0, 0.0)}),
    )

    assert result.decision == "auto"
    assert result.link_type == "proceeds"


def test_absorbed_cue_inherits_the_nearest_alias_direction(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("contains", "is part of", _vec(1.0, 0.0, 0.0), "reverse"),
        AliasVector("proceeds", "then", _vec(0.0, 0.0, 1.0)),
    ]

    result = resolve_cue(
        "belongs to",
        vectors,
        embed_text=_fake_embed({carrier_text("belongs to"): _vec(1.0, 0.0, 0.0)}),
    )

    assert result.decision == "auto"
    assert (result.link_type, result.direction) == ("contains", "reverse")


def test_direction_conflict_inside_margin_stays_unresolved(monkeypatch):
    # Both `contains` aliases are equally near but read opposite ways;
    # similarity cannot break that tie, so the gate flags instead.
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("contains", "includes", _vec(1.0, 0.05, 0.0), "forward"),
        AliasVector("contains", "is part of", _vec(1.0, 0.0, 0.05), "reverse"),
    ]

    result = resolve_cue(
        "belongs to",
        vectors,
        embed_text=_fake_embed({carrier_text("belongs to"): _vec(1.0, 0.0, 0.0)}),
    )

    assert result.decision == "unresolved"
    assert result.link_type is None
    assert result.direction is None


def test_below_threshold_stays_unresolved_with_candidates(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("proceeds", "then", _vec(3.0, 4.0, 0.0)),
        AliasVector("contains", "includes", _vec(0.0, 1.0, 0.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0, 0.0)}),
    )

    assert result.decision == "unresolved"
    assert result.link_type is None
    assert result.alias is None
    assert result.score is None
    assert result.candidates
    assert result.candidates[0][2] == pytest.approx(0.6)


def test_strict_mode_does_not_embed(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "strict")
    vectors = [AliasVector("proceeds", "then", _vec(1.0, 0.0))]

    result = resolve_cue("and also", vectors, embed_text=_raising_embed)

    assert result.decision == "strict"
    assert result.candidates == ()


def test_invalid_mode_is_rejected_and_unset_mode_defaults_open(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "loose")

    with pytest.raises(ValueError):
        resolution_mode()
    with pytest.raises(ValueError):
        resolve_cue("and also", (), embed_text=_raising_embed)

    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    assert resolution_mode() == "open"


def test_no_alias_vectors_stays_unresolved_without_embedding(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)

    result = resolve_cue("and also", (), embed_text=_raising_embed)

    assert result.decision == "unresolved"
    assert result.candidates == ()


def test_candidates_are_best_first_and_truncated(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("a", "one", _vec(1.0, 0.0)),
        AliasVector("b", "two", _vec(4.0, 3.0)),
        AliasVector("c", "three", _vec(3.0, 4.0)),
        AliasVector("d", "four", _vec(0.0, 1.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        k=3,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0)}),
    )

    assert len(result.candidates) == 3
    scores = [score for _link_type, _alias, score in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_cue_is_normalized_before_embedding(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    expected = carrier_text("and also")

    result = resolve_cue(
        "  And   ALSO ",
        [AliasVector("proceeds", "then", _vec(1.0, 0.0))],
        embed_text=_fake_embed({expected: _vec(1.0, 0.0)}),
    )

    assert result.cue == "and also"


def test_candidates_carry_one_score_per_link_type(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUE_RESOLUTION", raising=False)
    vectors = [
        AliasVector("proceeds", "then", _vec(1.0, 0.0)),
        AliasVector("proceeds", "afterwards", _vec(20.0, 1.0)),
        AliasVector("proceeds", "next", _vec(10.0, 1.0)),
        AliasVector("contains", "includes", _vec(4.0, 3.0)),
    ]

    result = resolve_cue(
        "and also",
        vectors,
        k=2,
        embed_text=_fake_embed({carrier_text("and also"): _vec(1.0, 0.0)}),
    )

    # Without the per-type reduction the rival type never reaches the flag.
    assert [link_type for link_type, _alias, _score in result.candidates] == [
        "proceeds",
        "contains",
    ]
    assert result.candidates[1][2] == pytest.approx(0.8)
