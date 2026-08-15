from __future__ import annotations

import math
from collections import Counter

from mycelium.connect.funnel import BatchStatement, Candidate, FunnelResult
from mycelium.connect.rules import LinkProposal, propose_links, shipped_cues


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
        self.allow_all_link_types = allow_all_link_types
        self.embed_calls: Counter[str] = Counter()
        self.sharing_calls = 0

    def embed(self, text: str) -> list[float]:
        self.embed_calls[text] += 1
        return self.embeddings_by_text[text]

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        return self.neighbours_by_vector.get(tuple(vec), [])[:k]

    def similarity(self, vec: list[float], statement_id: str) -> float | None:
        return self.similarities.get(statement_id)

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

    def kind_of(self, statement_id: str) -> str | None:
        return self.kinds.get(statement_id)

    def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
        return self.link_types_by_kind_pair.get(
            (from_kind, to_kind), self.allow_all_link_types
        )


_RULE_LINK_TYPES = frozenset({"configures", "restricts", "composes", "proceeds"})


def _funnel(
    entries: dict[int, tuple[list[float], frozenset[str]]],
    candidates: list[Candidate] | None = None,
) -> FunnelResult:
    return FunnelResult(
        embeddings={index: vec for index, (vec, _) in entries.items()},
        entities={index: entities for index, (_, entities) in entries.items()},
        candidates=candidates or [],
    )


def test_shipped_anchored_cue_resolves_to_batch_sibling_and_records_exact_cue():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    view.embeddings_by_text["company"] = [1.0, 0.0]
    view.entities_by_text["company"] = frozenset({"ent_company"})
    batch = [
        BatchStatement(4, "capability", "Cadence can be set per company"),
        BatchStatement(1, "property", "Company notification settings"),
    ]
    funnel = _funnel(
        {
            4: ([0.0, 1.0], frozenset()),
            1: ([0.8, 0.6], frozenset({"ent_company"})),
        }
    )

    proposals = propose_links(batch, funnel, view)

    assert proposals == [
        LinkProposal(
            new_index=4,
            target="@1",
            link_type="configures",
            pattern="configures-capability",
            cue="can be set per",
            target_text="company",
            score=0.8,
            anchored=True,
        )
    ]


def test_missing_batch_mention_falls_through_to_anchored_substrate_candidate():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    view.sharing["stm_dispatch"] = frozenset({"ent_dispatch"})
    view.similarities["stm_dispatch"] = 0.9
    view.kinds["stm_dispatch"] = "property"
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(1, "property", "Retry policy window"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.99, math.sqrt(1.0 - 0.99**2)], frozenset()),
        }
    )

    proposals = propose_links(batch, funnel, view)

    assert len(proposals) == 1
    assert proposals[0].target == "stm_dispatch"
    assert proposals[0].score == 0.9
    assert proposals[0].anchored is True


def test_named_entity_is_a_hard_filter_even_for_high_similarity_batch_sibling():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(1, "property", "Retry policy window"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.99, math.sqrt(1.0 - 0.99**2)], frozenset()),
        }
    )

    assert propose_links(batch, funnel, view) == []


def test_unnamed_phrase_uses_stronger_embedding_threshold_without_anchor():
    phrase = "the dispatch attempts"
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(1, "property", "Dispatch attempt allowance"),
    ]

    high_view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    high_view.embeddings_by_text[phrase] = [1.0, 0.0]
    high_funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.8, 0.6], frozenset()),
        }
    )

    high = propose_links(batch, high_funnel, high_view)

    assert len(high) == 1
    assert high[0].target == "@1"
    assert high[0].score == 0.8
    assert high[0].anchored is False
    assert high_view.sharing_calls == 0

    low_view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    low_view.embeddings_by_text[phrase] = [1.0, 0.0]
    low_funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.7, math.sqrt(1.0 - 0.7**2)], frozenset()),
        }
    )

    assert propose_links(batch, low_funnel, low_view) == []


