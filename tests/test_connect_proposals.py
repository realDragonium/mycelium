from mycelium.connect.funnel import Candidate, FunnelResult
from mycelium.connect.nli import NliLabel, PairVerdict
from mycelium.connect.proposals import proposals_from
from mycelium.connect.rules import LinkProposal


def _funnel(*candidates: Candidate) -> FunnelResult:
    return FunnelResult(embeddings={}, entities={}, candidates=list(candidates))


def _candidate(
    new_index: int,
    statement_id: str,
    score: float,
    relation: str,
    shared_entities: frozenset[str] = frozenset(),
) -> Candidate:
    return Candidate(
        new_index=new_index,
        statement_id=statement_id,
        kind="event",
        score=score,
        via=frozenset({"vector"}),
        shared_entities=shared_entities,
        relation=relation,
        link_types=frozenset(),
    )


def _verdict(
    new_index: int,
    statement_id: str,
    verdict: str,
    score: float,
    forward: tuple[str, float] = ("entailment", 0.91),
    backward: tuple[str, float] = ("entailment", 0.87),
) -> PairVerdict:
    return PairVerdict(
        new_index=new_index,
        statement_id=statement_id,
        forward=NliLabel(*forward),
        backward=NliLabel(*backward),
        verdict=verdict,
        score=score,
    )


def _link(link_type: str = "requires", *, score: float = 0.81) -> LinkProposal:
    return LinkProposal(
        new_index=0,
        source="@0",
        target="stm_target",
        link_type=link_type,
        pattern="requires-verb",
        cue="requires",
        phrase="the session timeout duration",
        score=score,
        anchored=True,
    )


def test_similarity_only_proposes_duplicate_candidates_as_merges():
    result = proposals_from(
        funnel=_funnel(
            _candidate(0, "stm_duplicate", 0.93, "duplicate"),
            _candidate(1, "stm_related", 0.82, "related"),
        ),
        links=[],
        verdicts=None,
    )

    assert len(result.proposals) == 1
    merge = result.proposals[0]
    assert (merge.kind, merge.new_index, merge.target) == (
        "merge",
        0,
        "stm_duplicate",
    )
    assert merge.provenance == {"source": "similarity", "score": 0.93}
    assert result.dropped_merges == []


def test_nli_verdicts_produce_merges_and_conflicts_only():
    duplicate = _verdict(0, "stm_duplicate", "duplicate", 0.94)
    contradiction = _verdict(
        1,
        "stm_conflict",
        "contradiction",
        0.79,
        forward=("contradiction", 0.92),
        backward=("neutral", 0.72),
    )
    result = proposals_from(
        funnel=_funnel(
            _candidate(2, "stm_ignored", 0.99, "duplicate"),
            _candidate(
                1,
                "stm_conflict",
                0.79,
                "related",
                frozenset({"ent_shared"}),
            ),
        ),
        links=[],
        verdicts=[duplicate, contradiction, _verdict(2, "stm_related", "related", 0.8)],
    )

    assert [proposal.kind for proposal in result.proposals] == ["merge", "conflict"]
    assert [proposal.target for proposal in result.proposals] == [
        "stm_duplicate",
        "stm_conflict",
    ]
    assert result.proposals[0].provenance == {
        "source": "nli",
        "score": 0.94,
        "forward": {"label": "entailment", "confidence": 0.91},
        "backward": {"label": "entailment", "confidence": 0.87},
    }
    assert result.proposals[1].provenance == {
        "source": "nli",
        "score": 0.79,
        "forward": {"label": "contradiction", "confidence": 0.92},
        "backward": {"label": "neutral", "confidence": 0.72},
    }


def test_contradiction_without_shared_entities_is_suppressed():
    result = proposals_from(
        funnel=_funnel(_candidate(0, "stm_unrelated", 0.6, "related")),
        links=[],
        verdicts=[
            _verdict(0, "stm_unrelated", "contradiction", 0.6),
        ],
    )

    assert result.proposals == []
    assert result.suppressed_conflicts == 1


