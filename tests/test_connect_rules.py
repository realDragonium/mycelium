from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import pytest

from mycelium.connect.funnel import BatchStatement, Candidate, FunnelResult
from mycelium.connect.rules import (
    LinkProposal,
    RuleProposals,
    SuppressedNegation,
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


def _proposals_for(
    text: str,
    kind: str,
    phrase: str,
    *,
    shipped: dict[str, frozenset[str] | None] | None = None,
    allow: frozenset[str] | None = None,
) -> RuleProposals:
    default_allow = frozenset({"composes", "contains", "restricts", "triggers"})
    view = FakeView(allow_all_link_types=default_allow if allow is None else allow)
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    batch = [
        BatchStatement(0, kind, text),
        BatchStatement(1, "property", phrase),
    ]
    funnel = _funnel({1: ([0.8, 0.6], frozenset())})
    if shipped is None:
        return propose_links(batch, funnel, view)
    return propose_links(batch, funnel, view, shipped=shipped)


def test_negated_to_role_is_suppressed_and_affirmative_still_proposes():
    negated = _proposals_for("The quota does not limit uploads", "rule", "uploads")

    assert negated.links == []
    assert negated.suppressed_negations == [
        SuppressedNegation(
            new_index=0,
            pattern="restricts-limits",
            cue="limit",
            phrase="uploads",
            negator="not",
        )
    ]

    affirmative = _proposals_for("The quota limits uploads", "rule", "uploads")
    assert len(affirmative.links) == 1
    assert affirmative.suppressed_negations == []


def test_negated_from_role_is_suppressed_and_affirmative_keeps_source_slot():
    negated = _proposals_for(
        "The report does not belong to the archive", "state", "the archive"
    )

    assert negated.links == []
    assert negated.suppressed_negations == [
        SuppressedNegation(
            new_index=0,
            pattern="contains-belongs-to",
            cue="belong to",
            phrase="the archive",
            negator="not",
        )
    ]

    affirmative = _proposals_for(
        "The report belongs to the archive", "state", "the archive"
    )
    assert len(affirmative.links) == 1
    assert affirmative.links[0].source == "@1"
    assert affirmative.links[0].target == "@0"


def test_negated_cases_level_is_suppressed_and_affirmative_keeps_source_slot():
    # The frame's cue is contiguous, so "is not high for" never matches and
    # verb negation cannot reach it; the enumerating parent it captures can
    # still be denied nominally.
    negated = _proposals_for(
        "The escalation priority is high for no severity policy",
        "rule",
        "no severity policy",
    )

    assert negated.links == []
    assert negated.suppressed_negations == [
        SuppressedNegation(
            new_index=0,
            pattern="cases-level-for",
            cue="is high for",
            phrase="no severity policy",
            negator="no",
        )
    ]

    affirmative = _proposals_for(
        "The escalation priority is high for the severity policy",
        "rule",
        "the severity policy",
        allow=frozenset({"cases"}),
    )
    assert len(affirmative.links) == 1
    assert affirmative.links[0].source == "@1"
    assert affirmative.links[0].target == "@0"


def test_never_and_no_longer_suppress_trigger_cues():
    shipped = {"triggers-verb": None}

    never = _proposals_for(
        "The job never triggers the export",
        "event",
        "the export",
        shipped=shipped,
    )
    assert never.links == []
    assert [item.negator for item in never.suppressed_negations] == ["never"]

    no_longer = _proposals_for(
        "The job no longer triggers the export",
        "event",
        "the export",
        shipped=shipped,
    )
    assert no_longer.links == []
    assert [item.negator for item in no_longer.suppressed_negations] == ["no longer"]


def test_nominal_negation_suppresses_passive_agent():
    no_policy = _proposals_for("The cache is locked by no policy", "state", "no policy")
    assert no_policy.links == []
    assert [item.negator for item in no_policy.suppressed_negations] == ["no"]

    none = _proposals_for(
        "The cache is locked by none of the policies",
        "state",
        "none of the policies",
    )
    assert none.links == []
    assert [item.negator for item in none.suppressed_negations] == ["none"]


def test_no_more_than_quantifier_is_not_suppressed():
    result = _proposals_for(
        "The quota limits no more than ten uploads",
        "rule",
        "no more than ten uploads",
    )

    assert len(result.links) == 1
    assert result.suppressed_negations == []


def test_negation_substrings_do_not_suppress_affirmatives():
    nevertheless = _proposals_for(
        "Nevertheless, the report belongs to the archive", "state", "the archive"
    )
    innovation = _proposals_for("The innovation belongs to the lab", "state", "the lab")

    assert len(nevertheless.links) == 1
    assert nevertheless.suppressed_negations == []
    assert len(innovation.links) == 1
    assert innovation.suppressed_negations == []


def test_negated_match_with_affirmative_conjunct_is_suppressed_as_one_match():
    result = _proposals_for(
        "The report does not belong to the archive but belongs to the workspace",
        "state",
        "the archive",
    )

    # The greedy phrase group leaves the negated verb head as the only match, so
    # this catalog does not recover the affirmative conjunct separately.
    assert result.links == []
    assert [item.negator for item in result.suppressed_negations] == ["not"]


def test_affirmative_match_with_negated_conjunct_is_suppressed_as_one_match():
    result = _proposals_for(
        "The report belongs to the workspace but does not belong to the archive",
        "state",
        "the workspace",
    )

    assert result.links == []
    assert result.suppressed_negations == [
        SuppressedNegation(
            new_index=0,
            pattern="contains-belongs-to",
            cue="belongs to",
            phrase="the workspace but does not belong to the archive",
            negator="not",
        )
    ]


def test_nonverbal_cue_follows_head_chain_to_negated_verb():
    result = _proposals_for(
        "The formula does not include base plus tax",
        "rule",
        "tax",
    )

    assert result.links == []
    assert result.suppressed_negations == [
        SuppressedNegation(
            new_index=0,
            pattern="composes-formula",
            cue="plus",
            phrase="tax",
            negator="not",
        )
    ]


def test_focus_negation_does_not_suppress_affirmative_cue():
    result = _proposals_for(
        "The quota not only limits uploads but also blocks retries",
        "rule",
        "uploads but also blocks retries",
    )

    assert len(result.links) == 1
    assert result.links[0].link_type == "restricts"
    assert result.suppressed_negations == []


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

    proposals = propose_links(batch, funnel, view).links

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

    proposals = propose_links(batch, funnel, view).links

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
        (proposal,) = propose_links(batch, funnel, view, shipped=shipped).links
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
    admitted = propose_links(batch, funnel, view_admitting(("rule", "state"))).links
    assert [proposal.source for proposal in admitted] == ["s-policy"]

    # The carrier's own side admitting the type is not enough for this frame.
    assert propose_links(batch, funnel, view_admitting(("state", "rule"))).links == []


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

    proposals = propose_links(batch, funnel, view).links

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

    assert propose_links(batch, funnel, view).links == []


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

    high = propose_links(batch, high_funnel, high_view).links

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

    assert propose_links(batch, low_funnel, low_view).links == []


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

    proposals = propose_links(batch, funnel, view).links

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

    proposals = propose_links(batch, funnel, view).links

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

    proposals = propose_links(batch, funnel, view).links

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

    assert propose_links(batch, funnel, view).links == []

    proposals = propose_links(
        batch, funnel, view, aliases={"restricts": ("throttles",)}
    ).links

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

    assert propose_links(batch, _funnel({}), view).links == []
    assert view.embed_calls == Counter()


def test_shipped_passive_by_frame_puts_the_resolved_agent_in_the_source_slot():
    view = FakeView(allow_all_link_types=frozenset({"restricts"}))
    phrase = "the freeze policy"
    view.embeddings_by_text[phrase] = [1.0, 0.0]
    batch = [
        BatchStatement(0, "state", "The cache is locked by the freeze policy"),
        BatchStatement(1, "rule", "The freeze policy applies"),
    ]
    funnel = _funnel({1: ([0.8, 0.6], frozenset())})

    proposals = propose_links(batch, funnel, view).links

    assert proposals == [
        LinkProposal(
            new_index=0,
            source="@1",
            target="@0",
            link_type="restricts",
            pattern="restricts-state-by",
            cue="is locked by",
            phrase=phrase,
            score=0.8,
            anchored=False,
        )
    ]


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

    proposals = propose_links(batch, funnel, view).links

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

    proposals = propose_links(batch, funnel, view, shipped=shipped).links

    assert len(proposals) == 1
    assert proposals[0].target == "@1"
    assert proposals[0].target != "@0"
    assert proposals[0].score == 0.95
    assert proposals[0].pattern == "configures-configured-on"
    assert proposals[0].cue == "is configured on"


def test_empty_batch_and_statements_without_shipped_cues_return_nothing():
    view = FakeView(allow_all_link_types=_RULE_LINK_TYPES)

    assert propose_links([], _funnel({}), view).links == []

    batch = [
        BatchStatement(0, "event", "The payroll export completed successfully"),
        BatchStatement(1, "state", "The account remains available"),
    ]

    assert propose_links(batch, _funnel({}), view).links == []
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

    proposals = propose_links(batch, _funnel({}), view).links

    assert len(view.similarity_calls) == 1
    assert set(view.similarity_calls[0]) == set(popular)
    assert view.kinds_of_calls == [tuple(popular)]
    assert len(proposals) == 1
    assert proposals[0].target == "stm_58"
    assert proposals[0].score == 0.99
