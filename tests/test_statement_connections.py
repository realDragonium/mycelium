from __future__ import annotations

from collections.abc import Callable

import pytest

from mycelium.statement_connections import (
    Candidate,
    ConditionGroup,
    ConditionLeaf,
    Direction,
    Edge,
    EdgeBatch,
    Endpoint,
    Limits,
    Result,
    Search,
    Statement,
    resolve_endpoint,
)


def statement(sid: str) -> Statement:
    return Statement(id=sid, kind="action", text=sid)


def run_search(
    edges: list[Edge],
    source: str = "a",
    target: str = "z",
    direction: Direction = "both",
    limits: Limits | None = None,
    get_statement: Callable[[str], Statement | None] = statement,
    required: list[str] | None = None,
) -> Result:
    def read(sid: str, limit: int) -> EdgeBatch:
        adjacent = [
            e
            for e in edges
            if (
                sid == e.from_id if direction == "forward" else sid in e.statement_ids()
            )
        ]
        return EdgeBatch(
            tuple(adjacent[:limit]), min(limit, len(adjacent)), len(adjacent) > limit
        )

    return Search(
        read,
        get_statement,
        Result(
            source=Endpoint(input=source, status="id", selected_id=source),
            target=Endpoint(input=target, status="id", selected_id=target),
            required=[
                Endpoint(input=sid, status="id", selected_id=sid)
                for sid in (required or [])
            ],
            status="needs_resolution",
            direction=direction,
            link_types=None,
            limits=limits or Limits(),
        ),
    ).run()


def edge(number: int, source: str, target: str) -> Edge:
    return Edge(id=number, from_id=source, to_id=target, link_type="next")


def test_returns_short_and_long_routes_without_unrelated_branches_or_cycles():
    result = run_search(
        [
            edge(1, "a", "z"),
            edge(2, "a", "b"),
            edge(3, "b", "c"),
            edge(4, "c", "z"),
            edge(5, "b", "unused"),
            edge(6, "b", "b"),
        ]
    )
    assert result.status == "found"
    assert [r.statement_ids for r in result.routes] == [
        ["a", "z"],
        ["a", "b", "c", "z"],
    ]
    assert {e.id for e in result.edges} == {1, 2, 3, 4}
    assert {s.id for s in result.statements} == {"a", "b", "c", "z"}
    assert not result.truncated


def test_shared_input_is_connected_only_when_reverse_steps_are_allowed():
    edges = [edge(1, "a", "input"), edge(2, "z", "input")]
    result = run_search(edges)
    assert [s.traversal for s in result.routes[0].steps] == ["forward", "reverse"]
    assert result.edges[1].from_id == "z"
    assert result.edges[1].to_id == "input"
    forward = run_search(edges, direction="forward")
    assert forward.status == "not_found_within_limits"
    assert not forward.truncated


def test_parallel_conditional_edges_remain_distinct_routes_with_full_context():
    when = ConditionGroup(
        op="and",
        of=[
            ConditionLeaf(statement_id="ready"),
            ConditionGroup(op="not", of=[ConditionLeaf(statement_id="blocked")]),
        ],
    )
    result = run_search(
        [
            edge(1, "a", "z"),
            Edge(id=2, from_id="a", to_id="z", link_type="next", when=when),
        ],
        direction="forward",
    )
    assert [r.statement_ids for r in result.routes] == [["a", "z"], ["a", "z"]]
    assert [r.steps[0].edge_id for r in result.routes] == [1, 2]
    assert result.edges[1].when == when
    assert {s.id for s in result.statements} == {"a", "z", "ready", "blocked"}


@pytest.mark.parametrize(
    "source,target", [("blocked", "z"), ("a", "blocked"), ("blocked", "ready")]
)
def test_condition_participation_is_explicit_in_either_direction(
    source: str, target: str
):
    when = ConditionGroup(
        op="or",
        of=[
            ConditionLeaf(statement_id="ready"),
            ConditionGroup(op="not", of=[ConditionLeaf(statement_id="blocked")]),
        ],
    )
    edges = [Edge(id=1, from_id="a", to_id="z", link_type="next", when=when)]
    result = run_search(edges, source, target)
    assert len(result.routes) == 1
    assert result.routes[0].steps[0].traversal == "condition"
    assert result.edges[0].when == when
    assert (
        run_search(edges, source, target, direction="forward").status
        == "not_found_within_limits"
    )


