"""Measure lexical link-pattern hit and false-fire rates without storing text.

A hit means an existing link (S -> T, type L) has a cue of type L in the
source statement. A pair fire is a unique (S, C, L) proposed by a cue where S
and another statement C share an entity mention; it is true when that exact
link exists and false otherwise. Statement-level precision for a pattern is
the fraction of statements it matches that have any outgoing link of its type.
Statements without mentions produce no pairs. Vocabulary types with no links
have no ground truth rather than a zero-percent hit rate.

Usage:
    uv run python scripts/measure_link_patterns.py --data-dir PATH
        [--out PATH] [--label TEXT] [--show-cues N]
    uv run python scripts/measure_link_patterns.py --snapshot FILE.jsonl
        [--out PATH] [--label TEXT] [--show-cues N]

The Markdown report contains counts only. `--show-cues` may print matched cue
text to stdout, but statement text is never included in the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mycelium import store
from mycelium.connect.patterns import all_patterns, find_cues


@dataclass(frozen=True)
class Stmt:
    """Represent the statement fields needed by the evaluator."""

    id: str
    kind: str
    text: str


@dataclass(frozen=True)
class Link:
    """Represent one materialized statement-to-statement link."""

    from_id: str
    to_id: str
    link_type: str


def _rate(numerator: int, denominator: int) -> float | None:
    """Return a fraction, leaving empty denominators without a rate."""
    return numerator / denominator if denominator else None


def _entity_candidates(
    statements: list[Stmt], mentions: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Build alias-aware candidate statement sets from shared entities."""
    known_ids = {statement.id for statement in statements}
    by_entity: dict[str, set[str]] = defaultdict(set)
    for statement_id, entity_ids in mentions.items():
        if statement_id in known_ids:
            for entity_id in entity_ids:
                by_entity[entity_id].add(statement_id)

    candidates: dict[str, set[str]] = {}
    for statement in statements:
        shared = set()
        for entity_id in mentions.get(statement.id, set()):
            shared.update(by_entity.get(entity_id, set()))
        shared.discard(statement.id)
        candidates[statement.id] = shared
    return candidates


def _link_row() -> dict[str, int | float | None]:
    """Create an empty aggregate row for one link type."""
    return {
        "links": 0,
        "hits": 0,
        "hit_rate": None,
        "pair_fires": 0,
        "true_fires": 0,
        "false_fires": 0,
        "false_fire_rate": None,
    }


