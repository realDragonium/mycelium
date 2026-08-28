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
    KIND_PATTERNS,
    all_patterns,
    find_cues,
    patterns_for,
)
from mycelium.store.glossary import _STATEMENT_LINK_TYPE_SEED
from mycelium.store.link_type_aliases import seed_aliases_by_type, seed_rows

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
    assert by_pattern["composes-formula"].phrase.startswith("the sum of")
    assert "valued-by-equals" in by_pattern


def test_part_of_captures_the_from_slot_and_composed_of_the_to_slot():
    # "X is a part of Y" names the relation from the far side: Y contains X,
    # so the captured phrase fills the edge's `from` slot.
    cues = find_cues("The purge schedule is a part of the retention policy", "state")
    part_of = next(cue for cue in cues if cue.pattern == "contains-part-of")
    assert (part_of.link_type, part_of.phrase_role, part_of.phrase) == (
        "contains",
        "from",
        "the retention policy",
    )

    # "X is composed of Y" keeps the carrier as the container: X contains Y.
    composed = find_cues("The bundle is composed of three modules", "state")
    assert [(cue.pattern, cue.phrase_role) for cue in composed] == [
        ("contains-composed-of", "to")
    ]


def test_belongs_to_captures_the_owner_from_slot():
    examples = (
        ("The purge schedule belongs to the retention policy", "belongs to"),
        ("The archive schedule is owned by the retention policy", "is owned by"),
    )

    for text, expected_cue in examples:
        cues = find_cues(text, "state")
        match = next(cue for cue in cues if cue.pattern == "contains-belongs-to")
        assert (match.cue, match.link_type, match.phrase_role, match.phrase) == (
            expected_cue,
            "contains",
            "from",
            "the retention policy",
        )


def test_find_cues_obeys_kind_scope_and_unknown_kind_baseline():
    text = "A login attempt is rejected on an unrecognized account"

    event_cues = find_cues(text, "event")

    match = next(cue for cue in event_cues if cue.pattern == "requires-on-condition")
    assert match.phrase == "an unrecognized account"
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
    assert tuned_capability.phrase == "a job profile"
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
    assert limits_match.phrase == "nightly syncs"
    assert state_match.cue == "is quarantined"


def test_pattern_registry_has_unique_names_flags_and_seeded_types():
    patterns = all_patterns()

    assert len({pattern.name for pattern in patterns}) == len(patterns)
    assert all(pattern.regex.flags & re.IGNORECASE for pattern in patterns)
    assert {pattern.link_type for pattern in patterns} <= set(_STATEMENT_LINK_TYPE_SEED)


def test_seeded_alias_directions_agree_with_every_frame_geometry():
    aliases = seed_aliases_by_type()
    kinds = (*KIND_PATTERNS, "generic")
    agreements: set[tuple[str, str]] = set()

    for pattern in all_patterns():
        for link_type, alias, direction in seed_rows():
            if link_type != pattern.link_type:
                continue
            text = f"X {alias} Y"
            for kind in kinds:
                for cue in find_cues(text, kind, aliases):
                    if (
                        cue.pattern != pattern.name
                        or cue.cue.casefold() != alias.casefold()
                    ):
                        continue
                    assert (pattern.phrase_role == "from") == (direction == "reverse")
                    agreements.add((pattern.name, alias))

    assert {
        ("contains-part-of", "is part of"),
        ("requires-required", "is required for"),
        ("cases-one-of", "is one of"),
        ("contains-belongs-to", "belongs to"),
        ("contains-belongs-to", "is owned by"),
    } <= agreements
    # A frame whose phrasing never equals a seeded alias has no seeded direction
    # to agree with, so the sweep binds exactly the frames pinned here.
    assert {name for name, _alias in agreements} == frozenset(
        {
            "requires-verb",
            "requires-required",
            "requires-needs",
            "requires-must-have",
            "accepts-verb",
            "accepts-optional",
            "accepts-may-provide",
            "configures-verb",
            "restricts-verb",
            "restricts-limits",
            "enables-verb",
            "enables-allows",
            "triggers-verb",
            "triggers-causes",
            "establishes-verb",
            "establishes-becomes",
            "contains-verb",
            "contains-composed-of",
            "contains-consists-of",
            "contains-part-of",
            "contains-belongs-to",
            "proceeds-verb",
            "proceeds-followed-by",
            "replaces-verb",
            "replaces-instead-of",
            "supersedes-verb",
            "governed-by-phrase",
            "varies-by-verb",
            "varies-by-depends",
            "fallback-to-verb",
            "proceeds-then",
            "valued-by-state",
            "governed-by-capability",
            "composes-formula",
            "valued-by-derived",
            "valued-by-determined",
            "cases-one-of",
            "fallback-to-defaults",
            "teaches-how-to",
            "resolves-fix",
            "confirms-if",
            "violates-missing",
        }
    )


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
        aliases={},
    )

    assert report["totals"]["hits"] == 2
    assert report["totals"]["hit_rate"] == 0.5
    assert report["by_link_type"]["triggers"]["pair_fires"] == 3
    assert report["by_link_type"]["triggers"]["true_fires"] == 1
    assert report["by_link_type"]["triggers"]["false_fires"] == 2
    assert report["by_pattern"]["triggers-verb"]["statement_precision"] == 1.0
    assert report["by_link_type"]["accepts"]["links"] == 0
    assert report["by_link_type"]["accepts"]["hit_rate"] is None


