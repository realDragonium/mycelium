from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import pytest

from mycelium import server
from mycelium.connect import funnel
from mycelium.connect.funnel import (
    BatchStatement,
    candidates_for,
    find_candidates,
    link_typable,
)


class FakeView:
    def __init__(
        self, allow_all_link_types: frozenset[str] = frozenset({"contains", "triggers"})
    ) -> None:
        self.embeddings_by_text: dict[str, list[float]] = {}
        self.neighbours_by_vector: dict[tuple[float, ...], list[tuple[str, float]]] = {}
        self.similarities: dict[str, float | None] = {}
        self.entities_by_text: dict[str, frozenset[str]] = {}
        self.sharing: dict[str, frozenset[str]] = {}
        self.kinds: dict[str, str] = {}
        self.link_types_by_kind_pair: dict[tuple[str, str], frozenset[str]] = {}
        self.aliases: dict[str, tuple[str, ...]] = {}
        self.allow_all_link_types = allow_all_link_types
        self.embed_calls: Counter[str] = Counter()
        self.sharing_calls = 0
        self.similarity_calls: list[tuple[str, ...]] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls[text] += 1
        return self.embeddings_by_text[text]

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        return self.neighbours_by_vector.get(tuple(vec), [])[:k]

    def similarity(
        self, vec: list[float], statement_ids: Sequence[str]
    ) -> dict[str, float]:
        self.similarity_calls.append(tuple(statement_ids))
        scores: dict[str, float] = {}
        for statement_id in statement_ids:
            score = self.similarities.get(statement_id)
            if score is not None:
                scores[statement_id] = score
        return scores

    def entities_in(self, text: str) -> frozenset[str]:
        return self.entities_by_text.get(text, frozenset())

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        self.sharing_calls += 1
        return {
            statement_id: shared & entity_ids
            for statement_id, shared in self.sharing.items()
            if shared & entity_ids
        }

    def kinds_of(self, statement_ids: Sequence[str]) -> dict[str, str]:
        return {
            statement_id: self.kinds[statement_id]
            for statement_id in statement_ids
            if statement_id in self.kinds
        }

    def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
        return self.link_types_by_kind_pair.get(
            (from_kind, to_kind), self.allow_all_link_types
        )

    def aliases_by_type(self) -> dict[str, tuple[str, ...]]:
        return self.aliases


def test_unions_vector_and_mention_routes_before_thresholding():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]
    view.entities_by_text["new"] = frozenset({"entity"})
    view.neighbours_by_vector[(1.0,)] = [
        ("vector", 0.8),
        ("both", 0.75),
        ("low-vector", 0.59),
        ("vanished", 0.95),
    ]
    view.sharing = {
        "mention": frozenset({"entity"}),
        "both": frozenset({"entity"}),
        "low-mention": frozenset({"entity"}),
    }
    view.similarities = {"mention": 0.7, "both": 0.9, "low-mention": 0.5}
    view.kinds = {
        "vector": "state",
        "both": "event",
        "low-vector": "event",
        "mention": "state",
        "low-mention": "event",
    }

    result = find_candidates([BatchStatement(0, "event", "new")], view)
    by_id = {candidate.statement_id: candidate for candidate in result.candidates}

    assert set(by_id) == {"both", "vector", "mention"}
    assert by_id["vector"].via == frozenset({"vector"})
    assert by_id["vector"].shared_entities == frozenset()
    assert by_id["mention"].via == frozenset({"mention"})
    assert by_id["mention"].shared_entities == frozenset({"entity"})
    assert by_id["both"].via == frozenset({"vector", "mention"})
    assert by_id["both"].score == 0.9
    assert by_id["both"].shared_entities == frozenset({"entity"})
    assert len(view.similarity_calls) == 1
    assert set(view.similarity_calls[0]) == {"mention", "both", "low-mention"}