def test_matrix_rejects_link_and_inadmissible_batch_does_not_fall_through():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    view.link_types_by_kind_pair[("rule", "state")] = frozenset()
    view.sharing["stm_dispatch"] = frozenset({"ent_dispatch"})
    view.similarities["stm_dispatch"] = 0.95
    view.kinds["stm_dispatch"] = "property"
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(1, "state", "Dispatch attempt availability"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.8, 0.6], frozenset({"ent_dispatch"})),
        }
    )

    assert propose_links(batch, funnel, view) == []


def test_matrix_skips_best_candidate_and_selects_next_admissible_candidate():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    view.link_types_by_kind_pair[("rule", "state")] = frozenset()
    view.link_types_by_kind_pair[("rule", "property")] = frozenset({"restricts"})
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(8, "state", "Dispatch attempt availability"),
        BatchStatement(3, "property", "Dispatch attempt allowance"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            8: ([0.9, math.sqrt(1.0 - 0.9**2)], frozenset({"ent_dispatch"})),
            3: ([0.8, 0.6], frozenset({"ent_dispatch"})),
        }
    )

    proposals = propose_links(batch, funnel, view)

    assert len(proposals) == 1
    assert proposals[0].target == "@3"
    assert proposals[0].score == 0.8


def test_shipped_cues_filters_pattern_membership_and_kind_restriction():
    assert shipped_cues("A login triggers an audit", "event") == []

    shipped = {"restricts-limits": frozenset({"rule"})}
    text = "Retry budget limits the dispatch attempts"

    assert shipped_cues(text, "event", shipped) == []
    cues = shipped_cues(text, "rule", shipped)
    assert len(cues) == 1
    assert cues[0].pattern == "restricts-limits"
    assert cues[0].cue == "limits"


def test_targetless_shipped_cue_proposes_nothing():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    batch = [BatchStatement(0, "state", "Payroll export is locked")]

    assert propose_links(batch, _funnel({}), view) == []
    assert view.embed_calls == Counter()


def test_target_phrase_embedding_and_sharing_are_cached_across_statements():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(2, "rule", "Daily quota limits the dispatch attempts"),
        BatchStatement(1, "property", "Dispatch attempt allowance"),
    ]
    funnel = _funnel(
        {
            1: ([0.8, 0.6], frozenset({"ent_dispatch"})),
        }
    )

    proposals = propose_links(batch, funnel, view)

    assert [(proposal.new_index, proposal.target) for proposal in proposals] == [
        (0, "@1"),
        (2, "@1"),
    ]
    assert view.embed_calls == Counter({phrase: 1})
    assert view.sharing_calls == 1


def test_duplicate_proposals_keep_higher_score_and_never_target_source_index():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    first_phrase = "cadence that is configured on company"
    second_phrase = "company"
    view.embeddings_by_text[first_phrase] = [0.8, 0.6]
    view.embeddings_by_text[second_phrase] = [0.95, math.sqrt(1.0 - 0.95**2)]
    batch = [
        BatchStatement(
            0,
            "capability",
            "Notification configures cadence that is configured on company",
        ),
        BatchStatement(1, "property", "Company notification cadence"),
    ]
    funnel = _funnel(
        {
            0: ([1.0, 0.0], frozenset()),
            1: ([1.0, 0.0], frozenset()),
        }
    )
    shipped = {
        "configures-verb": None,
        "configures-configured-on": frozenset({"capability"}),
    }

    proposals = propose_links(batch, funnel, view, shipped=shipped)

    assert len(proposals) == 1
    assert proposals[0].target == "@1"
    assert proposals[0].target != "@0"
    assert proposals[0].score == 0.95
    assert proposals[0].pattern == "configures-configured-on"
    assert proposals[0].cue == "is configured on"


def test_empty_batch_and_statements_without_shipped_cues_return_nothing():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)

    assert propose_links([], _funnel({}), view) == []

    batch = [
        BatchStatement(0, "event", "The payroll export completed successfully"),
        BatchStatement(1, "state", "The account remains available"),
    ]

    assert propose_links(batch, _funnel({}), view) == []
    assert view.embed_calls == Counter()