def test_hop_limit_and_same_endpoint_have_precise_results():
    edges = [edge(1, "a", "b"), edge(2, "b", "z")]
    assert (
        run_search(edges, limits=Limits(max_hops=1)).status == "not_found_within_limits"
    )
    same = run_search(edges, "a", "a", limits=Limits(max_hops=0))
    assert same.routes[0].statement_ids == ["a"]
    assert same.routes[0].steps == []
    assert same.expansions == same.edge_reads == 0


def test_route_limit_is_reported_only_when_another_route_is_found():
    edges = [edge(1, "a", "z"), edge(2, "a", "b"), edge(3, "b", "z")]
    result = run_search(edges, limits=Limits(max_routes=1))
    assert len(result.routes) == 1
    assert result.stop_reasons == ["max_routes"]
    assert not run_search(edges[:1], limits=Limits(max_routes=1)).truncated


def test_edge_budget_retains_discovered_routes_and_does_not_claim_disconnection():
    edges = [edge(1, "a", "z"), edge(2, "a", "b")]
    result = run_search(edges, limits=Limits(max_expansions=1))
    assert result.status == "found"
    assert result.stop_reasons == ["max_edge_reads"]
    assert result.expansions == result.edge_reads == 1
    missing = run_search(list(reversed(edges)), limits=Limits(max_expansions=1))
    assert missing.status == "incomplete"
    assert missing.truncated


def test_expansion_budget_keeps_terminal_routes_already_queued():
    # One edge generates multiple condition-participation steps.
    conditional = Edge(
        id=1,
        from_id="a",
        to_id="z",
        link_type="next",
        when=ConditionLeaf(statement_id="ready"),
    )
    result = run_search([conditional], limits=Limits(max_expansions=1))
    assert result.status == "found"
    assert result.stop_reasons == ["max_expansions"]
    assert result.expansions == 1


def test_response_limit_never_returns_a_partial_condition_or_route():
    def large_statement(sid: str) -> Statement:
        return Statement(id=sid, kind="action", text="x" * 40_000)

    result = run_search([edge(1, "a", "z")], get_statement=large_statement)
    assert result.status == "incomplete"
    assert result.stop_reasons == ["output_limit"]
    assert result.routes == result.edges == result.statements == []


def test_id_resolution_never_calls_search_and_missing_ids_are_not_queries():
    def unexpected_search(query: str) -> list[Candidate]:
        raise AssertionError("IDs must not embed")

    assert (
        resolve_endpoint("stm_a", statement, unexpected_search).selected_id == "stm_a"
    )
    assert (
        resolve_endpoint("stm_missing", lambda _: None, unexpected_search).status
        == "missing"
    )


@pytest.mark.parametrize(
    "scores,status,selected",
    [
        ([0.9, 0.7], "matched", "stm_0"),
        ([0.9, 0.89], "ambiguous", None),
        ([0.9, 0.9], "ambiguous", None),
        ([], "missing", None),
    ],
)
def test_text_resolution_reports_candidates_without_guessing_ambiguous_matches(
    scores: list[float],
    status: str,
    selected: str | None,
):
    candidates = [
        Candidate(id=f"stm_{i}", kind="action", text=f"step {i}", score=s)
        for i, s in enumerate(scores)
    ]
    result = resolve_endpoint("click save", statement, lambda _: candidates)
    assert result.status == status
    assert result.selected_id == selected
    assert result.candidates == candidates


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_hops": -1},
        {"max_hops": 9},
        {"max_routes": 0},
        {"max_routes": 21},
        {"max_expansions": 0},
        {"max_expansions": 10001},
        {"max_hops": True},
    ],
)
def test_limits_reject_unbounded_or_invalid_work(kwargs: dict[str, int]):
    with pytest.raises(ValueError):
        Limits(**kwargs)


def test_requirements_connect_on_branches_without_a_single_path_through_them():
    edges = [
        edge(1, "a", "z"),
        edge(2, "setting", "a"),
        edge(3, "page", "setting"),
        edge(4, "rule", "a"),
    ]
    result = run_search(edges, required=["page", "rule"])
    assert result.status == "found"
    assert result.connected_ids == ["a", "page", "rule", "z"]
    assert result.unconnected_ids == []
    assert [r.statement_ids for r in result.routes] == [
        ["a", "z"],
        ["a", "rule"],
        ["a", "setting", "page"],
    ]
    assert len(result.edges) == 4
    assert not result.truncated
    reversed_requirements = run_search(edges, required=["rule", "page"])
    assert reversed_requirements.routes == result.routes


