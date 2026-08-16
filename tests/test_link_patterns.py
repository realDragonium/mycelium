"""Focused tests for lexical link patterns and their offline evaluator."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from mycelium import store
from mycelium.connect.patterns import (
    COMMON_PATTERNS,
    all_patterns,
    find_cues,
    patterns_for,
)
from mycelium.store.glossary import _STATEMENT_LINK_TYPE_SEED

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_link_patterns.py"


def _load_script():
    """Load the evaluator by path because scripts is not a package."""
    spec = importlib.util.spec_from_file_location("measure_link_patterns", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


measure_link_patterns = _load_script()
Link = measure_link_patterns.Link
Stmt = measure_link_patterns.Stmt


def test_find_cues_captures_rule_formula_targets():
    text = (
        "Match score equals the sum of construct points plus intelligence contribution"
    )

    cues = find_cues(text, "rule")
    by_pattern = {cue.pattern: cue for cue in cues}

    assert by_pattern["composes-formula"].cue == "equals"
    assert by_pattern["composes-formula"].target_text.startswith("the sum of")
    assert "valued-by-equals" in by_pattern


def test_find_cues_obeys_kind_scope_and_unknown_kind_baseline():
    text = "A login attempt is rejected on an unrecognized account"

    event_cues = find_cues(text, "event")

    match = next(cue for cue in event_cues if cue.pattern == "requires-on-condition")
    assert match.target_text == "an unrecognized account"
    assert "requires-on-condition" not in {
        cue.pattern for cue in find_cues(text, "rule")
    }
    assert patterns_for("widget") == COMMON_PATTERNS


def test_find_cues_empty_and_ordered_by_start():
    assert find_cues("A plain relationally neutral sentence", "event") == []

    cues = find_cues("This requires input and then produces output", "event")

    assert [cue.start for cue in cues] == sorted(cue.start for cue in cues)
    assert cues[0].pattern == "requires-verb"
    assert cues[-1].pattern == "triggers-produces"


def test_empty_aliases_preserve_all_templated_pattern_defaults():
    examples = (
        ("The threshold is configured on company", "capability"),
        ("The threshold can be toggled per company", "capability"),
        ("Score difference between base and adjustment", "rule"),
        ("Retry budget limits dispatch attempts", "rule"),
        ("The account is read-only", "state"),
        ("The request is routed through the proxy", "event"),
    )

    for text, kind in examples:
        assert find_cues(text, kind) == find_cues(text, kind, aliases={})


def test_configures_aliases_replace_packaged_cues():
    aliases = {"configures": ("tuned", "configured")}

    tuned = find_cues(
        "The score threshold can be tuned on a job profile",
        "capability",
        aliases=aliases,
    )
    configured = find_cues(
        "The score threshold can be configured on a job profile",
        "capability",
        aliases=aliases,
    )
    toggled = find_cues(
        "The score threshold can be toggled on a job profile",
        "capability",
        aliases=aliases,
    )

    tuned_capability = next(
        cue for cue in tuned if cue.pattern == "configures-capability"
    )
    assert tuned_capability.cue == "can be tuned on"
    assert tuned_capability.target_text == "a job profile"
    assert any(cue.pattern == "configures-capability" for cue in configured)
    assert not any(cue.pattern == "configures-capability" for cue in toggled)


def test_aliases_do_not_affect_non_templated_patterns():
    text = "A login triggers an audit"

    assert find_cues(text, "event", aliases={"triggers": ("kicks off",)}) == find_cues(
        text, "event"
    )


def test_link_type_alias_fires_in_each_templated_frame():
    aliases = {"restricts": ("throttles", "quarantined")}

    limits = find_cues("The importer throttles nightly syncs", "rule", aliases)
    state = find_cues("The account is quarantined", "state", aliases)

    limits_match = next(cue for cue in limits if cue.pattern == "restricts-limits")
    state_match = next(cue for cue in state if cue.pattern == "restricts-state")
    assert limits_match.cue == "throttles"
    assert limits_match.target_text == "nightly syncs"
    assert state_match.cue == "is quarantined"


def test_pattern_registry_has_unique_names_flags_and_seeded_types():
    patterns = all_patterns()

    assert len({pattern.name for pattern in patterns}) == len(patterns)
    assert all(pattern.regex.flags & re.IGNORECASE for pattern in patterns)
    assert {pattern.link_type for pattern in patterns} <= set(_STATEMENT_LINK_TYPE_SEED)


def test_measure_reports_hits_pairs_precision_and_no_ground_truth():
    statements = [
        Stmt("stm_1", "event", "A login triggers a session"),
        Stmt("stm_2", "event", "A session completes"),
        Stmt("stm_3", "rule", "Score equals base points"),
        Stmt("stm_4", "property", "Profile"),
        Stmt("stm_5", "event", "An audit completes"),
    ]
    links = [
        Link("stm_1", "stm_2", "triggers"),
        Link("stm_1", "stm_3", "requires"),
        Link("stm_3", "stm_4", "composes"),
        Link("stm_5", "stm_1", "triggers"),
    ]
    mentions = {
        "stm_1": {"ent_shared"},
        "stm_2": {"ent_shared"},
        "stm_3": {"ent_shared"},
        "stm_4": {"ent_other"},
        "stm_5": {"ent_shared"},
    }

    report = measure_link_patterns.measure(
        statements,
        links,
        mentions,
        ["accepts", "composes", "requires", "triggers"],
    )

    assert report["totals"]["hits"] == 2
    assert report["totals"]["hit_rate"] == 0.5
    assert report["by_link_type"]["triggers"]["pair_fires"] == 3
    assert report["by_link_type"]["triggers"]["true_fires"] == 1
    assert report["by_link_type"]["triggers"]["false_fires"] == 2
    assert report["by_pattern"]["triggers-verb"]["statement_precision"] == 1.0
    assert report["by_link_type"]["accepts"]["links"] == 0
    assert report["by_link_type"]["accepts"]["hit_rate"] is None


def test_load_snapshot_filters_entity_targets_and_keeps_external_statements(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    records = [
        {
            "id": "stm_1",
            "kind": "event",
            "text": "A login triggers a session",
            "mentions": [{"entity_id": "ent_1", "name_id": "nam_1", "name": "login"}],
            "links": [
                {"to_id": "stm_2", "link_type": "triggers", "when": None},
                {"to_id": "ent_1", "link_type": "about", "when": None},
                {"to_id": "stm_missing", "link_type": "requires", "when": {}},
            ],
        },
        {
            "id": "stm_2",
            "kind": "state",
            "text": "A session is active",
            "mentions": [{"entity_id": "ent_1", "name_id": "nam_2", "name": "session"}],
            "links": [],
        },
        {
            "id": "stm_3",
            "kind": "property",
            "text": "Session identifier",
            "mentions": [],
            "links": [],
        },
    ]
    snapshot.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    statements, links, mentions, vocabulary = measure_link_patterns.load_snapshot(
        snapshot
    )

    assert len(statements) == 3
    assert len(links) == 2
    assert {link.to_id for link in links} == {"stm_2", "stm_missing"}
    assert mentions["stm_1"] == {"ent_1"}
    assert vocabulary == ["requires", "triggers"]


def test_render_markdown_never_contains_statement_text():
    report = measure_link_patterns.measure(
        [Stmt("stm_1", "event", "ZZZSENTINEL has no lexical cues")],
        [],
        {},
        ["accepts"],
    )

    markdown = measure_link_patterns.render_markdown(report, source_label="fixture")

    assert "# Link Pattern Hit Rate" in markdown
    assert "ZZZSENTINEL" not in markdown


def test_data_dir_cli_writes_report(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    source_id = store.create_statement(conn, "event", "A login triggers a session")
    target_id = store.create_statement(conn, "event", "A session begins")
    store.insert_links(conn, [(source_id, target_id, "triggers", None)])
    conn.commit()
    conn.close()
    output = tmp_path / "r.md"

    result = measure_link_patterns.main(
        ["--data-dir", str(tmp_path), "--out", str(output)]
    )

    assert result == 0
    assert output.exists()
