"""Test raw-text extraction and injected resolution of unknown connectives.

The cue tests bypass embeddings so they isolate which segmented cuts reach the gate.
"""

from __future__ import annotations

from mycelium.connect import extract as ex
from mycelium.connect.cue_gate import CueResolution
from mycelium.connect.negation import negated_connective
from mycelium.connect.segment import Cut, Fragment, Segmentation

TEXT = """When the invite is sent, a reminder is scheduled. Notification cadence can be configured on Company.

- Click Save to apply the change.
- The user logs in and receives a token.
- Blue widgets."""


def _cue_segmentation(cue: str) -> Segmentation:
    cue_end = 22 + len(cue)
    return Segmentation(
        fragments=[
            Fragment(0, "The invite is created", "claim", (0, 21), 0, False, False),
            Fragment(
                1,
                "the reminder is scheduled",
                "claim",
                (cue_end + 1, cue_end + 26),
                0,
                False,
                False,
            ),
        ],
        cuts=[Cut("compound-phrase", cue, (22, cue_end), 0, 1)],
        proposals=[],
    )


def test_negated_cue_is_flagged_without_calling_resolver():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    links, flags, resolutions = ex._gate_cuts(
        _cue_segmentation("but never"),
        aliases={},
        item_position={0: 0, 1: 1},
        condition_links=[],
        resolve=reject,
    )

    assert links == []
    assert resolutions == [CueResolution("but never", "negated", None, None, None, ())]
    assert len(flags) == 1
    assert flags[0].reason == "cue"
    assert "the words deny the relation" in flags[0].detail
    assert flags[0].provenance == {
        "cue": "but never",
        "decision": "negated",
        "candidates": [],
    }


def test_standalone_no_cue_is_flagged_without_calling_resolver():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    links, flags, resolutions = ex._gate_cuts(
        _cue_segmentation("but no"),
        aliases={},
        item_position={0: 0, 1: 1},
        condition_links=[],
        resolve=reject,
    )

    assert links == []
    assert resolutions == [CueResolution("but no", "negated", None, None, None, ())]
    assert len(flags) == 1
    assert flags[0].reason == "cue"
    assert "the words deny the relation" in flags[0].detail
    assert flags[0].provenance == {
        "cue": "but no",
        "decision": "negated",
        "candidates": [],
    }


def test_connective_quantifier_is_not_negated_but_no_longer_is():
    assert negated_connective("no more than") is None
    assert negated_connective("no fewer than") is None
    assert negated_connective("no longer")


def test_negation_substring_cue_reaches_resolver():
    calls: list[str] = []

    def resolve(cue: str) -> CueResolution:
        calls.append(cue)
        return CueResolution(cue, "unresolved", None, None, None, ())

    ex._gate_cuts(
        _cue_segmentation("nevertheless"),
        aliases={},
        item_position={0: 0, 1: 1},
        condition_links=[],
        resolve=resolve,
    )

    assert calls == ["nevertheless"]


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
    assert result.condition_links == [(1, 0, "requires")]


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


def test_hidden_transition_is_rejected_before_classification():
    result = ex.extract("The status becomes active")

    assert result.items == []
    assert len(result.flags) == 1
    assert result.flags[0].reason == "rejected"
    assert "hidden_event_state" in result.flags[0].detail


def test_hidden_event_and_state_is_not_accepted_as_a_state_item():
    result = ex.extract("The flag is set to true")

    assert result.items == []
    assert len(result.flags) == 1
    assert result.flags[0].reason == "rejected"
    assert "hidden_event_state" in result.flags[0].detail


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
        "rejected",
        "phrasing",
        "flip",
        "depends_on_rejected",
    } <= ex.FLAG_SOURCES.keys()


def test_resolved_cut_produces_left_to_right_item_link():
    result = ex.extract(
        "The invite is created and then the reminder is scheduled",
        aliases={"and then": frozenset({("proceeds", "forward")})},
    )

    assert [item.text for item in result.items] == [
        "The invite is created",
        "the reminder is scheduled",
    ]
    assert result.cut_links == [(0, 1, "proceeds")]


def test_cut_alias_direction_orients_the_link_both_ways():
    text = "The invite is created and then the reminder is scheduled"

    forward = ex.extract(
        text, aliases={"and then": frozenset({("proceeds", "forward")})}
    )
    assert forward.cut_links == [(0, 1, "proceeds")]

    # A far-side alias on the same cut reads the edge the other way round.
    reverse = ex.extract(
        text, aliases={"and then": frozenset({("proceeds", "reverse")})}
    )
    assert reverse.cut_links == [(1, 0, "proceeds")]


def test_cut_without_aliases_produces_no_link():
    result = ex.extract("The invite is created and then the reminder is scheduled")

    assert result.cut_links == []


def test_cut_with_unclassified_endpoint_produces_only_a_flag():
    result = ex.extract(
        "The invite is created and then the user logs in",
        aliases={"and then": frozenset({("proceeds", "forward")})},
    )

    assert result.cut_links == []
    assert [(flag.text, flag.reason) for flag in result.flags] == [
        ("the user logs in", "unmatched")
    ]


