from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import pytest

from mycelium.connect.funnel import BatchStatement, Candidate, FunnelResult
from mycelium.connect.rules import (
    LinkProposal,
    _cosine,
    propose_links,
    shipped_cues,
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
        self.kinds_of_calls: list[tuple[str, ...]] = []

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
        self.kinds_of_calls.append(tuple(statement_ids))
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
            source="@4",
            target="@1",
            link_type="configures",
            pattern="configures-capability",
            cue="can be set per",
            phrase="company",
            score=0.8,
            anchored=True,
        )
    ]


def test_far_side_frame_puts_the_resolved_phrase_in_the_source_slot():
    view = FakeView(allow_all_link_types=frozenset({"contains"}))
    view.embeddings_by_text["the retention policy"] = [1.0, 0.0]
    view.neighbours_by_vector[(1.0, 0.0)] = [("s-policy", 0.9)]
    view.kinds["s-policy"] = "rule"
    batch = [
        BatchStatement(
            0, "state", "The purge schedule is a part of the retention policy"
        )
    ]
    funnel = _funnel({0: ([0.0, 1.0], frozenset())})

    proposals = propose_links(batch, funnel, view)

    assert proposals == [
        LinkProposal(
            new_index=0,
            source="s-policy",
            target="@0",
            link_type="contains",
            pattern="contains-part-of",
            cue="is a part of",
            phrase="the retention policy",
            score=0.9,
            anchored=False,
        )
    ]


def test_both_directions_of_one_link_type_read_off_the_words():
    """The same `contains` vocabulary works both ways round.

    "X contains Y" puts the carrier in the source slot; "X is a part of Y"
    puts the resolved phrase there. Same batch position, same link type,
    opposite edges — decided entirely by the frame that matched.
    """
    shipped = {"contains-verb": None, "contains-part-of": None}

    def run(text: str) -> LinkProposal:
        view = FakeView(allow_all_link_types=frozenset({"contains"}))
        view.embeddings_by_text["the retention policy"] = [1.0, 0.0]
        view.neighbours_by_vector[(1.0, 0.0)] = [("s-policy", 0.9)]
        view.kinds["s-policy"] = "rule"
        batch = [BatchStatement(0, "state", text)]
        funnel = _funnel({0: ([0.0, 1.0], frozenset())})
        (proposal,) = propose_links(batch, funnel, view, shipped=shipped)
        return proposal

    outward = run("The archive contains the retention policy")
    assert (outward.source, outward.target) == ("@0", "s-policy")

    inward = run("The archive is a part of the retention policy")
    assert (inward.source, inward.target) == ("s-policy", "@0")


def test_far_side_frame_checks_the_matrix_from_the_phrase_side():
    batch = [
        BatchStatement(
            0, "state", "The purge schedule is a part of the retention policy"
        )
    ]

    def view_admitting(pair: tuple[str, str]) -> FakeView:
        view = FakeView(allow_all_link_types=frozenset())
        view.link_types_by_kind_pair[pair] = frozenset({"contains"})
        view.embeddings_by_text["the retention policy"] = [1.0, 0.0]
        view.neighbours_by_vector[(1.0, 0.0)] = [("s-policy", 0.9)]
        view.kinds["s-policy"] = "rule"
        return view

    funnel = _funnel({0: ([0.0, 1.0], frozenset())})

    # The resolved phrase is the edge's source, so rule -> state must admit it.
    admitted = propose_links(batch, funnel, view_admitting(("rule", "state")))
    assert [proposal.source for proposal in admitted] == ["s-policy"]

    # The carrier's own side admitting the type is not enough for this frame.
    assert propose_links(batch, funnel, view_admitting(("state", "rule"))) == []


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


def test_matrix_rejected_batch_sibling_falls_through_to_substrate():
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

    proposals = propose_links(batch, funnel, view)

    assert len(proposals) == 1
    assert proposals[0].source == "@0"
    assert proposals[0].target == "stm_dispatch"
    assert proposals[0].link_type == "restricts"
    assert proposals[0].score == 0.95


