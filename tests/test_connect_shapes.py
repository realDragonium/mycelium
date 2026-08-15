"""Focused tests for kind phrasing shapes and their offline evaluator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from mycelium.connect.shapes import (
    EVENT_PARTICIPLES,
    RULE_PARTICIPLES,
    SHAPE_NAMES,
    STATE_PARTICIPLES,
    classify,
    match_shapes,
)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_kind_shapes.py"


def _load_script():
    """Load the evaluator by path because scripts is not a package."""
    spec = importlib.util.spec_from_file_location("measure_kind_shapes", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


measure_kind_shapes = _load_script()


def _assert_assigned_shape(text: str, kind: str, shape: str) -> None:
    matches = match_shapes(text)
    result = classify(text)

    assert shape in {match.shape for match in matches}
    assert result.status == "assigned"
    assert result.kind == kind


def test_capability_modal_shape():
    _assert_assigned_shape(
        "A job profile can be renamed", "capability", "capability-modal"
    )


def test_event_passive_shape():
    _assert_assigned_shape(
        "An invite is sent to the participant", "event", "event-passive"
    )


def test_event_active_shape():
    _assert_assigned_shape("The request arrives", "event", "event-active")


def test_state_passive_shape():
    _assert_assigned_shape("Auto result sharing is enabled", "state", "state-passive")


def test_state_perfect_shape():
    _assert_assigned_shape("The invite has expired", "state", "state-perfect")


def test_state_copula_condition_shape():
    _assert_assigned_shape(
        "The report PDF download is in progress",
        "state",
        "state-copula-condition",
    )


def test_state_possession_shape():
    _assert_assigned_shape("The invite has a phone number", "state", "state-possession")


def test_state_stative_verb_shape():
    _assert_assigned_shape("The invite contains a link", "state", "state-stative-verb")


def test_state_negated_np_shape():
    _assert_assigned_shape("No name on the invite", "state", "state-negated-np")


def test_rule_passive_shape():
    _assert_assigned_shape(
        "Assessment language is determined by invite locale",
        "rule",
        "rule-passive",
    )


def test_rule_formula_shapes():
    _assert_assigned_shape(
        "Match score equals the sum of construct points", "rule", "rule-formula"
    )
    _assert_assigned_shape(
        "Intelligence baseline defaults to percentile 40", "rule", "rule-formula"
    )


def test_rule_band_shape():
    _assert_assigned_shape(
        "Competency match level is High for participant scores below the benchmark",
        "rule",
        "rule-band",
    )


def test_rule_measure_shape():
    _assert_assigned_shape("The retry delay is 6 days", "rule", "rule-measure")


def test_property_noun_phrase_shape():
    _assert_assigned_shape("Vacancy ID", "property", "property-noun-phrase")


def test_action_imperative_shape():
    _assert_assigned_shape("Click the Save button", "action", "action-imperative")


def test_check_imperative_shape():
    _assert_assigned_shape("Verify the provider matches", "check", "check-imperative")


def test_procedure_how_to_shape():
    _assert_assigned_shape(
        "How to configure automation for a vacancy",
        "procedure",
        "procedure-how-to",
    )


def test_passive_participle_lexicons_control_event_state_collision():
    # This shared passive surface is the collision the allow-lists control.
    event = classify("An invite is sent to the participant")
    state = classify("Auto result sharing is enabled")

    assert event.status == "assigned"
    assert event.kind == "event"
    assert state.status == "assigned"
    assert state.kind == "state"


def test_modal_passive_is_capability_not_event():
    matches = match_shapes("A job profile can be renamed")

    assert "capability-modal" in {match.shape for match in matches}
    assert "event-passive" not in {match.shape for match in matches}


def test_distinct_kind_matches_are_ambiguous():
    # The initial command and embedded modal deliberately match check and capability.
    result = classify("Verify the report can be downloaded")

    assert {match.kind for match in result.matches} == {"check", "capability"}
    assert result.status == "ambiguous"
    assert result.kind is None


def test_unknown_compound_and_empty_text_are_unmatched():
    compound = classify("The invite is stored and the report is shown")

    assert compound.status == "unmatched"
    assert compound.kind is None
    assert compound.matches == ()
    for text in ("", "   "):
        result = classify(text)
        assert result.status == "unmatched"
        assert result.kind is None
        assert result.matches == ()


def test_negated_modal_is_a_prohibition_not_a_capability():
    # "cannot" parses as an ordinary capability modal; a prohibition is
    # rule-shaped, so the shape withholds rather than assign a capability.
    text = "An assessment cannot be retaken once submitted"

    assert "capability-modal" not in {match.shape for match in match_shapes(text)}
    assert classify(text).kind != "capability"


def test_semicolon_marks_a_compound_remnant_and_matches_nothing():
    result = classify("The invite is sent; the report is enabled")

    assert result.status == "unmatched"
    assert result.matches == ()


def test_band_marker_keeps_a_conditional_copula_out_of_state():
    shapes = {
        match.shape
        for match in match_shapes(
            "The section is available when a recording type is set"
        )
    }

    assert "state-copula-condition" not in shapes


def test_passive_participle_lexicons_are_pairwise_disjoint():
    assert STATE_PARTICIPLES.isdisjoint(EVENT_PARTICIPLES)
    assert STATE_PARTICIPLES.isdisjoint(RULE_PARTICIPLES)
    assert EVENT_PARTICIPLES.isdisjoint(RULE_PARTICIPLES)


def test_shape_names_cover_every_detector_without_duplicates():
    expected = {
        "capability-modal",
        "event-passive",
        "event-active",
        "state-passive",
        "state-perfect",
        "state-copula-condition",
        "state-possession",
        "state-stative-verb",
        "state-negated-np",
        "rule-passive",
        "rule-formula",
        "rule-band",
        "rule-measure",
        "property-noun-phrase",
        "action-imperative",
        "check-imperative",
        "procedure-how-to",
    }

    assert set(SHAPE_NAMES) == expected
    assert len(SHAPE_NAMES) == len(set(SHAPE_NAMES))


def _summary_rows() -> list[tuple[str, str]]:
    return [
        ("event", "An invite is sent to the participant"),
        ("state", "Auto result sharing is enabled"),
        ("event", "Vacancy ID"),
        ("check", "Verify the report can be downloaded"),
        ("state", "The invite is stored and the report is shown"),
        ("rule", "Match score equals the sum of construct points"),
    ]


def test_summarize_counts_rates_confusion_and_floor():
    report = measure_kind_shapes.summarize(_summary_rows())

    assert report["totals"] == {
        "statements": 6,
        "assigned": 4,
        "correct": 3,
        "wrong": 1,
        "ambiguous": 1,
        "unmatched": 1,
        "precision": 0.75,
        "recall": 0.5,
        "flag_rate": 1 / 3,
    }
    assert report["by_kind"]["event"]["n"] == 2
    assert report["by_kind"]["event"]["correct"] == 1
    assert report["by_kind"]["event"]["wrong"] == 1
    assert report["by_kind"]["event"]["precision"] == 0.5
    assert report["by_kind"]["event"]["recall"] == 0.5
    assert report["by_kind"]["state"]["unmatched"] == 1
    assert report["by_kind"]["state"]["flag_rate"] == 0.5
    assert report["confusion"]["event"] == {"event": 1, "property": 1}
    assert report["confusion"]["check"]["(ambiguous)"] == 1
    assert report["confusion"]["state"]["(unmatched)"] == 1
    assert report["by_shape"]["event-passive"]["fires"] == 1
    assert report["by_shape"]["event-passive"]["correct"] == 1
    assert "capability" in report["floor"]["kinds_without_ground_truth"]
    assert "check" in report["floor"]["kinds_without_ground_truth"]
    assert "event" in report["floor"]["kinds_missed"]


def test_render_markdown_contains_counts_but_never_statement_text():
    rows = _summary_rows()
    report = measure_kind_shapes.summarize(rows)

    markdown = measure_kind_shapes.render_markdown(report, source_label="fixture")

    assert "# Kind Shape Classification Accuracy" in markdown
    assert "| event | 2 | 1 | 1 | 0 | 0 | 1/2 (50.0%)" in markdown
    assert "3/4 (75.0%)" in markdown
    assert "no ground truth in this snapshot" in markdown
    assert "An invite is sent" not in markdown
    assert "Verify the report" not in markdown