def _resolution(
    decision: str,
    *,
    link_type: str | None = "proceeds",
    alias: str | None = "then",
    score: float | None = 0.91,
    candidates: tuple[tuple[str, str, float], ...] = (),
) -> CueResolution:
    """Build a resolution for the shared unknown compound cue."""
    return CueResolution(
        cue="and also",
        decision=decision,
        link_type=link_type,
        alias=alias,
        score=score,
        candidates=candidates,
    )


def test_auto_decision_types_cut_and_reports_resolution():
    resolution = _resolution("auto")

    result = ex.extract(
        "The invite is created and also the reminder is scheduled",
        aliases={},
        resolve_cue=lambda cue: resolution,
    )

    assert [item.text for item in result.items] == [
        "The invite is created",
        "the reminder is scheduled",
    ]
    assert result.cut_links == [(0, 1, "proceeds")]
    assert not any(flag.reason == "cue" for flag in result.flags)
    assert result.cue_resolutions == [resolution]


def test_low_confidence_decision_also_types_cut():
    resolution = _resolution("auto:low-confidence", score=0.86)

    result = ex.extract(
        "The invite is created and also the reminder is scheduled",
        aliases={},
        resolve_cue=lambda cue: resolution,
    )

    assert result.cut_links == [(0, 1, "proceeds")]
    assert result.cue_resolutions == [resolution]


def test_unresolved_cue_flags_connective_with_near_misses():
    source = "The invite is created and also the reminder is scheduled"
    candidates = (
        ("proceeds", "then", 0.61),
        ("contains", "includes", 0.58),
    )
    resolution = _resolution(
        "unresolved",
        link_type=None,
        alias=None,
        score=None,
        candidates=candidates,
    )

    result = ex.extract(
        source,
        aliases={},
        resolve_cue=lambda cue: resolution,
    )

    assert result.cut_links == []
    cue_flags = [flag for flag in result.flags if flag.reason == "cue"]
    assert len(cue_flags) == 1
    flag = cue_flags[0]
    assert "and also" in flag.detail
    assert "proceeds" in flag.detail
    assert "contains" in flag.detail
    assert flag.provenance == {
        "cue": "and also",
        "decision": "unresolved",
        "candidates": [list(candidate) for candidate in candidates],
    }
    start = source.index("and also")
    assert flag.span == (start, start + len("and also"))


def test_strict_decision_flags_connective_without_link():
    resolution = _resolution(
        "strict",
        link_type=None,
        alias=None,
        score=None,
    )

    result = ex.extract(
        "The invite is created and also the reminder is scheduled",
        aliases={},
        resolve_cue=lambda cue: resolution,
    )

    assert result.cut_links == []
    cue_flags = [flag for flag in result.flags if flag.reason == "cue"]
    assert len(cue_flags) == 1
    assert "and also" in cue_flags[0].detail


def test_coordination_and_is_never_a_cue_candidate():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    result = ex.extract(
        "The user logs in and receives a token",
        aliases={},
        resolve_cue=reject,
    )

    assert result.cue_resolutions == []
    assert not any(flag.reason == "cue" for flag in result.flags)


def test_conditional_opener_is_never_retyped():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    result = ex.extract(
        "When the invite is sent, a reminder is scheduled",
        aliases={},
        resolve_cue=reject,
    )

    assert result.condition_links == [(1, 0, "requires")]
    assert result.cue_resolutions == []


def test_semicolon_carries_no_cue():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    result = ex.extract(
        "The invite is created; the reminder is scheduled",
        aliases={},
        resolve_cue=reject,
    )

    assert result.cue_resolutions == []
    assert not any(flag.reason == "cue" for flag in result.flags)


def test_none_resolver_preserves_old_extraction_behavior():
    implicit = ex.extract(TEXT)
    explicit = ex.extract(TEXT, resolve_cue=None)

    assert explicit.items == implicit.items
    assert explicit.flags == implicit.flags
    assert explicit.condition_links == implicit.condition_links
    assert explicit.cut_links == implicit.cut_links
    assert explicit.cue_resolutions == []


def test_each_distinct_cue_is_resolved_once():
    calls: list[str] = []
    resolution = _resolution("auto")

    def resolve(cue: str) -> CueResolution:
        calls.append(cue)
        return resolution

    result = ex.extract(
        "The invite is created and also the reminder is scheduled. "
        "The token is created and also the report is generated.",
        aliases={},
        resolve_cue=resolve,
    )

    assert calls == ["and also"]
    assert len(result.cut_links) == 2
    assert result.cue_resolutions == [resolution]


def test_registered_ambiguous_cue_is_not_guessed():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    result = ex.extract(
        "The invite is created and also the reminder is scheduled",
        aliases={"and also": frozenset({("proceeds", "forward"), ("next", "forward")})},
        resolve_cue=reject,
    )

    assert result.cut_links == []
    assert result.cue_resolutions == []


def test_cue_on_an_unclassified_endpoint_is_never_a_candidate():
    def reject(cue: str) -> CueResolution:
        raise AssertionError(f"unexpected cue: {cue!r}")

    result = ex.extract(
        "The invite is created and also archived",
        aliases={},
        resolve_cue=reject,
    )

    assert [item.text for item in result.items] == ["The invite is created"]
    assert [flag.reason for flag in result.flags] == ["unmatched"]
    assert result.cue_resolutions == []
