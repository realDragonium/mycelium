import pytest

from mycelium import draft_corrections
from mycelium.draft_corrections import Corrected, Operation
from review_helpers import correction


def _batch():
    return Operation(
        ref="op_batch",
        seq=1,
        kind="upsert_statements",
        payload={
            "statements": [
                {
                    "kind": "capability",
                    "text": "A workspace admin can export invoices.",
                },
                {"kind": "event", "text": "The export is queued."},
                {
                    "kind": "state",
                    "text": "Exports are kept for seven days.",
                    "links": [{"to_id": "stm_retention", "link_type": "refines"}],
                },
                {
                    "kind": "event",
                    "text": "The admin receives an email with the export.",
                    "incoming_links": [
                        {
                            "from_id": "@1",
                            "link_type": "triggers",
                            "when": {"statement_id": "@2"},
                        }
                    ],
                },
            ]
        },
    )


def _links():
    return Operation(
        ref="op_links",
        seq=2,
        kind="add_links",
        payload={
            "links": [
                {"from_id": "@1:0", "to_id": "@1:3", "link_type": "triggers"},
                {"from_id": "stm_sso", "to_id": "@1:0", "link_type": "requires"},
            ]
        },
    )


def _link(from_id, link_type, to_id, when_json=None):
    return {
        "from_id": from_id,
        "link_type": link_type,
        "to_id": to_id,
        "when_json": when_json,
    }


def test_edit_changes_one_statement_and_nothing_else():
    batch = _batch()
    result = draft_corrections.apply(
        [batch, _links()],
        [
            correction(
                "edit",
                operation_ref="op_batch",
                statement=1,
                text="The export job is queued.",
            )
        ],
    )
    statements = result.payloads["op_batch"]["statements"]
    assert statements[1]["text"] == "The export job is queued."
    assert [s for i, s in enumerate(statements) if i != 1] == [
        s for i, s in enumerate(batch.payload["statements"]) if i != 1
    ]
    assert result.payloads["op_links"] == _links().payload


def test_dropping_a_statement_keeps_every_other_reference_on_its_target():
    result = draft_corrections.apply(
        [_batch(), _links()],
        [
            correction(
                "drop_link",
                operation_ref="op_links",
                link=_link("@1:0", "triggers", "@1:3"),
            ),
            correction(
                "drop_link",
                operation_ref="op_links",
                link=_link("stm_sso", "requires", "@1:0"),
            ),
            correction(
                "add_link",
                operation_ref="op_links",
                link=_link("stm_sso", "requires", "@1:3"),
            ),
            correction("drop_statement", operation_ref="op_batch", statement=0),
        ],
    )
    statements = result.payloads["op_batch"]["statements"]
    assert [s["text"] for s in statements] == [
        "The export is queued.",
        "Exports are kept for seven days.",
        "The admin receives an email with the export.",
    ]
    assert statements[2]["incoming_links"] == [
        {"from_id": "@0", "link_type": "triggers", "when": {"statement_id": "@1"}}
    ]
    assert result.payloads["op_links"]["links"] == [
        {"from_id": "stm_sso", "to_id": "@1:2", "link_type": "requires"}
    ]


def test_indices_name_the_draft_as_submitted():
    result = draft_corrections.apply(
        [_batch()],
        [
            correction("drop_statement", operation_ref="op_batch", statement=0),
            correction("edit", operation_ref="op_batch", statement=2, kind="property"),
        ],
    )
    statements = result.payloads["op_batch"]["statements"]
    assert statements[1] == {**_batch().payload["statements"][2], "kind": "property"}


def test_a_statement_still_named_elsewhere_cannot_drop():
    with pytest.raises(ValueError, match=r"still named by op_links as @1:3"):
        draft_corrections.apply(
            [_batch(), _links()],
            [correction("drop_statement", operation_ref="op_batch", statement=3)],
        )


def test_batch_links_are_added_where_their_batch_end_is():
    result = draft_corrections.apply(
        [_batch()],
        [
            correction(
                "add_link", operation_ref="op_batch", link=_link("@0", "contains", "@1")
            ),
            correction(
                "add_link",
                operation_ref="op_batch",
                link=_link("stm_billing", "contains", "@2"),
            ),
        ],
    )
    statements = result.payloads["op_batch"]["statements"]
    assert statements[0]["links"] == [{"to_id": "@1", "link_type": "contains"}]
    assert statements[2]["incoming_links"] == [
        {"from_id": "stm_billing", "link_type": "contains"}
    ]


def test_dropping_a_batch_link_removes_only_that_link():
    result = draft_corrections.apply(
        [_batch()],
        [
            correction(
                "drop_link",
                operation_ref="op_batch",
                link=_link("@1", "triggers", "@3"),
            )
        ],
    )
    assert result.payloads["op_batch"]["statements"][3]["incoming_links"] == []
    assert result.payloads["op_batch"]["statements"][2]["links"] == [
        {"to_id": "stm_retention", "link_type": "refines"}
    ]


@pytest.mark.parametrize(
    ("fix", "message"),
    [
        (
            correction(
                "drop_link",
                operation_ref="op_batch",
                link=_link("@1", "requires", "@3"),
            ),
            "has no link @1 requires @3",
        ),
        (
            correction(
                "add_link",
                operation_ref="op_batch",
                link=_link("stm_a", "requires", "stm_b"),
            ),
            'needs one end in its batch, written "@N"',
        ),
        (
            correction(
                "add_link",
                operation_ref="op_batch",
                link=_link("@1", "triggers", "@3", '{"statement_id": "@2"}'),
            ),
            "already has that link",
        ),
        (
            correction("edit", operation_ref="op_batch", statement=4, text="Text."),
            "statement 4 names none of them",
        ),
        (
            correction(
                "edit", operation_ref="op_batch", statement=0, description="A note."
            ),
            "changes only kind, text",
        ),
        (
            correction(
                "edit",
                operation_ref="op_batch",
                statement=0,
                link=_link("@0", "contains", "@1"),
            ),
            "edit takes no link",
        ),
        (
            correction("drop_statement", operation_ref="op_batch"),
            "statement None names none of them",
        ),
    ],
)
def test_a_correction_that_does_not_fit_the_draft_is_refused(fix, message):
    with pytest.raises(ValueError, match=message):
        draft_corrections.apply([_batch()], [fix])


def test_a_struck_operation_takes_no_other_correction():
    with pytest.raises(ValueError, match="is struck"):
        draft_corrections.apply(
            [_batch(), _links()],
            [
                correction("strike", operation_ref="op_links"),
                correction(
                    "drop_link",
                    operation_ref="op_links",
                    link=_link("@1:0", "triggers", "@1:3"),
                ),
            ],
        )


def test_a_result_that_changes_an_unnamed_statement_is_refused():
    batch = _batch()
    tampered = batch.payload | {
        "statements": [
            {**batch.payload["statements"][0], "text": "Changed."},
            *batch.payload["statements"][1:],
        ]
    }
    with pytest.raises(ValueError, match="changed statement 0 of op_batch"):
        draft_corrections._check_intact(
            [batch],
            [correction("edit", operation_ref="op_batch", statement=1, kind="state")],
            Corrected(payloads={"op_batch": tampered}, struck=[]),
            {},
        )
