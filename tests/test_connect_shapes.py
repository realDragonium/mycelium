"""Focused tests for kind phrasing shapes and their offline evaluator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from mycelium.connect.shapes import (
    EVENT_PARTICIPLES,
    RULE_PARTICIPLES,
    SHAPE_NAMES,
    STATE_PARTICIPLES,
    Classification,
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
    _assert_assigned_shape("The record has unlocked", "state", "state-perfect")
    # An unlisted participle is novel event vocabulary, not a state by default.
    assert classify("The reviewer has approved the request").status == "unmatched"


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
    # "Single X" names a product feature far more often than an absence.
    _assert_assigned_shape(
        "Single sign-on configuration", "property", "property-noun-phrase"
    )


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


def test_command_lemma_bare_noun_phrase_is_unmatched():
    for text in ("Review value", "Delete account"):
        result = classify(text)

        assert result.kind is None
        assert result.status == "unmatched"


def test_ordinary_property_names_remain_property_noun_phrases():
    for text in ("Partner client secret", "Base URL", "Custom query fields"):
        _assert_assigned_shape(text, "property", "property-noun-phrase")


def test_bare_noun_phrase_fragment_is_indistinguishable_from_a_property_name():
    # Deliberate limit: matcher lacks evidence to reject it; segmentation owns it.
    _assert_assigned_shape("Blue widgets", "property", "property-noun-phrase")


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
    # The prefix needs a word boundary, or "How tools work" reads as a heading.
    assert classify("How tools work").status == "unmatched"
    # A heading names one procedure however many verbs its title mentions, so
    # the compound guard does not apply to it.
    assert classify("How to configure automation and test it").kind == "procedure"


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


def test_coordinated_predicates_match_nothing():
    # Every detector reads the root, so the second predicate would be ignored.
    result = classify("An invite is sent and auto result sharing is enabled")

    assert result.status == "unmatched"
    assert result.matches == ()


def test_a_transitive_perfect_is_a_completed_action_not_a_state():
    assert classify("The administrator has enabled result sharing").status == (
        "unmatched"
    )
    assert classify("The invite has expired").kind == "state"


def test_negated_able_to_is_a_prohibition_not_a_capability():
    assert classify("A participant is not able to download the report").kind != (
        "capability"
    )


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


def test_a_marker_inside_the_subject_leaves_the_copula_unconditional():
    _assert_assigned_shape(
        "The reviewer list for a vacancy is empty",
        "state",
        "state-copula-condition",
    )


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


def _summary_results() -> list[tuple[str, str, Classification]]:
    return measure_kind_shapes.classify_rows(_summary_rows())


def test_summarize_counts_rates_confusion_and_floor():
    report = measure_kind_shapes.summarize(_summary_results())

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
    assert report["by_kind"]["event"]["recall"] == 0.5
    assert report["by_kind"]["state"]["unmatched"] == 1
    assert report["by_kind"]["state"]["flag_rate"] == 0.5
    # Precision belongs to the assigned kind: the event row misassigned as
    # property is a false positive for property, not for event.
    assert report["by_assigned_kind"]["event"] == {
        "assigned": 1,
        "correct": 1,
        "wrong": 0,
        "precision": 1.0,
    }
    assert report["by_assigned_kind"]["property"] == {
        "assigned": 1,
        "correct": 0,
        "wrong": 1,
        "precision": 0.0,
    }
    assert report["confusion"]["event"] == {"event": 1, "property": 1}
    assert report["confusion"]["check"]["(ambiguous)"] == 1
    assert report["confusion"]["state"]["(unmatched)"] == 1
    assert report["by_shape"]["event-passive"]["fires"] == 1
    assert report["by_shape"]["event-passive"]["correct"] == 1
    assert "capability" in report["floor"]["kinds_never_assigned"]
    assert "check" in report["floor"]["kinds_never_assigned"]
    assert "property" in report["floor"]["kinds_missed"]
    assert "event" in report["floor"]["kinds_met"]


def test_render_markdown_contains_counts_but_never_statement_text():
    report = measure_kind_shapes.summarize(_summary_results())

    markdown = measure_kind_shapes.render_markdown(report, source_label="fixture")

    assert "# Kind Shape Classification Accuracy" in markdown
    assert "| event | 2 | 1 | 1 | 0 | 0 | 1/2 (50.0%)" in markdown
    assert "| property | 1 | 0 | 1 | 0/1 (0.0%) |" in markdown
    assert "3/4 (75.0%)" in markdown
    assert "never assigned in this snapshot" in markdown
    assert "An invite is sent" not in markdown
    assert "Verify the report" not in markdown


def test_load_snapshot_names_the_line_of_a_record_missing_keys(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(
        '{"kind": "state", "text": "The invite is enabled"}\n{"kind": "state"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing text on line 2"):
        measure_kind_shapes.load_snapshot(snapshot)
