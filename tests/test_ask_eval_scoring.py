"""Scoring for the Ask evaluation harness (scripts/ask_eval_scoring.py)."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = _ROOT / "scripts" / "ask_eval_scoring.py"
    spec = importlib.util.spec_from_file_location("ask_eval_scoring", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load()


def _case(**over):
    raw = {"id": "c", "question": "How long is a trial?", "facts": ["trial"]}
    return sc.parse_cases({"cases": [raw | over]}, lambda key: f"stm_{key}")[0]


def _seen(answer="A trial lasts 14 days.", provenance=("stm_trial",), **over):
    evidence = (
        sc.EvidenceRecord("s1", "stm_trial", "[rule] A trial lasts 14 days"),
        sc.EvidenceRecord("s2", "stm_other", "[rule] Exports hold 10,000 rows"),
    )
    return sc.Observed(
        **{
            "outcome": "answered",
            "answer": answer,
            "gaps": (),
            "provenance": provenance,
            "evidence": evidence,
            "fact_texts": {"stm_trial": "A trial lasts 14 days"},
        }
        | over
    )


def _verdict(facts=(("f0", True),), claims=(("14 days", ["s1"]),), **over):
    return sc.Judgement(
        **{
            "facts": [{"fact": f, "stated": s} for f, s in facts],
            "must_not": [],
            "claims": [{"claim": c, "support": r} for c, r in claims],
            "declines": False,
            "flags_conflict": False,
        }
        | over
    )


def test_committed_cases_resolve_against_the_seed():
    cases_dir = _ROOT / "tests" / "ask_eval"
    seed = tomllib.loads((cases_dir / "seed.toml").read_text(encoding="utf-8"))
    keys = {s["key"] for s in seed["statements"]}

    def resolve(key: str) -> str:
        assert key in keys, key
        return key

    data = tomllib.loads((cases_dir / "cases.toml").read_text(encoding="utf-8"))
    cases = sc.parse_cases(data, resolve)
    assert len({c.id for c in cases}) == len(cases)
    assert sum(not c.answerable for c in cases) >= 3


@pytest.mark.parametrize("over", [{"answerable": False}, {"facts": []}])
def test_facts_are_required_exactly_when_answerable(over):
    with pytest.raises(ValueError):
        _case(**over)
    assert _case(answerable=False, facts=[]).categories == ("unanswerable",)


def test_a_grounded_cited_answer_scores_clean():
    score = sc.score_case(_case(), _seen(), _verdict())
    assert score.fact_recall == 1.0
    assert score.cited_recall == 1.0
    assert score.unsupported_claims == 0
    assert score.citation_precision == 1.0
    assert score.false_refusal is False
    assert score.refs_in_answer is False


def test_unsupported_claims_and_idle_citations_are_counted():
    verdict = _verdict(claims=(("14 days", ["s1"]), ("Trials renew monthly", [])))
    score = sc.score_case(
        _case(), _seen(provenance=("stm_trial", "stm_other")), verdict
    )
    assert (score.claims, score.unsupported_claims) == (2, 1)
    assert score.citation_precision == 0.5


def test_a_fact_named_by_its_text_still_counts():
    verdict = _verdict(facts=(("A trial lasts 14 days", True),))
    assert sc.score_case(_case(), _seen(), verdict).fact_recall == 1.0


def test_refs_shown_in_the_answer_are_flagged():
    seen = _seen(answer="A trial lasts 14 days (s1).")
    assert sc.score_case(_case(), seen, _verdict()).refs_in_answer is True


def test_refusal_is_correct_only_without_a_forbidden_claim():
    case = _case(answerable=False, facts=[], must_not=["Trials renew"])
    declined = _verdict(facts=(), claims=(), declines=True)
    assert sc.score_case(case, _seen(), declined).correct_refusal is True
    claimed = _verdict(
        facts=(), claims=(), declines=True, must_not=[{"index": 0, "claimed": True}]
    )
    score = sc.score_case(case, _seen(), claimed)
    assert (score.correct_refusal, score.must_not_violations) == (False, 1)


def test_a_clarification_counts_as_a_refusal_of_an_answerable_question():
    score = sc.score_case(
        _case(conflict=True), _seen(outcome="needs_clarification"), None
    )
    assert (score.fact_recall, score.false_refusal) == (0.0, True)
    assert score.conflict_flagged is False


def test_links_render_with_their_conditions():
    label = {"stm_a": "s1", "stm_b": "s2"}.get
    links = [
        {
            "link_type": "establishes",
            "to_id": "stm_a",
            "when": {"op": "not", "of": [{"statement_id": "stm_b"}]},
        }
    ]
    assert sc.render_links(links, lambda sid: label(sid) or sid) == (
        "establishes -> s1 when NOT s2",
    )


def test_aggregate_rates_skip_cases_a_metric_does_not_apply_to():
    answered = sc.score_case(_case(), _seen(), _verdict())
    refused = sc.score_case(
        _case(answerable=False, facts=[]),
        _seen(),
        _verdict(facts=(), claims=(), declines=True),
    )
    totals = sc.aggregate([answered, refused])
    assert totals["fact_recall"] == 1.0
    assert totals["correct_refusal"] == 1.0
    assert totals["conflict_flagged"] is None
