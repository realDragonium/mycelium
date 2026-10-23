"""Scoring for the ingest evaluation harness (scripts/ingest_eval_scoring.py)."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = _ROOT / "scripts" / "ingest_eval_scoring.py"
    spec = importlib.util.spec_from_file_location("ingest_eval_scoring", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load()

EXISTING = "stm_aaaa"
OTHER = "stm_bbbb"

CASE = {
    "id": "demo",
    "prose": "x",
    "statements": [
        {
            "key": "trigger",
            "text": "A form is submitted",
            "kind": "event",
            "existing": [EXISTING],
        },
        {"key": "valid", "text": "The form is valid", "kind": "state"},
        {"key": "created", "text": "An invite is created", "kind": "event"},
        {
            "key": "parent",
            "text": "Invites can be sent",
            "kind": "capability",
            "existing": [OTHER],
        },
    ],
    "links": [
        {"from": "trigger", "to": "created", "type": ["triggers"], "when": ["valid"]},
        {"from": "parent", "to": "trigger", "type": "contains", "preexisting": True},
    ],
    "contradictions": [{"key": "parent", "existing": [OTHER]}],
    "aliases": [{"alias": "Invite", "entity": "ent_1"}],
}


def _score(ops, judged, ledger=None):
    case = sc.parse_case(CASE)
    graph = sc.extract_draft(ops)
    counts, outcomes = sc.score_case(case, graph, judged, ledger or sc.Ledger())
    return counts, outcomes


_EVAL = _ROOT / "tests" / "ingest_eval"


def test_every_case_file_parses_against_the_seed() -> None:
    seed = sc.parse_seed(tomllib.loads((_EVAL / "seed.toml").read_text()))
    seed_ids = {k: f"id_{k}" for k in seed.statement_keys}
    seed_ids |= {e.key: f"id_{e.key}" for e in seed.entities}
    paths = sorted(p for p in _EVAL.glob("*.toml") if p.name != "seed.toml")
    assert len(paths) >= 15
    ids = [sc.parse_case(tomllib.loads(p.read_text()), seed_ids).id for p in paths]
    assert ids == [p.stem for p in paths]


def test_seed_references_resolve_to_ids() -> None:
    seeded = {
        **CASE,
        "statements": [{**CASE["statements"][0], "existing": ["seed:form"]}]
        + CASE["statements"][1:],
        "aliases": [{"alias": "Invite", "entity": "seed:invite"}],
    }
    case = sc.parse_case(seeded, {"form": EXISTING, "invite": "ent_1"})
    assert case.statement("trigger").existing == (EXISTING,)
    assert case.aliases[0].entity == "ent_1"
    with pytest.raises(ValueError, match="seed:invite"):
        sc.parse_case(seeded, {"form": EXISTING})


def test_seed_becomes_one_batch_with_positional_refs() -> None:
    seed = sc.parse_seed(
        {
            "entities": [{"key": "inv", "name": "Invite", "description": "d"}],
            "statements": [
                {"key": "on", "kind": "state", "text": "Invites are on"},
                {
                    "key": "sent",
                    "kind": "event",
                    "text": "An invite is sent",
                    "incoming": [{"from": "made", "type": "triggers", "when": ["on"]}],
                },
                {
                    "key": "made",
                    "kind": "event",
                    "text": "An invite is made",
                    "links": [{"to": "sent", "type": "x", "when": ["!on", "on"]}],
                },
            ],
        }
    )
    assert seed.statement_keys == ("on", "sent", "made")
    assert seed.batch[1]["incoming_links"] == [
        {"from_id": "@2", "link_type": "triggers", "when": {"statement_id": "@0"}}
    ]
    assert seed.batch[2]["links"][0]["when"] == {
        "op": "and",
        "of": [
            {"op": "not", "of": [{"statement_id": "@0"}]},
            {"statement_id": "@0"},
        ],
    }
    with pytest.raises(ValueError, match="nope"):
        sc.parse_seed(
            {
                "statements": [
                    {
                        "key": "a",
                        "kind": "x",
                        "text": "t",
                        "links": [{"to": "nope", "type": "x"}],
                    }
                ]
            }
        )


def test_parse_case_rejects_unknown_keys() -> None:
    bad = {**CASE, "links": [{"from": "trigger", "to": "nope", "type": "x"}]}
    with pytest.raises(ValueError, match="nope"):
        sc.parse_case(bad)


def test_negated_when_literal() -> None:
    data = {
        **CASE,
        "links": [
            {"from": "trigger", "to": "created", "type": "x", "when": ["!valid"]}
        ],
    }
    (link,) = sc.parse_case(data).links
    assert link.when == frozenset({sc.Literal_("valid", negated=True)})


def test_extract_resolves_cross_op_and_sibling_refs() -> None:
    ops = [
        (
            1,
            "upsert_statements",
            {
                "statements": [
                    {"kind": "state", "text": "The form is valid"},
                    {
                        "kind": "event",
                        "text": "An invite is created",
                        "incoming_links": [
                            {
                                "from_id": EXISTING,
                                "link_type": "triggers",
                                "when": {"statement_id": "@0"},
                            }
                        ],
                    },
                ]
            },
        ),
        (
            2,
            "add_links",
            {
                "links": [
                    {
                        "from_id": "@1:1",
                        "to_id": "@1:0",
                        "link_type": "requires",
                        "when": {"op": "not", "of": [{"statement_id": OTHER}]},
                    },
                ]
            },
        ),
    ]
    graph = sc.extract_draft(ops)
    valid, created = sc.NodeRef(seq=1, index=0), sc.NodeRef(seq=1, index=1)
    assert [s.ref for s in graph.statements] == [valid, created]
    first, second = graph.links
    assert (first.source, first.target) == (sc.NodeRef(existing=EXISTING), created)
    assert first.when == frozenset({(valid, False)})
    assert (second.source, second.target) == (created, valid)
    assert second.when == frozenset({(sc.NodeRef(existing=OTHER), True)})


def test_or_condition_is_unscorable() -> None:
    ops = [
        (
            1,
            "add_links",
            {
                "links": [
                    {
                        "from_id": EXISTING,
                        "to_id": OTHER,
                        "link_type": "x",
                        "when": {
                            "op": "or",
                            "of": [{"statement_id": EXISTING}, {"statement_id": OTHER}],
                        },
                    }
                ]
            },
        )
    ]
    (link,) = sc.extract_draft(ops).links
    assert link.when is None


def test_upsert_with_id_is_a_refinement_not_a_new_statement() -> None:
    ops = [(1, "upsert_statement", {"id": EXISTING, "kind": "event", "text": "t"})]
    graph = sc.extract_draft(ops)
    assert graph.statements == []
    assert graph.modified_existing == [EXISTING]


def test_perfect_draft_scores_full_marks() -> None:
    ops = [
        (1, "upsert_statement", {"kind": "state", "text": "The form is valid"}),
        (
            2,
            "upsert_statement",
            {
                "kind": "event",
                "text": "An invite is created",
                "incoming_links": [
                    {
                        "from_id": EXISTING,
                        "link_type": "triggers",
                        "when": {"statement_id": "@1:0"},
                    }
                ],
            },
        ),
        (
            3,
            "alias_suggestion",
            {"proposal": {"entity_id": "ent_1", "alias": "invite"}},
        ),
    ]
    ledger = sc.Ledger(flagged=(f"conflicts with {OTHER}",))
    counts, outcomes = _score(ops, {0: "valid", 1: "created"}, ledger)
    assert outcomes == ["match", "match"]
    m = sc.metrics(counts)
    for name in (
        "statement_recall",
        "statement_precision",
        "kind_accuracy",
        "reuse_accuracy",
        "link_recall_typed",
        "link_precision",
        "existing_referenced",
        "condition_accuracy",
        "contradiction_recall",
        "alias_recall",
    ):
        assert m[name] == 1.0, name


def test_restating_an_existing_statement_is_a_duplicate() -> None:
    ops = [(1, "upsert_statement", {"kind": "event", "text": "A form is submitted"})]
    counts, outcomes = _score(ops, {0: "trigger"})
    assert outcomes == ["duplicate_of_existing"]
    assert counts.reused == 1  # parent reused, trigger duplicated
    assert counts.expected_existing == 2
    assert counts.true_positive == 0


def test_repeat_claims_go_to_the_earliest_statement() -> None:
    ops = [
        (1, "upsert_statement", {"kind": "state", "text": "Form valid"}),
        (2, "upsert_statement", {"kind": "rule", "text": "The form is valid"}),
    ]
    counts, outcomes = _score(ops, {0: "valid", 1: "valid"})
    assert outcomes == ["match", "repeat"]
    assert counts.kind_correct == 1


def test_reversed_link_and_wrong_condition() -> None:
    ops = [
        (
            1,
            "upsert_statement",
            {
                "kind": "event",
                "text": "An invite is created",
                "links": [{"to_id": EXISTING, "link_type": "triggers"}],
            },
        ),
        (
            2,
            "add_links",
            {
                "links": [
                    {"from_id": EXISTING, "to_id": "@1:0", "link_type": "proceeds"}
                ]
            },
        ),
    ]
    counts, _ = _score(ops, {0: "created"})
    assert counts.links_reversed == 0  # a forward link exists, of the wrong type
    assert counts.links_any_type == 1
    assert counts.links_typed == 0
    assert counts.conditional_correct == 0
    assert counts.scorable_links == 2
    assert counts.correct_links == 0


def test_only_reversed_link_counts_as_reversed() -> None:
    ops = [
        (
            1,
            "upsert_statement",
            {
                "kind": "event",
                "text": "An invite is created",
                "links": [{"to_id": EXISTING, "link_type": "triggers"}],
            },
        )
    ]
    counts, _ = _score(ops, {0: "created"})
    assert (counts.links_any_type, counts.links_reversed) == (0, 1)


def test_restating_a_preexisting_link_is_correct_but_not_recalled() -> None:
    ops = [
        (
            1,
            "add_links",
            {"links": [{"from_id": OTHER, "to_id": EXISTING, "link_type": "contains"}]},
        )
    ]
    counts, _ = _score(ops, {})
    assert (counts.correct_links, counts.scorable_links) == (1, 1)
    assert counts.expected_links == 1 and counts.links_typed == 0


def test_contradiction_in_ledger_row_and_spurious_rows() -> None:
    ledger = sc.Ledger(
        rows=(
            ("contradiction", (OTHER,)),
            ("contradiction", (EXISTING,)),
            ("duplicate", (EXISTING,)),
        )
    )
    counts, _ = _score([], {}, ledger)
    assert counts.contradictions_flagged == 1
    assert counts.spurious_contradictions == 1
    assert counts.referenced_existing == 2


def test_metrics_skip_empty_denominators() -> None:
    m = sc.metrics(sc.Counts())
    assert set(m.values()) == {None}
