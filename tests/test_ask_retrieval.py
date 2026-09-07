"""Bounded combined retrieval and evidence reference contracts."""

from __future__ import annotations

import json

import pytest

from mycelium.ask.evidence import Evidence, bound_payload
from mycelium.ask.prompts import format_recon
from mycelium.ask.retrieval import retrieve_context
from mycelium.ask.tools import AnswerInput
from test_ask import _submit_input

WHEN = {
    "op": "and",
    "of": [
        {"statement_id": "stm_enabled"},
        {"op": "not", "of": [{"statement_id": "stm_disabled"}]},
    ],
}
ROOT = {
    "id": "stm_root",
    "kind": "rule",
    "text": "The worker retries conditionally.",
    "links": [
        {"to_id": "stm_next", "link_type": "triggers", "when": WHEN},
        {
            "to_id": "stm_next",
            "link_type": "triggers",
            "when": {"op": "not", "of": [WHEN]},
        },
    ],
    "incoming_links": [{"from_id": "stm_parent", "link_type": "establishes"}],
    "when_references": [
        {
            "from_id": "stm_gate",
            "to_id": "stm_target",
            "link_type": "triggers",
            "when": {"statement_id": "stm_root"},
        }
    ],
}


class Reads:
    def __init__(self, roots=None):
        self.calls = []
        self.roots = roots or [ROOT]

    def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "list_entities":
            return {"total": 1, "entities": [{"id": "ent_worker", "name": "Worker"}]}
        if name == "get_entity":
            return {
                "id": "ent_worker",
                "description": "Retry worker",
                "names": [
                    {"id": "nam_1", "text": "Worker"},
                    {"id": "nam_2", "text": "Bot"},
                ],
                "links": [{"to_entity_id": "ent_queue", "link_type": "uses"}],
                "incoming_links": [
                    {"from_entity_id": "ent_service", "link_type": "contains"}
                ],
            }
        if name == "search_statements":
            return self.roots
        if name == "get_statements":
            return {
                "statements": [
                    {"id": sid, "kind": "state", "text": sid}
                    for sid in arguments["ids"]
                ],
                "missing": [],
            }
        raise AssertionError(name)


