from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import Context

from mycelium import auth, embed, server, store, vector
from mycelium.statement_connections import MAX_TEXT_CHARS, Result
from mycelium.store.connection_graph import ConnectionGraph


@pytest.fixture
def conn(monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    database = store.connect(":memory:")
    store.migrate(database)
    monkeypatch.setattr(server, "_db", lambda: database)
    yield database
    database.close()


def pair(conn: sqlite3.Connection) -> tuple[str, str]:
    a = store.create_statement(conn, "action", "Click Save.")
    b = store.create_statement(conn, "event", "The changes are saved.")
    store.insert_links(conn, [(a, b, "performs", None)])
    conn.commit()
    return a, b


def test_sql_reader_preserves_parallel_conditions_and_filters_types(
    conn: sqlite3.Connection,
):
    a, b = pair(conn)
    condition = store.create_statement(conn, "state", "The user is signed in.")
    store.insert_links(conn, [(a, b, "performs", {"statement_id": condition})])
    conn.commit()
    result = Result.model_validate(
        server.find_statement_connections(a, b, direction="forward")
    )
    assert len(result.routes) == len(result.edges) == 2
    assert {s.id for s in result.statements} == {a, b, condition}
    assert len({r.steps[0].edge_id for r in result.routes}) == 2
    assert not result.truncated
    assert (
        server.find_statement_connections(a, b, link_types=["next"])["status"]
        == "not_found_within_limits"
    )
    assert (
        server.find_statement_connections(a, b, link_types=[])["status"]
        == "not_found_within_limits"
    )


def test_sql_reader_can_start_at_a_negated_condition_and_excludes_entity_edges(
    conn: sqlite3.Connection,
):
    a, b = pair(conn)
    condition = store.create_statement(conn, "state", "The form is invalid.")
    when = {"op": "not", "of": [{"statement_id": condition}]}
    store.insert_links(conn, [(a, b, "performs", when)])
    entity = store.create_entity(conn, "A decorative entity")
    store.insert_entity_statement_links(
        conn, [(entity, condition, "se", "legacy", None)]
    )
    conn.commit()
    result = Result.model_validate(server.find_statement_connections(condition, b))
    assert result.status == "found"
    assert result.routes[0].steps[0].traversal == "condition"
    selected = next(
        e for e in result.edges if e.id == result.routes[0].steps[0].edge_id
    )
    assert selected.when is not None
    assert selected.when.model_dump() == when
    assert entity not in {s.id for s in result.statements}


def test_real_vector_resolution_reuses_search_ranking_without_hydrating_links(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    a, b = pair(conn)
    index = vector.Index.empty()
    names = vector.Index.empty()
    for i, sid in enumerate((a, b)):
        vec = [0.0] * vector.DIM
        vec[i] = 1.0
        store.set_vector_id(conn, sid, i)
        index.add(i, vec)
    conn.commit()
    monkeypatch.setattr(server, "_idx", lambda: index)
    monkeypatch.setattr(server, "_name_idx", lambda: names)
    monkeypatch.setattr(
        embed, "embed", lambda text: [1.0, 0.0] + [0.0] * (vector.DIM - 2)
    )
    result = Result.model_validate(
        server.find_statement_connections("save the form", b)
    )
    assert result.source.status == "matched"
    assert result.source.selected_id == a
    assert result.source.candidates[0].score == pytest.approx(1)
    assert result.status == "found"
    assert not conn.in_transaction


def test_unknown_and_ambiguous_endpoints_never_walk_graph(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    a, b = pair(conn)
    monkeypatch.setattr(
        server,
        "_search_statement_candidates",
        lambda *args: [(a, 0.9, 0.9), (b, 0.89, 0.89)],
    )
    result = Result.model_validate(server.find_statement_connections("save", b))
    assert result.status == "needs_resolution"
    assert result.source.status == "ambiguous"
    assert result.routes == []
    assert result.edge_reads == 0
    missing = Result.model_validate(server.find_statement_connections("stm_missing", b))
    assert missing.source.status == "missing"
    assert missing.status == "needs_resolution"


def test_hub_reads_and_large_conditions_are_bounded(conn: sqlite3.Connection):
    a, b = pair(conn)
    for i in range(20):
        node = store.create_statement(conn, "state", f"State {i} holds.")
        store.insert_links(conn, [(a, node, "establishes", None)])
    batch = ConnectionGraph(conn, "both", None).neighbors(a, 3)
    assert batch.has_more
    assert batch.rows_read == len(batch.edges) == 3
    conditions = [
        store.create_statement(conn, "state", f"Condition {i} holds.")
        for i in range(128)
    ]
    store.insert_links(
        conn,
        [
            (
                a,
                b,
                "conditional",
                {
                    "op": "and",
                    "of": [{"statement_id": sid} for sid in conditions],
                },
            )
        ],
    )
    result = Result.model_validate(
        server.find_statement_connections(a, b, link_types=["conditional"])
    )
    assert result.status == "incomplete"
    assert result.stop_reasons == ["condition_limit"]


def test_text_is_explicitly_truncated_and_the_tool_does_not_commit_a_callers_transaction(
    conn: sqlite3.Connection,
):
    a, b = pair(conn)
    store.update_statement_text(conn, a, "x" * (MAX_TEXT_CHARS + 1))
    assert conn.in_transaction
    result = Result.model_validate(server.find_statement_connections(a, b))
    assert conn.in_transaction
    assert result.source.candidates[0].text_truncated
    assert len(result.source.candidates[0].text) == MAX_TEXT_CHARS
    conn.rollback()
    saved = store.get_statement(conn, a)
    assert saved is not None
    assert saved["text"] == "Click Save."


def test_response_envelope_is_bounded_even_when_no_route_can_be_returned(
    conn: sqlite3.Connection,
):
    a, b = pair(conn)
    with pytest.raises(ValueError, match="response limit"):
        server.find_statement_connections(a, b, link_types=["\x00" * 200] * 100)


def test_sparse_adjacency_does_not_scan_unrelated_edges(conn: sqlite3.Connection):
    a, b = pair(conn)
    other = store.create_statement(conn, "event", "Another flow runs.")
    store.insert_links(conn, [(other, other, f"type_{i}", None) for i in range(1000)])
    condition = store.create_statement(conn, "state", "A condition holds.")
    store.insert_links(conn, [(a, b, "conditional", {"statement_id": condition})])
    instructions = 0

    def check_budget() -> int:
        nonlocal instructions
        instructions += 100
        return int(instructions > 2000)

    conn.set_progress_handler(check_budget, 100)
    try:
        graph = ConnectionGraph(conn, "both", None)
        assert len(graph.neighbors(a, 3).edges) == 2
        assert len(graph.neighbors(b, 3).edges) == 2
        assert len(graph.neighbors(condition, 3).edges) == 1
    finally:
        conn.set_progress_handler(None, 0)


def test_rest_and_mcp_dispatch_return_the_same_graph_for_a_reader(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    a, b = pair(conn)
    from mycelium.http import app

    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    # No lifespan: this test supplies only an isolated, in-memory substrate.
    response = TestClient(app).post(
        "/find-statement-connections", json={"source": a, "target": b}
    )
    assert response.status_code == 200, response.text
    mcp_tool = next(
        t
        for t in server.mcp._tool_manager.list_tools()
        if t.name == "find_statement_connections"
    )
    assert {"source", "target"} <= set(mcp_tool.parameters["properties"])
    token = auth.current_principal.set(
        auth.Principal(id="reader", name="Reader", role="reader", type="service")
    )
    try:
        result = asyncio.run(mcp_tool.run({"source": a, "target": b}, Context()))
    finally:
        auth.current_principal.reset(token)
    assert result == response.json()


def test_required_text_and_ids_resolve_once_and_connect_on_separate_branches(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    a, b = pair(conn)
    page = store.create_statement(conn, "event", "The settings page opens.")
    rule = store.create_statement(conn, "rule", "Saved changes become visible.")
    store.insert_links(
        conn, [(page, a, "configures", None), (rule, b, "governs", None)]
    )
    searches: list[str] = []

    def candidates(
        query: str, limit: int, min_score: float
    ) -> list[tuple[str, float, float]]:
        searches.append(query)
        return [(page, 0.9, 0.9)]

    monkeypatch.setattr(server, "_search_statement_candidates", candidates)
    result = Result.model_validate(
        server.find_statement_connections(
            a,
            b,
            required=["settings page", rule, " settings page "],
        )
    )
    assert result.status == "found"
    assert searches == ["settings page"]
    assert [r.selected_id for r in result.required] == [page, rule, page]
    assert result.required[0].status == "matched"
    assert result.connected_ids == sorted([a, b, page, rule])
    assert result.unconnected_ids == []
    assert len(result.routes) == 2


@pytest.mark.parametrize("missing", [True, False])
def test_unresolved_requirement_blocks_the_walk_and_reports_candidates(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    missing: bool,
):
    a, b = pair(conn)
    monkeypatch.setattr(
        server,
        "_search_statement_candidates",
        lambda *args: [(a, 0.9, 0.9), (b, 0.89, 0.89)],
    )
    result = Result.model_validate(
        server.find_statement_connections(
            a,
            b,
            required=["stm_missing" if missing else "a setting"],
        )
    )
    assert result.status == "needs_resolution"
    assert result.required[0].status == ("missing" if missing else "ambiguous")
    assert len(result.required[0].candidates) == (0 if missing else 2)
    assert result.edge_reads == result.expansions == 0
    assert result.routes == result.connected_ids == result.unconnected_ids == []


def test_required_branch_respects_link_type_filters(conn: sqlite3.Connection):
    a, b = pair(conn)
    page = store.create_statement(conn, "event", "The settings page opens.")
    store.insert_links(conn, [(a, page, "configures", None)])
    result = Result.model_validate(
        server.find_statement_connections(
            a,
            b,
            required=[page],
            link_types=["performs"],
        )
    )
    assert result.status == "partial"
    assert result.unconnected_ids == [page]
    assert not result.truncated


def test_required_statements_work_through_http_and_mcp(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    a, b = pair(conn)
    page = store.create_statement(conn, "event", "The settings page opens.")
    store.insert_links(conn, [(page, a, "configures", None)])
    from mycelium.http import app

    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    arguments = {"source": a, "target": b, "required": [page]}
    response = TestClient(app).post("/find-statement-connections", json=arguments)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "found"
    assert response.json()["unconnected_ids"] == []
    mcp_tool = next(
        t
        for t in server.mcp._tool_manager.list_tools()
        if t.name == "find_statement_connections"
    )
    assert "required" in mcp_tool.parameters["properties"]
    assert "required" not in mcp_tool.parameters["required"]
    assert asyncio.run(mcp_tool.run(arguments, Context())) == response.json()


@pytest.mark.parametrize("required", [["stm_a"] * 9, [" "], ["x" * 2001]])
def test_invalid_required_inputs_are_rejected_before_resolving(
    required: list[str],
    monkeypatch: pytest.MonkeyPatch,
):
    def unexpected_db() -> sqlite3.Connection:
        raise AssertionError("invalid requests must not read the substrate")

    monkeypatch.setattr(server, "_db", unexpected_db)
    with pytest.raises(ValueError):
        server.find_statement_connections("stm_a", "stm_b", required=required)


@pytest.mark.parametrize(
    "body",
    [
        {"source": " ", "target": "stm_b"},
        {"source": "stm_a", "target": "stm_b", "max_hops": 9},
        {"source": "stm_a", "target": "stm_b", "direction": "backward"},
    ],
)
def test_rest_rejects_invalid_requests_without_search(body: dict[str, str | int]):
    from mycelium.http import app

    response = TestClient(app).post("/find-statement-connections", json=body)
    assert response.status_code in (400, 422)