def test_admissible_batch_sibling_wins_without_substrate_scoring():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch"})
    view.sharing["stm_dispatch"] = frozenset({"ent_dispatch"})
    view.similarities["stm_dispatch"] = 0.95
    view.kinds["stm_dispatch"] = "property"
    batch = [
        BatchStatement(0, "rule", "Retry budget limits the dispatch attempts"),
        BatchStatement(1, "property", "Dispatch attempt allowance"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.8, 0.6], frozenset({"ent_dispatch"})),
        }
    )

    proposals = propose_links(batch, funnel, view)

    assert len(proposals) == 1
    assert proposals[0].target == "@1"
    assert proposals[0].score == 0.8
    assert view.similarity_calls == []


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

    text = "Retry budget limits the dispatch attempts"

    assert shipped_cues(text, "event") == []
    cues = shipped_cues(text, "rule")
    assert len(cues) == 1
    assert cues[0].pattern == "restricts-limits"
    assert cues[0].cue == "limits"


def test_shipped_cues_admits_alias_without_widening_kind_policy():
    aliases = {"configures": ("tuned",)}
    text = "The score is tuned on a job profile"

    cues = shipped_cues(text, "capability", aliases=aliases)

    assert [cue.pattern for cue in cues] == ["configures-configured-on"]
    assert cues[0].cue == "is tuned on"
    assert shipped_cues(text, "rule", aliases=aliases) == []


def test_propose_links_uses_alias_cue_end_to_end():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    batch = [
        BatchStatement(0, "rule", "Retry budget throttles dispatch attempts"),
        BatchStatement(1, "property", "Dispatch attempt allowance"),
    ]
    funnel = _funnel(
        {
            0: ([0.0, 1.0], frozenset()),
            1: ([0.8, 0.6], frozenset()),
        }
    )

    assert propose_links(batch, funnel, view) == []

    proposals = propose_links(
        batch, funnel, view, aliases={"restricts": ("throttles",)}
    )

    assert len(proposals) == 1
    assert proposals[0].pattern == "restricts-limits"
    assert proposals[0].cue == "throttles"
    assert proposals[0].target == "@1"


def test_targetless_shipped_cue_proposes_nothing():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    text = "Payroll export is locked"
    batch = [BatchStatement(0, "state", text)]

    # Pin the branch under test: a cue does fire, and it carries no target phrase.
    cues = shipped_cues(text, "state")
    assert [cue.pattern for cue in cues] == ["restricts-state"]
    assert all(cue.phrase is None for cue in cues)

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

    # Pin the branch under test: both patterns fire, so one index/type/target key
    # really is proposed twice and the higher score has to win.
    assert [
        cue.pattern for cue in shipped_cues(batch[0].text, "capability", shipped)
    ] == [
        "configures-verb",
        "configures-configured-on",
    ]

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


def test_cosine_rejects_mismatched_embedding_dimensions():
    assert _cosine([1.0, 0.0], [0.8, 0.6]) == pytest.approx(0.8)

    with pytest.raises(ValueError):
        _cosine([1.0, 0.0, 0.0], [1.0, 0.0])


def test_anchored_fan_out_scores_all_sharing_ids_in_one_batched_call():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)
    phrase = "the dispatch attempts"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    view.entities_by_text[phrase] = frozenset({"ent_dispatch", "ent_retry"})
    popular = [f"stm_{index:02d}" for index in range(60)]
    for statement_id in popular:
        view.sharing[statement_id] = frozenset({"ent_dispatch"})
        view.similarities[statement_id] = 0.7
        view.kinds[statement_id] = "property"
    view.sharing["stm_59"] = frozenset({"ent_dispatch", "ent_retry"})
    view.similarities["stm_59"] = 0.9
    view.similarities["stm_58"] = 0.99
    batch = [BatchStatement(0, "rule", "Retry budget limits the dispatch attempts")]

    proposals = propose_links(batch, _funnel({}), view)

    assert len(view.similarity_calls) == 1
    assert set(view.similarity_calls[0]) == set(popular)
    assert view.kinds_of_calls == [tuple(popular)]
    assert len(proposals) == 1
    assert proposals[0].target == "stm_58"
    assert proposals[0].score == 0.99
