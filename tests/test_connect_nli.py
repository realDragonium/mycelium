from __future__ import annotations

import importlib.util
import os

import pytest

from mycelium.connect import nli
from mycelium.connect.funnel import BatchStatement, Candidate
from mycelium.connect.nli import (
    DEFAULT_MAX_PAIRS,
    DEFAULT_MODEL,
    NliLabel,
    NliUnavailable,
    TransformersNli,
    available,
    classify_candidates,
    default_model,
    max_pairs,
    model_name,
)


class FakeNli:
    def __init__(self, labels: dict[tuple[str, str], NliLabel] | None = None) -> None:
        self.labels = labels or {}
        self.calls: list[list[tuple[str, str]]] = []

    def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]:
        self.calls.append(pairs)
        return [self.labels.get(pair, NliLabel("neutral", 1.0)) for pair in pairs]


def candidate(
    *,
    new_index: int = 0,
    statement_id: str = "existing",
    kind: str = "event",
    score: float = 0.82,
) -> Candidate:
    return Candidate(
        new_index=new_index,
        statement_id=statement_id,
        kind=kind,
        score=score,
        via=frozenset({"vector"}),
        shared_entities=frozenset(),
        relation="related",
        link_types=frozenset(),
    )


def labels(forward: NliLabel, backward: NliLabel) -> dict[tuple[str, str], NliLabel]:
    return {("new", "existing text"): forward, ("existing text", "new"): backward}


def verdict_for(
    forward: NliLabel,
    backward: NliLabel,
    *,
    candidate_kind: str = "event",
    threshold: float | None = 0.7,
) -> str:
    model = FakeNli(labels(forward, backward))
    verdicts = classify_candidates(
        [BatchStatement(0, "event", "new")],
        [candidate(kind=candidate_kind)],
        model,
        text_of=lambda statement_id: "existing text",
        threshold=threshold,
    )
    return verdicts[0].verdict


def test_bidirectional_entailment_same_kind_is_duplicate():
    entailment = NliLabel("entailment", 0.9)

    assert verdict_for(entailment, entailment) == "duplicate"


def test_bidirectional_entailment_different_kind_is_related():
    entailment = NliLabel("entailment", 0.9)

    assert verdict_for(entailment, entailment, candidate_kind="state") == "related"


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_contradiction_at_threshold_in_either_direction(direction: str):
    neutral = NliLabel("neutral", 0.99)
    contradiction = NliLabel("contradiction", 0.7)
    forward = contradiction if direction == "forward" else neutral
    backward = contradiction if direction == "backward" else neutral

    assert verdict_for(forward, backward) == "contradiction"


def test_contradiction_below_threshold_is_related():
    assert (
        verdict_for(NliLabel("contradiction", 0.699), NliLabel("neutral", 0.99))
        == "related"
    )


def test_one_way_entailment_is_related():
    assert (
        verdict_for(NliLabel("entailment", 0.9), NliLabel("neutral", 0.9)) == "related"
    )


def test_bidirectional_entailment_with_one_low_confidence_is_related():
    assert (
        verdict_for(NliLabel("entailment", 0.9), NliLabel("entailment", 0.69))
        == "related"
    )


def test_missing_existing_text_skips_candidate_and_model_pair():
    model = FakeNli()
    candidates = [candidate(statement_id="missing"), candidate(statement_id="kept")]
    calls: list[str] = []

    def text_of(statement_id: str) -> str | None:
        calls.append(statement_id)
        return None if statement_id == "missing" else "kept text"

    verdicts = classify_candidates(
        [BatchStatement(0, "event", "new")],
        candidates,
        model,
        text_of=text_of,
    )

    assert calls == ["missing", "kept"]
    assert [verdict.statement_id for verdict in verdicts] == ["kept"]
    assert model.calls == [[("new", "kept text"), ("kept text", "new")]]


def test_classifies_all_candidates_once_in_directional_order():
    model = FakeNli()
    candidates = [candidate(statement_id="one"), candidate(statement_id="two")]
    existing = {"one": "first", "two": "second"}

    classify_candidates(
        [BatchStatement(0, "event", "new")],
        candidates,
        model,
        text_of=existing.get,
    )

    assert model.calls == [
        [
            ("new", "first"),
            ("first", "new"),
            ("new", "second"),
            ("second", "new"),
        ]
    ]


def test_score_is_carried_through_unchanged():
    model = FakeNli()

    verdicts = classify_candidates(
        [BatchStatement(0, "event", "new")],
        [candidate(score=0.8765)],
        model,
        text_of=lambda statement_id: "existing text",
    )

    assert verdicts[0].score == 0.8765


def test_explicit_threshold_overrides_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MYCELIUM_NLI_CONFIDENCE", "0.95")
    entailment = NliLabel("entailment", 0.8)

    assert verdict_for(entailment, entailment, threshold=0.75) == "duplicate"