def test_combined_retrieval_preserves_direction_conditional_variants_and_aliases():
    reads = Reads()
    result = retrieve_context(
        reads, query="When does it retry?", names=["Worker", "Bot"]
    )
    root = next(s for s in result["statements"] if s["id"] == "stm_root")
    assert root == ROOT
    assert len(root["links"]) == 2
    assert result["entities"][0]["names"][1]["text"] == "Bot"
    assert result["entities"][0]["incoming_links"][0]["from_entity_id"] == "ent_service"
    ids = [s["id"] for s in result["statements"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "stm_root",
        "stm_next",
        "stm_enabled",
        "stm_disabled",
        "stm_parent",
        "stm_gate",
        "stm_target",
    }
    assert len([name for name, _ in reads.calls if name == "get_entity"]) == 1
    search_args = next(
        args for name, args in reads.calls if name == "search_statements"
    )
    assert search_args["mentions"] == ["Worker"]
    assert search_args["depth"] == 0
    assert len(result["reads"]) == len(reads.calls)
    assert result["truncated"] == {
        "direct_statements": False,
        "linked_statements": False,
    }


def test_combined_limits_are_global_and_omissions_are_explicit():
    roots = [{**ROOT, "id": f"stm_{i}"} for i in range(9)]
    reads = Reads(roots)
    result = retrieve_context(
        reads, query="retry", names=["Worker"], statement_limit=2, linked_limit=1
    )
    assert len(result["direct_ids"]) == 2
    assert len(result["statements"]) == 3
    assert result["truncated"] == {"direct_statements": True, "linked_statements": True}
    assert next(args for name, args in reads.calls if name == "get_statements")[
        "ids"
    ] == ["stm_next"]
    assert result["statements"][0]["links"][0]["when"] == WHEN


@pytest.mark.parametrize(
    "over",
    [
        {"names": []},
        {"names": ["a"] * 4},
        {"entity_limit": 4},
        {"statement_limit": 9},
        {"linked_limit": 13},
        {"query": " "},
    ],
)
def test_invalid_bounds_do_no_work(over):
    reads = Reads()
    with pytest.raises(ValueError):
        retrieve_context(reads, **{"query": "retry", "names": ["Worker"], **over})
    assert reads.calls == []


def test_edge_caps_preserve_whole_conditions_and_original_total():
    root = {
        **ROOT,
        "links": [
            {"to_id": f"stm_{i}", "link_type": "triggers", "when": WHEN}
            for i in range(30)
        ],
    }
    result = retrieve_context(Reads([root]), query="retry", names=["Worker"])
    supplied = result["statements"][0]
    assert supplied["links_truncated"] == 30
    assert len(supplied["links"]) == 20
    assert all(edge["when"] == WHEN for edge in supplied["links"])


def test_name_resolution_failure_does_not_claim_a_statement_search():
    def read(name, arguments):
        return {"entities": [], "total": 0}

    result = retrieve_context(read, query="absent", names=["Unknown"])
    assert result["statements"] == []
    assert result["resolutions"][0]["candidates"] == []
    assert [read["name"] for read in result["reads"]] == [
        "list_entities",
        "search_entities",
    ]


def test_recon_preserves_reverse_links_negation_and_conditions():
    compact = json.loads(format_recon([ROOT]))[0]
    for field in ("links", "incoming_links", "when_references"):
        assert compact[field] == ROOT[field]


def test_references_only_vouch_for_supplied_statement_records():
    evidence = Evidence()
    sent = json.loads(
        evidence.supply(
            {
                "entities": [{"id": "ent_1", "text": "Entity"}],
                "statements": [ROOT],
                "id": "stm_missing",
            }
        )
    )
    assert evidence.expand(["s1", "s1", "stm_root"]) == ["stm_root"]
    assert sent["statements"][0]["ref"] == "s1"
    for invalid in ("ent_1", "stm_missing", "stm_next", "s2"):
        with pytest.raises(ValueError):
            evidence.expand([invalid])


def test_oversize_record_never_gets_a_reference_or_a_partial_condition():
    evidence = Evidence()
    huge = {**ROOT, "text": "x" * 25_000}
    sent = json.loads(evidence.supply([huge]))
    assert sent == {"items": [], "omitted_items": 1}
    assert evidence.ids == set()
    assert evidence.omitted
    assert json.loads(evidence.supply([ROOT]))[0]["ref"] == "s1"
    assert evidence.expand(["s1"]) == ["stm_root"]


def test_reference_numbers_never_collide_after_omissions():
    evidence = Evidence()
    # A larger top-level list can be omitted while a later collection survives.
    evidence.supply(
        {
            "large": [{"id": "stm_1", "text": "x" * 25_000}],
            "small": [{"id": "stm_2", "text": "second"}],
        }
    )
    previous = dict(evidence.by_ref)
    evidence.supply([{"id": "stm_3", "text": "third"}])
    assert all(evidence.by_ref[ref] == sid for ref, sid in previous.items())
    assert evidence.ids == {"stm_2", "stm_3"}


def test_compact_output_reduces_payload_without_losing_uncertainty():
    compact = _submit_input(
        provenance=["s1", "s2"],
        gaps=["Unknown delay", "Conflicting retry limits"],
        interpretation={
            "resolved_to": "Retry behavior",
            "reason": "No disable switch is documented",
        },
    )
    full_ids = ["stm_" + "a" * 32, "stm_" + "b" * 32]
    legacy = {
        **compact,
        "provenance": full_ids,
        "interpretation": {
            "as_asked": "Why retry?",
            "resolved_to": "Retry behavior",
            "reframed": True,
            "reframe_reason": compact["interpretation"]["reason"],
        },
        "sub_questions": [
            {
                "sub_question": "Retry limit",
                "status": "partial",
                "note": "Conflicting retry limits",
            }
        ],
        "adjacency_note": "Re-searched related conditions; nothing new.",
    }
    assert len(json.dumps(compact)) < len(json.dumps(legacy)) * 0.75
    parsed = AnswerInput.model_validate(compact)
    assert parsed.gaps == legacy["gaps"]
    assert parsed.interpretation.reason == legacy["interpretation"]["reframe_reason"]
    evidence = Evidence()
    evidence.supply([{"id": sid, "text": "Evidence"} for sid in full_ids])
    assert evidence.expand(parsed.provenance) == full_ids


def test_bounded_payload_remains_valid_json():
    result = bound_payload({"statements": [ROOT] * 20, "missing": []}, limit=2000)
    assert len(json.dumps(result, separators=(",", ":"))) <= 2000
    assert result["omitted_items"]["statements"] > 0
    assert all(s == ROOT for s in result["statements"])


def test_combined_retrieval_reduces_model_round_trips_for_the_same_evidence():
    from mycelium.ask import AskConfig, run_ask
    from mycelium.ask.substrate import ToolSpec
    from test_ask import FakeAnthropic, _message, _tool_use

    class Substrate:
        def __init__(self):
            self.reads = Reads()

        def tool_specs(self):
            return [
                ToolSpec(name, name, {"type": "object"})
                for name in (
                    "survey_statements",
                    "list_entities",
                    "get_entity",
                    "search_statements",
                    "get_statements",
                    "retrieve_context",
                )
            ]

        def call(self, name, arguments):
            if name == "survey_statements":
                return [ROOT]
            if name == "retrieve_context":
                return retrieve_context(self.reads, **arguments)
            return self.reads(name, arguments)

    legacy_reads = [
        ("list_entities", {"prefix": "Worker", "limit": 4}),
        ("get_entity", {"id": "ent_worker"}),
        (
            "search_statements",
            {"query": "retry", "mentions": ["Worker"], "limit": 7, "depth": 0},
        ),
        (
            "get_statements",
            {
                "ids": [
                    "stm_next",
                    "stm_enabled",
                    "stm_disabled",
                    "stm_parent",
                    "stm_gate",
                    "stm_target",
                ]
            },
        ),
    ]
    combined = [("retrieve_context", {"query": "retry", "names": ["Worker"]})]
    outcomes = []
    for reads in (legacy_reads, combined):
        turns = [_message([_tool_use(name, arguments)]) for name, arguments in reads]
        turns += [
            _message(
                [
                    _tool_use(
                        "survey_statements",
                        {"query": "retry conditions", "adjacency_sources": ["s1"]},
                    )
                ]
            ),
            _message([_tool_use("submit_answer", _submit_input())]),
        ]
        substrate = Substrate()
        result = run_ask(
            "Why?",
            client=FakeAnthropic(turns),
            substrate=substrate,
            config=AskConfig(trace_dir=""),
        )
        outcomes.append(result)
        assert result.trace["floor"]["satisfied"]
        assert len(substrate.reads.calls) == 4
    old, new = outcomes
    assert new.model_dump(exclude={"trace"}) == old.model_dump(exclude={"trace"})
    assert set(new.trace["evidence_refs"].values()) == set(
        old.trace["evidence_refs"].values()
    )
    assert old.trace["model_turns"] == 6
    assert new.trace["model_turns"] == 3
    assert len(new.trace["combined_reads"][0]) == 4


def test_registered_combined_tool_reads_real_aliases_and_conditions(
    tmp_path, monkeypatch
):
    from test_entity_statement_links import _client, _entity, _stmt

    with _client(tmp_path, monkeypatch) as client:
        entity = _entity(client, "RetryWorker")
        client.post(
            "/upsert-name", json={"text": "RetryBot", "entity_id": entity}
        ).raise_for_status()
        root = _stmt(client, "RetryWorker retries failed jobs.")
        target = _stmt(client, "The job returns to the queue.")
        condition = _stmt(client, "The retry budget is exhausted.")
        response = client.post(
            "/add-links",
            json={
                "links": [
                    {
                        "from_id": root,
                        "to_id": target,
                        "link_type": "triggers",
                        "when": {"op": "not", "of": [{"statement_id": condition}]},
                    }
                ]
            },
        )
        response.raise_for_status()
        response = client.post(
            "/retrieve-context", json={"query": "retry", "names": ["RetryBot"]}
        )
        response.raise_for_status()
        result = response.json()
        assert result["entities"][0]["id"] == entity
        statements = {s["id"]: s for s in result["statements"]}
        assert {root, target, condition} <= statements.keys()
        assert statements[root]["links"][0]["to_id"] == target
        assert statements[root]["links"][0]["when"] == {
            "op": "not",
            "of": [{"statement_id": condition}],
        }
        assert statements[target]["incoming_links"][0]["from_id"] == root
        assert statements[condition]["when_references"][0]["from_id"] == root
        assert (
            client.post(
                "/retrieve-context",
                json={"query": "retry", "names": ["RetryBot"], "linked_limit": 99},
            ).status_code
            == 422
        )


def test_combined_caps_keep_the_original_reverse_edge_total():
    root = {
        **ROOT,
        "incoming_links": [
            {"from_id": f"stm_{i}", "link_type": "triggers"} for i in range(25)
        ],
        "incoming_links_truncated": 200,
    }
    result = retrieve_context(Reads([root]), query="retry", names=["Worker"])
    assert len(result["statements"][0]["incoming_links"]) == 20
    assert result["statements"][0]["incoming_links_truncated"] == 200
