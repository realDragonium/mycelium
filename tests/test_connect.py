"""The connect pass: the ingest loop over existing statements, narrowed to
proposals that connect them.

Runs the real loop with the fakes from `test_ingest`: no server, DB or model.
"""

from __future__ import annotations

import pytest

from mycelium import ai
from mycelium.ingest import DraftCreated, IngestConfig, NothingToIngest
from mycelium.ingest.connect import Looked, Target, looked_at, run_connect
from mycelium.product_settings import IngestSettings
from test_ingest import (
    FakeAnthropic,
    FakeEmitter,
    FakeSubstrate,
    _emit_input,
    _ledger_row,
    _message,
    _op,
    _tool_use,
)

EXPORT = Target("stm_export", "event", "an invoice export is started")
QUEUED = Target("stm_queued", "state", "the export job is queued")
BATCH = (EXPORT, QUEUED)
NEIGHBOURS = [
    {"id": "stm_invoice", "kind": "capability", "text": "an admin can export invoices"},
    {"id": "stm_other", "kind": "rule", "text": "an export job retries twice"},
    {"id": "stm_paused", "kind": "state", "text": "the export job is paused"},
]


def _reads():
    return [
        _message([_tool_use("search_statements", {"query": "invoice export"})]),
        _message([_tool_use("search_statements", {"query": "export job"})]),
    ]


def _statements(_arguments):
    rows = NEIGHBOURS + [{"id": t.id, "kind": t.kind, "text": t.text} for t in BATCH]
    return {"statements": rows}


def _connect(ops, *, known=(), **config):
    emit = _emit_input(
        ops=ops,
        ledger=[
            _ledger_row(
                t.id, "new", matched=["stm_invoice"], considered=["stm_invoice"]
            )
            for t in BATCH
        ],
    )
    client = FakeAnthropic([*_reads(), _message([_tool_use("emit_draft", emit)])])
    emitter = FakeEmitter(
        {"add_links", "upsert_entity", "upsert_statement", "alias_suggestion"}
    )
    result = run_connect(
        BATCH,
        known_name=lambda name: name in known,
        client=client,
        substrate=FakeSubstrate({"get_statements": _statements}),
        emitter=emitter,
        config=IngestConfig(
            trace_log_path=None,
            model="claude-sonnet-4-6",
            limits=IngestSettings(**config),
        ),
    )
    return result, emitter, client


def _edge(source, target, link_type="contains"):
    return {"from_id": source, "to_id": target, "link_type": link_type}


def test_queues_links_that_touch_the_batch_as_one_draft():
    result, emitter, client = _connect(
        [_op("add_links", {"links": [_edge("stm_invoice", "stm_export")]})]
    )

    assert isinstance(result, DraftCreated)
    assert emitter.created == ["connect: 2 statements"]
    assert emitter.queued == [
        (
            result.draft_id,
            "add_links",
            {"links": [_edge("stm_invoice", "stm_export")]},
        )
    ]
    opening = str(client.calls[0]["messages"][0]["content"])
    assert "stm_export" in opening and "the export job is queued" in opening


def test_never_proposes_a_statement_change():
    result, emitter, _ = _connect(
        [
            _op("upsert_statement", {"kind": "event", "text": "an export fails"}),
            _op("add_links", {"links": [_edge("stm_invoice", "stm_queued")]}),
        ]
    )

    assert [kind for _, kind, _ in emitter.queued] == ["add_links"]
    assert isinstance(result, DraftCreated)
    assert any("only links and names" in line for line in result.flagged)


def test_drops_edges_away_from_the_batch_and_self_links():
    result, emitter, _ = _connect(
        [
            _op(
                "add_links",
                {
                    "links": [
                        _edge("stm_invoice", "stm_other"),
                        _edge("stm_export", "stm_export"),
                        _edge("stm_export", "stm_queued", "next"),
                    ]
                },
            )
        ]
    )

    assert emitter.queued[0][2] == {
        "links": [_edge("stm_export", "stm_queued", "next")]
    }
    assert isinstance(result, DraftCreated)
    assert sum("edge dropped" in line for line in result.flagged) == 2