def test_measure_scores_inverted_cue_evidence_on_the_incoming_edge():
    statements = [
        Stmt("stm_child", "state", "The schedule is a part of the retention policy"),
        Stmt("stm_parent", "rule", "The retention policy applies"),
    ]
    links = [Link("stm_parent", "stm_child", "contains")]
    mentions = {"stm_child": {"ent_policy"}, "stm_parent": {"ent_policy"}}

    report = measure_link_patterns.measure(
        statements, links, mentions, ["contains"], aliases={}
    )

    # The only cue sits on the child, but the edge it evidences is incoming.
    assert report["totals"]["hits"] == 1
    assert report["by_link_type"]["contains"]["true_fires"] == 1
    assert report["by_link_type"]["contains"]["false_fires"] == 0
    row = report["by_pattern"]["contains-part-of"]
    assert row["statements_with_type_link"] == 1
    assert row["statement_precision"] == 1.0
    assert row["link_hits"] == 1


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

    statements, links, mentions, vocabulary, aliases = (
        measure_link_patterns.load_snapshot(snapshot)
    )

    assert len(statements) == 3
    assert len(links) == 2
    assert {link.to_id for link in links} == {"stm_2", "stm_missing"}
    assert mentions["stm_1"] == {"ent_1"}
    assert vocabulary == ["requires", "triggers"]
    assert aliases == store.seed_aliases_by_type()


def test_render_markdown_never_contains_statement_text():
    report = measure_link_patterns.measure(
        [Stmt("stm_1", "event", "ZZZSENTINEL has no lexical cues")],
        [],
        {},
        ["accepts"],
        aliases={},
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


def test_snapshot_cli_uses_supplied_aliases(tmp_path: Path):
    snapshot = tmp_path / "snapshot.jsonl"
    records = [
        {
            "id": "stm_1",
            "kind": "rule",
            "text": "The importer throttles nightly syncs",
            "mentions": [],
            "links": [{"to_id": "stm_2", "link_type": "restricts", "when": None}],
        },
        {
            "id": "stm_2",
            "kind": "event",
            "text": "Nightly syncs run",
            "mentions": [],
            "links": [],
        },
    ]
    snapshot.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps({"restricts": ["limit", "throttles"]}), encoding="utf-8"
    )
    output = tmp_path / "report.md"

    result = measure_link_patterns.main(
        [
            "--snapshot",
            str(snapshot),
            "--aliases",
            str(aliases),
            "--out",
            str(output),
        ]
    )

    assert result == 0
    assert "| restricts | 1/1 (100.0%) |" in output.read_text(encoding="utf-8")


def test_aliases_with_data_dir_is_rejected(tmp_path: Path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    conn.close()
    aliases = tmp_path / "aliases.json"
    aliases.write_text("{}", encoding="utf-8")
    output = tmp_path / "report.md"

    result = measure_link_patterns.main(
        [
            "--data-dir",
            str(tmp_path),
            "--aliases",
            str(aliases),
            "--out",
            str(output),
        ]
    )

    assert result == 1
    assert not output.exists()
