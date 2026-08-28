from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest

from mycelium.connect import pipeline
from mycelium.connect.funnel import BatchStatement
from mycelium.connect.nli import NliLabel, NliUnavailable
from mycelium.connect.pipeline import NliPairs


class FakeView:
    def __init__(self, neighbours: list[tuple[str, float]]) -> None:
        self._neighbours = neighbours
        self._kinds = {statement_id: "event" for statement_id, _ in neighbours}

    def embed(self, text: str) -> list[float]:
        return [1.0]

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        return self._neighbours[:k]

    def similarity(
        self, vec: list[float], statement_ids: Sequence[str]
    ) -> dict[str, float]:
        return {}

    def entities_in(self, text: str) -> frozenset[str]:
        return frozenset()

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        return {}

    def kinds_of(self, statement_ids: Sequence[str]) -> dict[str, str]:
        return {
            statement_id: self._kinds[statement_id]
            for statement_id in statement_ids
            if statement_id in self._kinds
        }

    def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
        return frozenset()

    def aliases_by_type(self) -> dict[str, tuple[str, ...]]:
        return {}


class FakeNli:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]:
        self.calls.append(pairs)
        return [NliLabel("neutral", 1.0) for _ in pairs]


def test_unavailable_nli_reports_reason_and_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unavailable() -> None:
        raise NliUnavailable("checkpoint is offline")

    monkeypatch.delenv("MYCELIUM_NLI_MAX_PAIRS", raising=False)
    monkeypatch.setattr(pipeline.nli, "default_model", unavailable)
    view = FakeView([("existing", 0.9)])

    with caplog.at_level(logging.WARNING, logger="mycelium.connect.pipeline"):
        result = pipeline.run(
            [BatchStatement(0, "event", "new")],
            view,
            text_of=lambda statement_id: "existing text",
        )

    assert result.nli == "unavailable"
    assert result.nli_reason == "checkpoint is offline"
    assert result.suppressed_negations == []
    assert result.nli_pairs == NliPairs(classified=0, skipped=0, budget=400)
    assert "NLI unavailable: checkpoint is offline" in caplog.text


def test_unavailable_nli_reports_pairs_skipped_by_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableNli:
        def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]:
            raise NliUnavailable("checkpoint is offline")

    monkeypatch.setenv("MYCELIUM_NLI_MAX_PAIRS", "2")
    view = FakeView(
        [
            ("first", 0.9),
            ("second", 0.8),
            ("third", 0.7),
        ]
    )

    result = pipeline.run(
        [BatchStatement(0, "event", "new")],
        view,
        text_of=lambda statement_id: f"{statement_id} text",
        nli_model=UnavailableNli(),
    )

    assert result.nli == "unavailable"
    assert result.nli_reason == "checkpoint is offline"
    assert result.nli_pairs == NliPairs(classified=0, skipped=4, budget=2)


def test_zero_candidates_never_touches_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> None:
        raise AssertionError("default model must not be touched")

    monkeypatch.delenv("MYCELIUM_NLI_MAX_PAIRS", raising=False)
    monkeypatch.setattr(pipeline.nli, "default_model", fail)

    result = pipeline.run(
        [BatchStatement(0, "event", "new")],
        FakeView([]),
        text_of=lambda statement_id: None,
    )

    assert result.nli == "nothing_to_classify"
    assert result.nli_reason is None
    assert result.verdicts == []
    assert result.suppressed_negations == []
    assert result.nli_pairs == NliPairs(classified=0, skipped=0, budget=400)


def test_unresolvable_candidates_never_touch_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> None:
        raise AssertionError("default model must not be touched")

    monkeypatch.delenv("MYCELIUM_NLI_MAX_PAIRS", raising=False)
    monkeypatch.setattr(pipeline.nli, "default_model", fail)

    result = pipeline.run(
        [BatchStatement(0, "event", "new")],
        FakeView([("missing-first", 0.9), ("missing-second", 0.8)]),
        text_of=lambda statement_id: None,
    )

    assert result.nli == "nothing_to_classify"
    assert result.nli_reason is None
    assert result.verdicts == []
    assert result.nli_pairs == NliPairs(classified=0, skipped=0, budget=400)


def test_pair_budget_classifies_ranked_prefix_and_preserves_skipped_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_NLI_MAX_PAIRS", "2")
    monkeypatch.delenv("MYCELIUM_NLI_CONFIDENCE", raising=False)
    model = FakeNli()
    view = FakeView(
        [
            ("third", 0.7),
            ("first", 0.9),
            ("fourth", 0.65),
            ("second", 0.8),
        ]
    )
    existing_text = {
        "first": "first text",
        "second": "second text",
        "third": "third text",
        "fourth": "fourth text",
    }

    result = pipeline.run(
        [BatchStatement(0, "event", "new")],
        view,
        text_of=existing_text.get,
        nli_model=model,
    )

    assert result.nli == "ran"
    assert result.nli_reason is None
    assert result.suppressed_negations == []
    assert result.nli_pairs == NliPairs(classified=2, skipped=6, budget=2)
    assert model.calls == [[("new", "first text"), ("first text", "new")]]
    assert [candidate.statement_id for candidate in result.funnel.candidates] == [
        "first",
        "second",
        "third",
        "fourth",
    ]
    assert result.verdicts is not None
    assert [verdict.statement_id for verdict in result.verdicts] == ["first"]
    verdict_ids = {verdict.statement_id for verdict in result.verdicts}
    assert [
        candidate.statement_id
        for candidate in result.funnel.candidates
        if candidate.statement_id not in verdict_ids
    ] == ["second", "third", "fourth"]


def test_pair_counts_exclude_candidate_with_unresolvable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_NLI_MAX_PAIRS", "4")
    monkeypatch.delenv("MYCELIUM_NLI_CONFIDENCE", raising=False)
    model = FakeNli()
    view = FakeView(
        [
            ("missing", 0.9),
            ("classified", 0.8),
            ("budget-skipped", 0.7),
        ]
    )
    existing_text = {
        "classified": "existing text",
        "budget-skipped": "skipped text",
    }

    result = pipeline.run(
        [BatchStatement(0, "event", "new")],
        view,
        text_of=existing_text.get,
        nli_model=model,
    )

    assert result.nli == "ran"
    assert result.nli_pairs == NliPairs(classified=4, skipped=0, budget=4)
    assert model.calls == [
        [
            ("new", "existing text"),
            ("existing text", "new"),
            ("new", "skipped text"),
            ("skipped text", "new"),
        ]
    ]
    assert result.verdicts is not None
    assert [verdict.statement_id for verdict in result.verdicts] == [
        "classified",
        "budget-skipped",
    ]