def test_a_batch_statement_may_be_the_condition_but_not_of_its_own_edge():
    result, emitter, _ = _connect(
        [
            _op(
                "add_links",
                {
                    "links": [
                        {
                            **_edge("stm_invoice", "stm_other"),
                            "when": {"statement_id": "stm_queued"},
                        },
                        {
                            **_edge("stm_invoice", "stm_queued"),
                            "when": {"statement_id": "stm_queued"},
                        },
                    ]
                },
            )
        ]
    )

    assert [e["to_id"] for e in emitter.queued[0][2]["links"]] == ["stm_other"]
    assert isinstance(result, DraftCreated)
    assert any("one of its own ends" in line for line in result.flagged)


def test_never_joins_two_states_with_composes():
    result, emitter, _ = _connect(
        [
            _op(
                "add_links",
                {
                    "links": [
                        _edge("stm_queued", "stm_paused", "composes"),
                        _edge("stm_invoice", "stm_export"),
                    ]
                },
            )
        ]
    )

    assert emitter.queued[0][2] == {"links": [_edge("stm_invoice", "stm_export")]}
    assert isinstance(result, DraftCreated)
    assert any("joins two states" in line for line in result.flagged)


def test_leaves_a_statement_it_finds_badly_phrased_unlinked():
    emit = _emit_input(
        ops=[
            _op(
                "add_links",
                {
                    "links": [
                        _edge("stm_invoice", "stm_queued"),
                        {
                            **_edge("stm_invoice", "stm_other"),
                            "when": {"statement_id": "stm_queued"},
                        },
                        _edge("stm_invoice", "stm_export"),
                    ]
                },
            )
        ],
        ledger=[
            _ledger_row(
                "stm_export", "new", matched=["stm_invoice"], considered=["stm_invoice"]
            ),
            _ledger_row(
                "stm_queued",
                "unphraseable",
                matched=["stm_invoice"],
                considered=["stm_invoice"],
                note="say what is queued",
            ),
        ],
    )
    client = FakeAnthropic([*_reads(), _message([_tool_use("emit_draft", emit)])])
    emitter = FakeEmitter({"add_links"})

    result = run_connect(
        BATCH,
        known_name=lambda _name: False,
        client=client,
        substrate=FakeSubstrate({"get_statements": _statements}),
        emitter=emitter,
        config=IngestConfig(model="claude-sonnet-4-6", trace_log_path=None),
    )

    assert emitter.queued[0][2] == {"links": [_edge("stm_invoice", "stm_export")]}
    assert isinstance(result, DraftCreated)
    assert sum("rephrase first" in line for line in result.flagged) == 2


def test_drops_a_wrong_way_edge_like_ingest():
    # `establishes` runs event -> state, so state -> event is flipped.
    result, emitter, _ = _connect(
        [
            _op(
                "add_links",
                {"links": [_edge("stm_queued", "stm_export", "establishes")]},
            )
        ]
    )

    assert emitter.queued == []
    assert isinstance(result, NothingToIngest)


def test_drops_an_edge_whose_kinds_break_its_type_even_if_not_flipped():
    # `accepts` only ends on a property; neither end here is one.
    result, emitter, _ = _connect(
        [
            _op(
                "add_links",
                {
                    "links": [
                        _edge("stm_invoice", "stm_queued", "accepts"),
                        _edge("stm_invoice", "stm_export"),
                    ]
                },
            )
        ]
    )

    assert emitter.queued[0][2] == {"links": [_edge("stm_invoice", "stm_export")]}
    assert isinstance(result, DraftCreated)
    assert any("`accepts` goes any -> property" in line for line in result.flagged)


