from __future__ import annotations

from mycelium.connect import extract as ex

TEXT = """When the invite is sent, a reminder is scheduled. Notification cadence can be configured on Company.

- Click Save to apply the change.
- The user logs in and receives a token.
- Blue widgets."""


def test_extracts_the_measured_paragraph():
    result = ex.extract(TEXT)

    assert [(item.fragment_index, item.kind, item.text) for item in result.items] == [
        (0, "event", "the invite is sent"),
        (1, "event", "a reminder is scheduled"),
        (2, "capability", "Notification cadence can be configured on Company"),
        (3, "action", "Click Save to apply the change"),
        (6, "property", "Blue widgets"),
    ]
    assert [(flag.fragment_index, flag.reason) for flag in result.flags] == [
        (4, "unmatched"),
        (5, "unmatched"),
    ]
    assert result.condition_links == [(1, 0)]


def test_empty_and_whitespace_only_text():
    assert ex.extract("") == ex.Extraction([], [], [], [])
    assert ex.extract("   \n ") == ex.Extraction([], [], [], [])


def test_unsplit_fragment_is_flagged_without_classification():
    result = ex.extract(
        "The service starts and records the time when the token expires"
    )

    assert result.items == []
    assert [(flag.fragment_index, flag.reason) for flag in result.flags] == [
        (0, "unmatched"),
        (1, "unsplit"),
    ]
    assert result.flags[1].detail


def test_dropped_condition_link_is_recorded_on_both_surviving_records():
    result = ex.extract("When the invite is sent, the user logs in")
    note = "dropped requires link: claim fragment 1 → condition fragment 0"

    assert [(item.fragment_index, item.note) for item in result.items] == [(0, note)]
    assert [(flag.fragment_index, flag.reason) for flag in result.flags] == [
        (1, "unmatched")
    ]
    assert result.flags[0].detail == f"no phrasing shape matched — {note}"
    assert result.condition_links == []


def test_ambiguous_classification_is_flagged_with_its_shape_matches():
    # The initial command and the embedded modal match check and capability.
    result = ex.extract("Verify the report can be downloaded")

    assert result.items == []
    assert [(flag.fragment_index, flag.reason) for flag in result.flags] == [
        (0, "ambiguous")
    ]
    assert result.flags[0].detail == (
        "capability (capability-modal: can); check (check-imperative: Verify)"
    )


def test_flag_sources_cover_every_emitted_reason():
    assert {
        "unsplit",
        "ambiguous",
        "unmatched",
        "phrasing",
        "flip",
        "depends_on_rejected",
    } <= ex.FLAG_SOURCES.keys()


def test_resolved_cut_produces_left_to_right_item_link():
    result = ex.extract(
        "The invite is created and then the reminder is scheduled",
        aliases={"and then": frozenset({"proceeds"})},
    )

    assert [item.text for item in result.items] == [
        "The invite is created",
        "the reminder is scheduled",
    ]
    assert result.cut_links == [(0, 1, "proceeds")]


def test_cut_without_aliases_produces_no_link():
    result = ex.extract("The invite is created and then the reminder is scheduled")

    assert result.cut_links == []


def test_cut_with_unclassified_endpoint_produces_only_a_flag():
    result = ex.extract(
        "The invite is created and then the user logs in",
        aliases={"and then": frozenset({"proceeds"})},
    )

    assert result.cut_links == []
    assert [(flag.text, flag.reason) for flag in result.flags] == [
        ("the user logs in", "unmatched")
    ]