def measure(
    statements: list[Stmt],
    links: list[Link],
    mentions: dict[str, set[str]],
    vocabulary: list[str],
    aliases: Mapping[str, Sequence[str]],
) -> dict:
    """Return link-pattern measurements as plain report data."""
    vocabulary_set = set(vocabulary)
    vocabulary_types = sorted(vocabulary_set)
    statement_by_id = {statement.id: statement for statement in statements}
    cues_by_statement = {
        statement.id: find_cues(statement.text, statement.kind, aliases)
        for statement in statements
    }
    # A from-capturing cue evidences an incoming edge, so hits split by the
    # phrase role: a link counts when its source carries a to-role cue of its
    # type, or its target carries a from-role one.
    outgoing_cue_types = {
        statement_id: {cue.link_type for cue in cues if cue.phrase_role == "to"}
        for statement_id, cues in cues_by_statement.items()
    }
    incoming_cue_types = {
        statement_id: {cue.link_type for cue in cues if cue.phrase_role == "from"}
        for statement_id, cues in cues_by_statement.items()
    }
    cue_patterns = {
        statement_id: {cue.pattern for cue in cues}
        for statement_id, cues in cues_by_statement.items()
    }

    def cued(link: Link) -> bool:
        return link.link_type in outgoing_cue_types.get(
            link.from_id, set()
        ) or link.link_type in incoming_cue_types.get(link.to_id, set())

    eligible_links = [link for link in links if link.link_type in vocabulary_set]
    link_hits = [link for link in eligible_links if cued(link)]
    actual_link_triples = {(link.from_id, link.to_id, link.link_type) for link in links}
    outgoing_types: dict[str, set[str]] = defaultdict(set)
    incoming_types: dict[str, set[str]] = defaultdict(set)
    for link in links:
        outgoing_types[link.from_id].add(link.link_type)
        incoming_types[link.to_id].add(link.link_type)

    by_link_type = {link_type: _link_row() for link_type in vocabulary_types}
    for link in eligible_links:
        by_link_type[link.link_type]["links"] += 1
    for link in link_hits:
        by_link_type[link.link_type]["hits"] += 1

    candidates = _entity_candidates(statements, mentions)
    pair_fires_by_type: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    pair_fires_by_pattern: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for statement in statements:
        for candidate_id in candidates[statement.id]:
            for link_type in outgoing_cue_types[statement.id] & vocabulary_set:
                pair_fires_by_type[link_type].add(
                    (statement.id, candidate_id, link_type)
                )
            # A from-role cue fires the pair the other way round: the edge it
            # evidences would run candidate -> carrier.
            for link_type in incoming_cue_types[statement.id] & vocabulary_set:
                pair_fires_by_type[link_type].add(
                    (candidate_id, statement.id, link_type)
                )
            for pattern_name in cue_patterns[statement.id]:
                pair_fires_by_pattern[pattern_name].add(
                    (statement.id, candidate_id, pattern_name)
                )

    for link_type, row in by_link_type.items():
        fires = pair_fires_by_type[link_type]
        true_fires = sum(
            (from_id, to_id, link_type) in actual_link_triples
            for from_id, to_id, _ in fires
        )
        row["hit_rate"] = _rate(int(row["hits"]), int(row["links"]))
        row["pair_fires"] = len(fires)
        row["true_fires"] = true_fires
        row["false_fires"] = len(fires) - true_fires
        row["false_fire_rate"] = _rate(int(row["false_fires"]), len(fires))

    kinds = sorted({statement.kind for statement in statements})
    by_kind: dict[str, dict[str, int | float | None]] = {
        kind: {"links": 0, "hits": 0, "hit_rate": None} for kind in kinds
    }
    by_kind_and_type: dict[str, dict[str, dict[str, int | float | None]]] = {}
    for link in eligible_links:
        statement = statement_by_id.get(link.from_id)
        if statement is None:
            continue
        row = by_kind[statement.kind]
        row["links"] += 1
        if cued(link):
            row["hits"] += 1
        kind_types = by_kind_and_type.setdefault(statement.kind, {})
        type_row = kind_types.setdefault(
            link.link_type, {"links": 0, "hits": 0, "hit_rate": None}
        )
        type_row["links"] += 1
        if cued(link):
            type_row["hits"] += 1
    for row in by_kind.values():
        row["hit_rate"] = _rate(int(row["hits"]), int(row["links"]))
    for kind_types in by_kind_and_type.values():
        for row in kind_types.values():
            row["hit_rate"] = _rate(int(row["hits"]), int(row["links"]))

    by_pattern: dict[str, dict[str, str | int | float | None]] = {}
    for pattern in all_patterns():
        if pattern.link_type not in vocabulary_set:
            continue
        fired_statements = {
            statement_id
            for statement_id, pattern_names in cue_patterns.items()
            if pattern.name in pattern_names
        }
        # A from-capturing pattern's ground truth is the incoming edge: the
        # cue carrier sits on the receiving end of the link it evidences.
        inverted = pattern.phrase_role == "from"
        types_of = incoming_types if inverted else outgoing_types
        statements_with_link = sum(
            pattern.link_type in types_of[statement_id]
            for statement_id in fired_statements
        )
        pattern_link_hits = sum(
            link.link_type == pattern.link_type
            and pattern.name
            in cue_patterns.get(link.to_id if inverted else link.from_id, set())
            for link in eligible_links
        )
        fires = pair_fires_by_pattern[pattern.name]
        true_fires = sum(
            (
                (candidate_id, carrier_id, pattern.link_type)
                if inverted
                else (carrier_id, candidate_id, pattern.link_type)
            )
            in actual_link_triples
            for carrier_id, candidate_id, _ in fires
        )
        false_fires = len(fires) - true_fires
        by_pattern[pattern.name] = {
            "link_type": pattern.link_type,
            "statements_fired": len(fired_statements),
            "statements_with_type_link": statements_with_link,
            "statement_precision": _rate(statements_with_link, len(fired_statements)),
            "link_hits": pattern_link_hits,
            "pair_fires": len(fires),
            "false_fires": false_fires,
            "false_fire_rate": _rate(false_fires, len(fires)),
        }

    return {
        "totals": {
            "statements": len(statements),
            "links": len(links),
            "links_in_vocabulary": len(eligible_links),
            "hits": len(link_hits),
            "hit_rate": _rate(len(link_hits), len(eligible_links)),
        },
        "by_link_type": by_link_type,
        "by_kind": by_kind,
        "by_kind_and_type": by_kind_and_type,
        "by_pattern": by_pattern,
        "patterns_outside_vocabulary": sorted(
            pattern.name
            for pattern in all_patterns()
            if pattern.link_type not in vocabulary_set
        ),
        "links_outside_vocabulary": len(links) - len(eligible_links),
    }