def test_duplicate_flag_requires_same_kind_and_high_score():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]
    view.neighbours_by_vector[(1.0,)] = [
        ("same-high", 0.85),
        ("cross-high", 0.95),
        ("same-related", 0.7),
    ]
    view.kinds = {
        "same-high": "event",
        "cross-high": "state",
        "same-related": "event",
    }

    result = find_candidates([BatchStatement(0, "event", "new")], view)
    relations = {
        candidate.statement_id: candidate.relation for candidate in result.candidates
    }

    assert relations == {
        "cross-high": "related",
        "same-high": "duplicate",
        "same-related": "related",
    }


def test_ranking_cap_derived_data_and_convenience_filter():
    view = FakeView()
    view.embeddings_by_text = {"later": [2.0], "earlier": [1.0]}
    view.entities_by_text = {
        "later": frozenset({"two"}),
        "earlier": frozenset({"one"}),
    }
    view.neighbours_by_vector = {
        (2.0,): [("third", 0.7), ("beta", 0.8), ("alpha", 0.8)],
        (1.0,): [("first", 0.9)],
    }
    view.kinds = {
        "first": "state",
        "alpha": "state",
        "beta": "state",
        "third": "state",
    }
    batch = [
        BatchStatement(2, "event", "later"),
        BatchStatement(1, "event", "earlier"),
    ]

    result = find_candidates(batch, view, max_candidates=2)

    assert result.embeddings == {2: [2.0], 1: [1.0]}
    assert result.entities == {
        2: frozenset({"two"}),
        1: frozenset({"one"}),
    }
    assert view.embed_calls == Counter({"later": 1, "earlier": 1})
    assert [
        (candidate.new_index, candidate.statement_id) for candidate in result.candidates
    ] == [(1, "first"), (2, "alpha"), (2, "beta")]
    assert [candidate.statement_id for candidate in candidates_for(result, 2)] == [
        "alpha",
        "beta",
    ]


def test_empty_entities_skip_shared_mention_lookup():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]

    result = find_candidates([BatchStatement(0, "event", "new")], view)

    assert result.entities == {0: frozenset()}
    assert view.sharing_calls == 0


def test_invalid_threshold_order_raises_before_work():
    view = FakeView()

    with pytest.raises(
        ValueError,
        match=(
            "duplicate_threshold must be >= related_threshold "
            r"\(got 0.6 < 0.7\)"
        ),
    ):
        find_candidates([], view, related_threshold=0.7, duplicate_threshold=0.6)

    assert view.embed_calls == Counter()


def test_repeated_batch_index_raises_before_work():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]
    batch = [BatchStatement(0, "event", "new"), BatchStatement(0, "state", "new")]

    with pytest.raises(ValueError, match="batch statement indexes must be unique"):
        find_candidates(batch, view)

    assert view.embed_calls == Counter()


def test_empty_batch_returns_empty_result():
    assert find_candidates([], FakeView()) == funnel.FunnelResult({}, {}, [])


def test_empty_link_type_shortlist_preserves_related_candidate():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]
    view.neighbours_by_vector[(1.0,)] = [("existing", 0.7)]
    view.kinds["existing"] = "state"
    view.link_types_by_kind_pair[("event", "state")] = frozenset()

    result = find_candidates([BatchStatement(0, "event", "new")], view)

    assert len(result.candidates) == 1
    assert result.candidates[0].relation == "related"
    assert result.candidates[0].link_types == frozenset()
    assert link_typable(result) == []


def test_empty_link_type_shortlist_preserves_duplicate_relation():
    view = FakeView()
    view.embeddings_by_text["new"] = [1.0]
    view.neighbours_by_vector[(1.0,)] = [("existing", 0.9)]
    view.kinds["existing"] = "event"
    view.link_types_by_kind_pair[("event", "event")] = frozenset()

    result = find_candidates([BatchStatement(0, "event", "new")], view)

    assert result.candidates[0].relation == "duplicate"
    assert result.candidates[0].link_types == frozenset()


def test_duplicate_threshold_matches_server_constant():
    assert funnel.DUPLICATE_THRESHOLD == server.NEAR_DUPLICATE_THRESHOLD