def test_contradiction_with_shared_entities_survives():
    result = proposals_from(
        funnel=_funnel(
            _candidate(
                0,
                "stm_conflict",
                0.6,
                "related",
                frozenset({"ent_shared"}),
            )
        ),
        links=[],
        verdicts=[
            _verdict(0, "stm_conflict", "contradiction", 0.6),
        ],
    )

    assert [proposal.kind for proposal in result.proposals] == ["conflict"]
    assert result.suppressed_conflicts == 0


def test_only_best_merge_per_new_statement_survives():
    lower = _verdict(0, "stm_lower", "duplicate", 0.88)
    higher = _verdict(0, "stm_higher", "duplicate", 0.96)

    result = proposals_from(funnel=_funnel(), links=[], verdicts=[lower, higher])

    assert [proposal.target for proposal in result.proposals] == ["stm_higher"]
    assert [proposal.target for proposal in result.dropped_merges] == ["stm_lower"]


def test_merge_ties_use_nli_confidence_then_target_id():
    lower_confidence = _verdict(
        0,
        "stm_a",
        "duplicate",
        0.9,
        forward=("entailment", 0.7),
        backward=("entailment", 0.7),
    )
    higher_confidence = _verdict(
        0,
        "stm_z",
        "duplicate",
        0.9,
        forward=("entailment", 0.9),
        backward=("entailment", 0.9),
    )
    result = proposals_from(
        funnel=_funnel(),
        links=[],
        verdicts=[lower_confidence, higher_confidence],
    )
    assert result.proposals[0].target == "stm_z"

    tied = proposals_from(
        funnel=_funnel(),
        links=[],
        verdicts=[
            _verdict(0, "stm_z", "duplicate", 0.9),
            _verdict(0, "stm_a", "duplicate", 0.9),
        ],
    )
    assert tied.proposals[0].target == "stm_a"


def test_link_deduplication_preserves_distinct_types_and_provenance():
    first = _link()
    duplicate = _link(score=0.99)
    distinct_type = _link("accepts", score=0.77)

    result = proposals_from(
        funnel=_funnel(),
        links=[first, duplicate, distinct_type],
        verdicts=None,
    )

    assert [proposal.link_type for proposal in result.proposals] == [
        "requires",
        "accepts",
    ]
    assert result.proposals[0].provenance == {
        "source": "rule",
        "pattern": "requires-verb",
        "cue": "requires",
        "phrase": "the session timeout duration",
        "score": 0.81,
        "link_type": "requires",
    }


def test_link_proposal_keeps_its_edge_geometry():
    far_side = LinkProposal(
        new_index=0,
        source="stm_parent",
        target="@0",
        link_type="contains",
        pattern="contains-part-of",
        cue="is a part of",
        phrase="the retention policy",
        score=0.88,
        anchored=False,
    )

    result = proposals_from(funnel=_funnel(), links=[far_side], verdicts=None)

    proposal = result.proposals[0]
    assert (proposal.source, proposal.target) == ("stm_parent", "@0")
    plain = proposals_from(funnel=_funnel(), links=[_link()], verdicts=None)
    assert (plain.proposals[0].source, plain.proposals[0].target) == (
        "@0",
        "stm_target",
    )


def test_proposals_are_ordered_links_then_merges_then_conflicts():
    result = proposals_from(
        funnel=_funnel(
            _candidate(
                1,
                "stm_conflict",
                0.8,
                "related",
                frozenset({"ent_shared"}),
            )
        ),
        links=[_link()],
        verdicts=[
            _verdict(1, "stm_conflict", "contradiction", 0.8),
            _verdict(0, "stm_duplicate", "duplicate", 0.9),
        ],
    )

    assert [proposal.kind for proposal in result.proposals] == [
        "link",
        "merge",
        "conflict",
    ]
