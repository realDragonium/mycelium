from __future__ import annotations

import logging

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

    def similarity(self, vec: list[float], statement_id: str) -> float | None:
        return None

    def entities_in(self, text: str) -> frozenset[str]:
        return frozenset()

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        return {}

    def kind_of(self, statement_id: str) -> str | None:
        return self._kinds.get(statement_id)

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
    assert result.nli_pairs == NliPairs(classified=0, skipped=0, budget=400)
    assert "NLI unavailable: checkpoint is offline" in caplog.text


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
