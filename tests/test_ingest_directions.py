from mycelium.ingest import directions

EXISTING = {"stm_upload": directions.Statement(kind="event", text="A logo is uploaded")}


def _draft(edge_key: str, edge: dict) -> list[dict]:
    """A new state and a new event; the event carries `edge`."""
    return [
        {
            "op": "upsert_statements",
            "payload": {
                "statements": [
                    {"kind": "state", "text": "A workspace has a logo", "links": []},
                    {"kind": "event", "text": "A logo is replaced", edge_key: [edge]},
                ]
            },
        }
    ]


def test_a_flipped_edge_is_dropped_and_its_statement_kept():
    ops = _draft("incoming_links", {"from_id": "@0", "link_type": "establishes"})
    ops[0]["payload"]["statements"][0]["links"] = [
        {"to_id": "@1", "link_type": "triggers"}
    ]

    kept, dropped = directions.without_flipped(ops, EXISTING)

    first, second = kept[0]["payload"]["statements"]
    assert first["links"] == [{"to_id": "@1", "link_type": "triggers"}]
    assert second["incoming_links"] == []
    assert len(dropped) == 1 and "establishes" in dropped[0]
    assert ops[0]["payload"]["statements"][1]["incoming_links"]


def test_an_edge_against_an_existing_statements_kind_is_dropped():
    ops = [
        {
            "op": "upsert_statement",
            "payload": {
                "kind": "state",
                "text": "A workspace has a logo",
                "links": [{"to_id": "stm_upload", "link_type": "establishes"}],
                "incoming_links": [
                    {"from_id": "stm_upload", "link_type": "establishes"}
                ],
            },
        }
    ]

    assert directions.existing_ids(ops) == ["stm_upload"]
    kept, dropped = directions.without_flipped(ops, EXISTING)

    assert kept[0]["payload"]["links"] == []
    assert kept[0]["payload"]["incoming_links"] == ops[0]["payload"]["incoming_links"]
    assert dropped == [
        '"A workspace has a logo" -establishes-> "A logo is uploaded": link '
        "direction looks flipped: `establishes` goes any -> state, but this edge "
        "goes state -> event; swap from_id and to_id"
    ]