def test_required_mode_keeps_exploring_beyond_target_and_replaces_prefix_routes():
    result = run_search(
        [edge(1, "a", "z"), edge(2, "z", "c"), edge(3, "c", "d")],
        required=["d", "c"],
        limits=Limits(max_routes=1),
    )
    assert result.status == "found"
    assert [r.statement_ids for r in result.routes] == [["a", "z", "c", "d"]]
    assert result.connected_ids == ["a", "c", "d", "z"]
    assert not result.truncated


def test_unreachable_requirement_returns_partial_coverage_without_claiming_truncation():
    result = run_search([edge(1, "a", "z"), edge(2, "x", "c")], required=["c"])
    assert result.status == "partial"
    assert result.connected_ids == ["a", "z"]
    assert result.unconnected_ids == ["c"]
    assert not result.truncated
    assert {s.id for s in result.statements} == {"a", "z"}


def test_required_branches_are_retained_when_target_is_unreachable():
    result = run_search([edge(1, "a", "c")], required=["c"])
    assert result.status == "partial"
    assert result.connected_ids == ["a", "c"]
    assert result.unconnected_ids == ["z"]


def test_required_statements_in_condition_context_need_an_actual_traversal():
    conditional = Edge(
        id=1,
        from_id="a",
        to_id="z",
        link_type="next",
        when=ConditionLeaf(statement_id="c"),
    )
    result = run_search([conditional], required=["c"], direction="forward")
    assert "c" in {s.id for s in result.statements}
    assert result.status == "partial"
    assert result.unconnected_ids == ["c"]
    both = run_search([conditional], required=["c"])
    assert both.status == "found"
    assert both.routes[1].steps[0].traversal == "condition"
    assert both.unconnected_ids == []


def test_requirements_share_work_and_route_budgets():
    edges = [edge(1, "a", "z"), edge(2, "a", "c"), edge(3, "a", "d")]
    work_limited = run_search(
        edges, required=["c", "d"], limits=Limits(max_expansions=2)
    )
    assert work_limited.status == "partial"
    assert work_limited.expansions <= 2
    assert work_limited.edge_reads <= 2
    assert work_limited.connected_ids == ["a", "c", "z"]
    assert work_limited.unconnected_ids == ["d"]
    assert work_limited.truncated
    route_limited = run_search(edges, required=["c", "d"], limits=Limits(max_routes=1))
    assert route_limited.status == "partial"
    assert route_limited.stop_reasons == ["max_routes"]
    assert route_limited.unconnected_ids == ["c", "d"]


def test_required_hop_limit_is_measured_from_source_and_root_duplicates_are_free():
    edges = [edge(1, "a", "z"), edge(2, "z", "c")]
    result = run_search(edges, required=["c"], limits=Limits(max_hops=1))
    assert result.status == "partial"
    assert result.unconnected_ids == ["c"]
    assert not result.truncated
    duplicate = run_search(
        [], source="a", target="a", required=["a", "a"], limits=Limits(max_hops=0)
    )
    assert duplicate.status == "found"
    assert duplicate.connected_ids == ["a"]
    assert len(duplicate.required) == 2
    assert len(duplicate.routes) == 1
    assert duplicate.expansions == 0


def test_required_mode_stops_after_coverage_instead_of_enumerating_alternatives():
    edges = [edge(1, "a", "z"), edge(2, "a", "c"), edge(3, "c", "z")]
    assert len(run_search(edges).routes) == 2
    assert run_search(edges, required=[]).model_dump() == run_search(edges).model_dump()
    covered = run_search(edges, required=["z", "z"])
    assert len(covered.routes) == 1
    assert covered.unconnected_ids == []


def test_no_reachable_goals_has_explicit_coverage_and_no_false_partial_graph():
    result = run_search([], required=["c"])
    assert result.status == "not_found_within_limits"
    assert result.connected_ids == ["a"]
    assert result.unconnected_ids == ["c", "z"]
    assert result.routes == []


def test_required_branch_output_limit_preserves_previous_connections():
    def text(sid: str) -> Statement:
        return Statement(
            id=sid, kind="action", text="x" * (64_000 if sid == "c" else 10)
        )

    result = run_search(
        [edge(1, "a", "z"), edge(2, "a", "c")], required=["c"], get_statement=text
    )
    assert result.status == "partial"
    assert result.stop_reasons == ["output_limit"]
    assert result.connected_ids == ["a", "z"]
    assert result.unconnected_ids == ["c"]
    assert [e.id for e in result.edges] == [1]