def _fraction(
    numerator: int, denominator: int, *, no_ground_truth: bool = False
) -> str:
    """Format a count fraction for a report table."""
    if not denominator:
        return "no ground truth (0 links)" if no_ground_truth else "0/0 (n/a)"
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})"


def _pair_fraction(row: dict[str, Any]) -> str:
    """Format false pair fires over all pair fires."""
    return _fraction(int(row["false_fires"]), int(row["pair_fires"]))


def render_markdown(report: dict, *, source_label: str) -> str:
    """Render a count-only Markdown report."""
    totals = report["totals"]
    lines = [
        "# Link Pattern Hit Rate",
        "",
        (
            f"**Source:** {source_label} — {totals['statements']} statements, "
            f"{totals['links']} links"
        ),
        "",
        "## Totals",
        "",
        "| Statements | Links | Links in vocabulary | Hits | Links outside vocabulary |",
        "| ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {totals['statements']} | {totals['links']} | "
            f"{totals['links_in_vocabulary']} | "
            f"{_fraction(totals['hits'], totals['links_in_vocabulary'])} | "
            f"{report['links_outside_vocabulary']} |"
        ),
        "",
        "## By link type",
        "",
        "| Link type | Link hits | Pair fires | False fires |",
        "| --- | ---: | ---: | ---: |",
    ]
    type_rows = sorted(
        report["by_link_type"].items(), key=lambda item: (-item[1]["links"], item[0])
    )
    for link_type, row in type_rows:
        hit_fraction = _fraction(
            row["hits"], row["links"], no_ground_truth=row["links"] == 0
        )
        lines.append(
            f"| {link_type} | {hit_fraction} | {row['pair_fires']} | "
            f"{_pair_fraction(row)} |"
        )

    lines.extend(
        [
            "",
            "## By kind",
            "",
            "| Kind | Link hits |",
            "| --- | ---: |",
        ]
    )
    for kind, row in sorted(report["by_kind"].items()):
        lines.append(f"| {kind} | {_fraction(row['hits'], row['links'])} |")

    lines.extend(
        [
            "",
            "## By kind × link type",
            "",
            "| Kind | Link type | Link hits |",
            "| --- | --- | ---: |",
        ]
    )
    for kind, type_data in sorted(report["by_kind_and_type"].items()):
        for link_type, row in sorted(type_data.items()):
            lines.append(
                f"| {kind} | {link_type} | {_fraction(row['hits'], row['links'])} |"
            )

    lines.extend(
        [
            "",
            "## By pattern",
            "",
            (
                "| Pattern | Link type | Statement precision | Link hits | "
                "Pair fires | False fires |"
            ),
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )

    def pattern_sort(item: tuple[str, dict[str, Any]]) -> tuple[str, float, str]:
        name, row = item
        precision = row["statement_precision"]
        return row["link_type"], -(precision if precision is not None else -1.0), name

    for pattern_name, row in sorted(report["by_pattern"].items(), key=pattern_sort):
        lines.append(
            f"| {pattern_name} | {row['link_type']} | "
            f"{_fraction(row['statements_with_type_link'], row['statements_fired'])} | "
            f"{row['link_hits']} | {row['pair_fires']} | {_pair_fraction(row)} |"
        )

    lines.extend(["", "## Patterns outside vocabulary", ""])
    outside = report["patterns_outside_vocabulary"]
    if outside:
        lines.extend(f"- `{pattern_name}`" for pattern_name in outside)
    else:
        lines.append("None.")

    lines.extend(
        [
            "",
            "## How to read",
            "",
            (
                "A **hit** is an existing link whose type is proposed by a cue in "
                "its source statement. The target does not affect hit detection."
            ),
            "",
            (
                "A **pair fire** is a unique source, candidate, and link-type triple "
                "where the source has that cue and both statements mention at least "
                "one shared entity. It is true when the exact directed link exists "
                "and false otherwise. Statements without mentions produce no pairs."
            ),
            "",
            (
                "**Statement precision** is the fraction of statements matched by a "
                "pattern that have at least one outgoing link of that pattern's type, "
                "regardless of target. Vocabulary types with zero links have no ground "
                "truth rather than a zero-percent hit rate."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def load_snapshot(
    path: Path,
) -> tuple[
    list[Stmt],
    list[Link],
    dict[str, set[str]],
    list[str],
    dict[str, tuple[str, ...]],
]:
    """Load the evaluator's plain data from a get_statements JSONL export."""
    statements: list[Stmt] = []
    links: list[Link] = []
    mentions: dict[str, set[str]] = {}
    with path.open(encoding="utf-8") as snapshot:
        for line_number, line in enumerate(snapshot, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error}")
            statement = Stmt(record["id"], record["kind"], record["text"])
            statements.append(statement)
            mentions[statement.id] = {
                mention["entity_id"]
                for mention in record.get("mentions", [])
                if mention.get("entity_id")
            }
            links.extend(
                Link(statement.id, link["to_id"], link["link_type"])
                for link in record.get("links", [])
                if link.get("to_id", "").startswith("stm_")
            )
    vocabulary = sorted({link.link_type for link in links})
    return statements, links, mentions, vocabulary, store.seed_aliases_by_type()


def load_store(
    data_dir: Path,
) -> tuple[
    list[Stmt],
    list[Link],
    dict[str, set[str]],
    list[str],
    dict[str, tuple[str, ...]],
]:
    """Load evaluator data from an existing Mycelium data directory."""
    conn = store.connect(data_dir / "mycelium.db")
    try:
        statements: list[Stmt] = []
        page_size = 500
        offset = 0
        while True:
            rows = store.list_statements(conn, limit=page_size, offset=offset)
            if not rows:
                break
            statements.extend(Stmt(row["id"], row["kind"], row["text"]) for row in rows)
            offset += page_size

        links = [
            Link(row["from_statement_id"], row["to_statement_id"], row["link_type"])
            for row in conn.execute(
                "SELECT from_statement_id, to_statement_id, link_type "
                "FROM statement_links"
            )
        ]
        mentions: dict[str, set[str]] = defaultdict(set)
        for row in conn.execute(
            "SELECT sm.statement_id, n.entity_id "
            "FROM statement_mentions sm JOIN names n ON n.id = sm.name_id"
        ):
            mentions[row["statement_id"]].add(row["entity_id"])
        materialized = set(store.list_link_types(conn))
        glossary = {
            row["link_type"] for row in store.list_statement_link_type_glossary(conn)
        }
        vocabulary = sorted(materialized | glossary)
        return (
            statements,
            links,
            dict(mentions),
            vocabulary,
            store.aliases_by_type(conn),
        )
    finally:
        conn.close()


def _show_cues(
    statements: list[Stmt],
    limit: int,
    aliases: Mapping[str, Sequence[str]],
) -> None:
    """Print at most the requested number of matched cue texts per pattern."""
    if limit <= 0:
        return
    shown: dict[str, int] = defaultdict(int)
    samples: list[tuple[str, str, str]] = []
    for statement in statements:
        for cue in find_cues(statement.text, statement.kind, aliases):
            if shown[cue.pattern] < limit:
                samples.append((cue.pattern, cue.cue, cue.phrase or ""))
                shown[cue.pattern] += 1
    if samples:
        print("Cue samples:")
        for pattern_name, cue_text, phrase in sorted(samples):
            print(f"{pattern_name}: [{cue_text}] -> {phrase}")


def main(argv: list[str] | None = None) -> int:
    """Run the evaluator and write its count-only Markdown report."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data-dir", type=Path, help="Mycelium data directory")
    source.add_argument("--snapshot", type=Path, help="get_statements JSONL export")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("link_pattern_report.md"),
        help="Output Markdown file (default: ./link_pattern_report.md)",
    )
    parser.add_argument(
        "--label", help="Source label, including its date (default: source path)"
    )
    parser.add_argument(
        "--show-cues",
        type=int,
        default=0,
        metavar="N",
        help="Print up to N cue samples per pattern (default: 0)",
    )
    args = parser.parse_args(argv)

    source_path = args.data_dir if args.data_dir is not None else args.snapshot
    if args.data_dir is not None:
        db_path = args.data_dir / "mycelium.db"
        if not db_path.exists():
            print(f"database not found: {db_path}", file=sys.stderr)
            return 1
        statements, links, mentions, vocabulary, aliases = load_store(args.data_dir)
    else:
        statements, links, mentions, vocabulary, aliases = load_snapshot(args.snapshot)

    report = measure(statements, links, mentions, vocabulary, aliases)
    source_label = args.label if args.label is not None else str(source_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_markdown(report, source_label=source_label), encoding="utf-8"
    )
    _show_cues(statements, args.show_cues, aliases)
    totals = report["totals"]
    rate = totals["hit_rate"] or 0.0
    print(
        f"Measured {totals['links']} links over {totals['statements']} statements: "
        f"{totals['hits']} hits ({rate:.1%})"
    )
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