def test_environment_confidence_is_used_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MYCELIUM_NLI_CONFIDENCE", "0.85")
    entailment = NliLabel("entailment", 0.8)

    assert verdict_for(entailment, entailment, threshold=None) == "related"


def test_environment_confidence_outside_unit_range_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MYCELIUM_NLI_CONFIDENCE", "1.5")
    entailment = NliLabel("entailment", 0.9)

    with pytest.raises(ValueError, match="threshold 1.5"):
        verdict_for(entailment, entailment, threshold=None)


def test_explicit_confidence_outside_unit_range_raises():
    entailment = NliLabel("entailment", 0.9)

    with pytest.raises(ValueError, match="threshold -0.1"):
        verdict_for(entailment, entailment, threshold=-0.1)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        (NliLabel("duplicate", 0.9), "unknown label 'duplicate'"),
        (NliLabel("entailment", float("nan")), "confidence nan"),
        (NliLabel("entailment", 1.5), "confidence 1.5"),
    ],
)
def test_invalid_model_result_raises(label: NliLabel, expected: str):
    with pytest.raises(ValueError, match=expected):
        verdict_for(label, NliLabel("neutral", 0.9))


def test_empty_candidates_do_not_call_model():
    model = FakeNli()

    assert (
        classify_candidates(
            [BatchStatement(0, "event", "new")], [], model, text_of=lambda _: None
        )
        == []
    )
    assert model.calls == []


def test_candidate_index_absent_from_batch_raises():
    model = FakeNli()

    with pytest.raises(ValueError, match="new_index 4"):
        classify_candidates(
            [BatchStatement(0, "event", "new")],
            [candidate(new_index=4)],
            model,
            text_of=lambda statement_id: "existing text",
        )

    assert model.calls == []


def test_optional_dependency_availability_guard(monkeypatch: pytest.MonkeyPatch):
    assert isinstance(available(), bool)
    original_find_spec = importlib.util.find_spec

    def missing_nli_package(name: str):
        if name in {"transformers", "torch"}:
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", missing_nli_package)

    with pytest.raises(NliUnavailable):
        TransformersNli().classify([("a", "b")])


def test_model_name_defaults_and_honours_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MYCELIUM_NLI_MODEL", raising=False)
    assert model_name() == DEFAULT_MODEL

    monkeypatch.setenv("MYCELIUM_NLI_MODEL", "local/checkpoint")
    assert model_name() == "local/checkpoint"


def test_max_pairs_defaults_and_honours_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MYCELIUM_NLI_MAX_PAIRS", raising=False)
    assert max_pairs() == DEFAULT_MAX_PAIRS == 400

    monkeypatch.setenv("MYCELIUM_NLI_MAX_PAIRS", "24")
    assert max_pairs() == 24


@pytest.mark.parametrize("configured", ["0", "-1", "not-an-integer"])
def test_max_pairs_rejects_non_positive_and_non_integer_values(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
):
    monkeypatch.setenv("MYCELIUM_NLI_MAX_PAIRS", configured)

    with pytest.raises(ValueError, match="not a positive integer"):
        max_pairs()


def test_default_model_reloads_when_checkpoint_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(nli, "available", lambda: True)
    monkeypatch.setattr(nli, "_model", None)
    monkeypatch.setenv("MYCELIUM_NLI_MODEL", "ck/a")

    first = default_model()
    assert first.model_name == "ck/a"
    assert default_model() is first

    monkeypatch.setenv("MYCELIUM_NLI_MODEL", "ck/b")
    second = default_model()

    assert second is not first
    assert second.model_name == "ck/b"


@pytest.mark.skipif(
    os.environ.get("MYCELIUM_TEST_NLI") != "1",
    reason="needs the nli extra and a model download",
)
def test_real_nli_model_classifies_representative_pairs():
    model = TransformersNli()

    results = model.classify(
        [
            ("A user logs out", "The user signs out"),
            (
                "The invite is sent to the participant",
                "The invite is never sent to the participant",
            ),
            (
                "A job profile can be renamed",
                "Older versions of a job profile can be browsed",
            ),
        ]
    )

    assert [result.label for result in results] == [
        "entailment",
        "contradiction",
        "neutral",
    ]
    assert all(0.0 <= result.confidence <= 1.0 for result in results)


def test_unloadable_checkpoint_is_reported_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    """A checkpoint that cannot be loaded must reach callers as NliUnavailable."""
    original_find_spec = importlib.util.find_spec

    def installed_nli_packages(name: str):
        if name in {"transformers", "torch"}:
            return object()
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", installed_nli_packages)
    # An absolute path is resolved locally, so the load fails without a network
    # call whether or not the optional packages are actually installed.
    monkeypatch.setenv("MYCELIUM_NLI_MODEL", "/nonexistent/nli-checkpoint")

    with pytest.raises(NliUnavailable):
        TransformersNli()._load()