def test_a_new_concept_must_be_named_by_the_batch_and_not_exist():
    result, emitter, _ = _connect(
        [
            _op("upsert_entity", {"name": "export job", "description": "queued work"}),
            _op("upsert_entity", {"name": "invoice export", "description": "rewrite"}),
            _op("upsert_entity", {"name": "billing portal", "description": "absent"}),
        ],
        known={"invoice export"},
    )

    assert [p["name"] for _, _, p in emitter.queued] == ["export job"]
    assert isinstance(result, DraftCreated)
    assert any("already names a concept" in line for line in result.flagged)
    assert any("would mention 'billing portal'" in line for line in result.flagged)


def test_an_alias_must_come_from_a_batch_statement_that_uses_it():
    def alias(statement_id, alias, quote):
        return _op(
            "alias_suggestion",
            {
                "entity_id": "ent_job",
                "alias": alias,
                "quote": quote,
                "reason": "the queue calls its jobs this",
                "ambiguity": "",
                "statement_id": statement_id,
            },
        )

    result, emitter, _ = _connect(
        [
            alias("stm_queued", "export job", "the export job is queued"),
            alias("stm_export", "export job", "an invoice export is started"),
            alias("stm_invoice", "invoices", "an admin can export invoices"),
        ]
    )

    assert [(kind, p["statement_id"]) for _, kind, p in emitter.queued] == [
        ("alias_suggestion", "stm_queued")
    ]
    assert isinstance(result, DraftCreated)
    assert result.alias_draft_id == result.draft_id


def test_stops_reading_while_another_turn_and_the_final_emit_fit_under_the_cap():
    # A read over 10k cached tokens costs $0.0031, but the forced emit writes
    # that history to the cache again ($0.0376): the next read would not fit.
    read = _reads()[0]
    read.usage.cache_read_input_tokens = 10_000
    emit = _emit_input(ledger=[_ledger_row("stm_export", "unphraseable", note="none")])
    client = FakeAnthropic([read, _message([_tool_use("emit_draft", emit)])])

    result = run_connect(
        BATCH,
        known_name=lambda _name: False,
        client=client,
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=IngestConfig(
            model="claude-sonnet-4-6",
            trace_log_path=None,
            max_cost_usd=0.04,
        ),
    )

    assert result.trace["forced_finalize"] == "cost_cap"
    assert len(client.calls) == 2
    assert result.trace["cost_usd"] < 0.04


def test_its_model_calls_are_metered_as_connect_and_a_spent_budget_pauses_it():
    calls: list[ai.usage.Call] = []
    ai.usage.install(calls.append)
    try:
        result, _, _ = _connect(
            [_op("add_links", {"links": [_edge("stm_invoice", "stm_export")]})]
        )
        ai.usage.install(
            calls.append, lambda action: "Budget spent" if action == "connect" else None
        )
        with pytest.raises(ai.usage.Paused, match="Budget spent"):
            _connect([])
    finally:
        ai.usage.install(None)

    assert calls and {call.action for call in calls} == {"connect"}
    assert {call.run_id for call in calls} == {result.trace["run_id"]}


def test_reports_what_it_made_of_each_statement_it_reached():
    trace = {
        "candidate_ledger": [
            _ledger_row(
                "stm_export",
                "new",
                matched=["stm_invoice", "stm_export"],
                considered=["stm_other", "stm_invoice", "ent_job"],
            ),
            _ledger_row("stm_queued", "unphraseable", note="say what is queued"),
            _ledger_row("stm_invoice", "new"),
        ]
    }

    assert looked_at(trace, BATCH) == [
        Looked("stm_export", ("stm_invoice", "stm_other"), None),
        Looked("stm_queued", (), "say what is queued"),
    ]
    trace["candidate_ledger"][1]["classification"] = "unprocessed"
    assert [item.statement_id for item in looked_at(trace, BATCH)] == ["stm_export"]
