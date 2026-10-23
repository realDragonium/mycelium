"""The connect pass: the ingest loop over existing statements, narrowed to
proposals that connect them.

Runs the real loop with the fakes from `test_ingest`: no server, DB or model.
"""

from __future__ import annotations

from mycelium.ingest import DraftCreated, IngestConfig, NothingToIngest
from mycelium.ingest.connect import Target, run_connect
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
NEIGHBOUR = {
    "id": "stm_invoice",
    "kind": "capability",
    "text": "an admin can export invoices",
}


def _reads():
    return [
        _message([_tool_use("search_statements", {"query": "invoice export"})]),
        _message([_tool_use("survey_statements", {"query": "export job"})]),
    ]


def _statements(_arguments):
    rows = [NEIGHBOUR] + [{"id": t.id, "kind": t.kind, "text": t.text} for t in BATCH]
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
        config=IngestConfig(trace_log_path=None, **config),
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
        (result.draft_id, "add_links", {"links": [_edge("stm_invoice", "stm_export")]})
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


def test_stops_reading_once_the_spending_cap_is_reached():
    emit = _emit_input(ledger=[_ledger_row("stm_export", "unphraseable", note="none")])
    client = FakeAnthropic([_reads()[0], _message([_tool_use("emit_draft", emit)])])

    result = run_connect(
        BATCH,
        known_name=lambda _name: False,
        client=client,
        substrate=FakeSubstrate(),
        emitter=FakeEmitter(),
        config=IngestConfig(
            trace_log_path=None,
            max_cost_usd=0.00001,
            input_per_mtok=3.0,
            output_per_mtok=15.0,
        ),
    )

    assert result.trace["forced_finalize"] == "cost_cap"
    assert len(client.calls) == 2
