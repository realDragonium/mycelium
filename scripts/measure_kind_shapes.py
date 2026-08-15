"""Measure kind classification precision and recall without storing text.

Each statement is classified by positive phrasing shapes. The Markdown report
contains counts only; ``--show-misses`` may print sample statement text to
stdout, but statement text is never included in the report.

Usage:
    uv run python scripts/measure_kind_shapes.py --data-dir PATH
        [--out PATH] [--label TEXT] [--show-misses N]
    uv run python scripts/measure_kind_shapes.py --snapshot FILE.jsonl
        [--out PATH] [--label TEXT] [--show-misses N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from mycelium import store
from mycelium.connect.shapes import (
    DESCRIPTIVE_KINDS,
    PRESCRIPTIVE_KINDS,
    SHAPE_NAMES,
    classify,
)

_STANDARD_KINDS = DESCRIPTIVE_KINDS + PRESCRIPTIVE_KINDS
_FLOOR_THRESHOLD = 0.9


def _rate(numerator: int, denominator: int) -> float | None:
    """Return a fraction, leaving empty denominators without a rate."""
    return numerator / denominator if denominator else None


def _kind_order(rows: list[tuple[str, str]]) -> list[str]:
    """Return standard kinds followed by extra ground-truth kinds."""
    extras = sorted({kind for kind, _ in rows} - set(_STANDARD_KINDS))
    return [*_STANDARD_KINDS, *extras]


def _empty_kind_row() -> dict[str, int | float | None]:
    """Create an empty aggregate row for one true kind."""
    return {
        "n": 0,
        "correct": 0,
        "wrong": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "recall": None,
        "flag_rate": None,
    }


def _empty_assigned_row() -> dict[str, int | float | None]:
    """Create an empty aggregate row for one assigned (predicted) kind."""
    return {"assigned": 0, "correct": 0, "wrong": 0, "precision": None}


def summarize(rows: list[tuple[str, str]]) -> dict:
    """Summarize shape classifications as plain report data."""
    kinds = _kind_order(rows)
    by_kind = {kind: _empty_kind_row() for kind in kinds}
    # Precision is a property of a prediction, so false positives accumulate
    # against the kind that was assigned, not the kind that was true.
    by_assigned_kind = {kind: _empty_assigned_row() for kind in kinds}
    confusion: dict[str, dict[str, int]] = {kind: {} for kind in kinds}
    # A shape name is "<kind>-<discriminator>", so a shape that never fires
    # still names its kind in the report.
    by_shape: dict[str, dict[str, str | int | float | None]] = {
        name: {
            "kind": name.split("-", 1)[0],
            "fires": 0,
            "correct": 0,
            "precision": None,
        }
        for name in SHAPE_NAMES
    }
    totals = {
        "statements": len(rows),
        "assigned": 0,
        "correct": 0,
        "wrong": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "precision": None,
        "recall": None,
        "flag_rate": None,
    }

    for true_kind, text in rows:
        result = classify(text)
        kind_row = by_kind[true_kind]
        kind_row["n"] += 1
        if result.status == "assigned":
            totals["assigned"] += 1
            column = result.kind
            assigned_row = by_assigned_kind.setdefault(column, _empty_assigned_row())
            assigned_row["assigned"] += 1
            if result.kind == true_kind:
                totals["correct"] += 1
                kind_row["correct"] += 1
                assigned_row["correct"] += 1
            else:
                totals["wrong"] += 1
                kind_row["wrong"] += 1
                assigned_row["wrong"] += 1
        else:
            column = f"({result.status})"
            totals[result.status] += 1
            kind_row[result.status] += 1
        confusion_row = confusion[true_kind]
        confusion_row[column] = confusion_row.get(column, 0) + 1

        for match in result.matches:
            shape_row = by_shape[match.shape]
            shape_row["fires"] += 1
            if match.kind == true_kind:
                shape_row["correct"] += 1

    for kind_row in by_kind.values():
        flagged = int(kind_row["ambiguous"]) + int(kind_row["unmatched"])
        kind_row["recall"] = _rate(int(kind_row["correct"]), int(kind_row["n"]))
        kind_row["flag_rate"] = _rate(flagged, int(kind_row["n"]))
    for assigned_row in by_assigned_kind.values():
        assigned_row["precision"] = _rate(
            int(assigned_row["correct"]), int(assigned_row["assigned"])
        )

    totals["precision"] = _rate(int(totals["correct"]), int(totals["assigned"]))
    totals["recall"] = _rate(int(totals["correct"]), int(totals["statements"]))
    totals["flag_rate"] = _rate(
        int(totals["ambiguous"]) + int(totals["unmatched"]),
        int(totals["statements"]),
    )
    for shape_row in by_shape.values():
        shape_row["precision"] = _rate(
            int(shape_row["correct"]), int(shape_row["fires"])
        )

    kinds_met: list[str] = []
    kinds_missed: list[str] = []
    kinds_without_ground_truth: list[str] = []
    for kind, assigned_row in by_assigned_kind.items():
        if int(assigned_row["assigned"]) == 0:
            kinds_without_ground_truth.append(kind)
        elif float(assigned_row["precision"]) >= _FLOOR_THRESHOLD:
            kinds_met.append(kind)
        else:
            kinds_missed.append(kind)

    return {
        "totals": totals,
        "by_kind": by_kind,
        "by_assigned_kind": by_assigned_kind,
        "confusion": confusion,
        "by_shape": by_shape,
        "floor": {
            "threshold": _FLOOR_THRESHOLD,
            "kinds_met": kinds_met,
            "kinds_missed": kinds_missed,
            "kinds_without_ground_truth": kinds_without_ground_truth,
        },
    }


def _fraction(numerator: int, denominator: int) -> str:
    """Format a count fraction or an empty-denominator marker."""
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})"


def render_markdown(report: dict, *, source_label: str) -> str:
    """Render a count-only Markdown report."""
    totals = report["totals"]
    lines = [
        "# Kind Shape Classification Accuracy",
        "",
        f"**Source:** {source_label} — {totals['statements']} statements",
        "",
        "## Totals",
        "",
        (
            "| Statements | Assigned | Correct | Wrong | Ambiguous | Unmatched | "
            "Precision | Recall | Flag rate |"
        ),
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {totals['statements']} | {totals['assigned']} | "
            f"{totals['correct']} | {totals['wrong']} | {totals['ambiguous']} | "
            f"{totals['unmatched']} | "
            f"{_fraction(totals['correct'], totals['assigned'])} | "
            f"{_fraction(totals['correct'], totals['statements'])} | "
            f"{_fraction(totals['ambiguous'] + totals['unmatched'], totals['statements'])} |"
        ),
        "",
        "## By true kind",
        "",
        (
            "| Kind | n | Correct | Misassigned | Ambiguous | Unmatched | "
            "Recall | Flag rate |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind, row in report["by_kind"].items():
        flagged = row["ambiguous"] + row["unmatched"]
        lines.append(
            f"| {kind} | {row['n']} | {row['correct']} | {row['wrong']} | "
            f"{row['ambiguous']} | {row['unmatched']} | "
            f"{_fraction(row['correct'], row['n'])} | "
            f"{_fraction(flagged, row['n'])} |"
        )

    lines.extend(
        [
            "",
            "## Precision by assigned kind",
            "",
            "| Assigned kind | Assigned | Correct | Wrong | Precision |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for kind, row in report["by_assigned_kind"].items():
        lines.append(
            f"| {kind} | {row['assigned']} | {row['correct']} | {row['wrong']} | "
            f"{_fraction(row['correct'], row['assigned'])} |"
        )

    assigned_columns = [
        kind
        for kind in report["by_kind"]
        if any(kind in row for row in report["confusion"].values())
    ]
    confusion_columns = [*assigned_columns, "(ambiguous)", "(unmatched)"]
    lines.extend(
        [
            "",
            "## Confusion matrix",
            "",
            "| True kind | " + " | ".join(confusion_columns) + " |",
            "| --- | " + " | ".join("---:" for _ in confusion_columns) + " |",
        ]
    )
    for kind, row in report["confusion"].items():
        counts = " | ".join(str(row.get(column, 0)) for column in confusion_columns)
        lines.append(f"| {kind} | {counts} |")

    lines.extend(
        [
            "",
            "## By shape",
            "",
            "| Shape | Kind | Fires | Correct | Precision |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for shape_name, row in report["by_shape"].items():
        lines.append(
            f"| {shape_name} | {row['kind']} | {row['fires']} | "
            f"{row['correct']} | {_fraction(row['correct'], row['fires'])} |"
        )

    lines.extend(["", "## Floor", ""])
    floor = report["floor"]
    threshold = floor["threshold"]
    lines.append(
        f"Precision of an assigned kind must reach {threshold:.0%}. A kind the "
        "classifier never assigned has nothing to measure."
    )
    lines.append("")
    for kind, row in report["by_assigned_kind"].items():
        if kind in floor["kinds_without_ground_truth"]:
            lines.append(f"- `{kind}`: never assigned in this snapshot")
        else:
            result = "met" if kind in floor["kinds_met"] else "missed"
            lines.append(
                f"- `{kind}`: {result} — "
                f"{_fraction(row['correct'], row['assigned'])} precision"
            )
    lines.append("")
    return "\n".join(lines)


def load_snapshot(path: Path) -> list[tuple[str, str]]:
    """Load kind and text pairs from a statement JSONL snapshot."""
    rows: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as snapshot:
        for line_number, line in enumerate(snapshot, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid JSON on line {line_number}: {error}"
                ) from error
            rows.append((record["kind"], record["text"]))
    return rows


def load_store(data_dir: Path) -> list[tuple[str, str]]:
    """Load kind and text pairs from an existing Mycelium data directory."""
    conn = store.connect(data_dir / "mycelium.db")
    try:
        rows: list[tuple[str, str]] = []
        page_size = 500
        offset = 0
        while True:
            page = store.list_statements(conn, limit=page_size, offset=offset)
            if not page:
                break
            rows.extend((row["kind"], row["text"]) for row in page)
            offset += page_size
        return rows
    finally:
        conn.close()


def _misses(rows: list[tuple[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Group missed statement text for optional stdout diagnostics."""
    buckets: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"misclassified": [], "ambiguous": [], "unmatched": []}
    )
    for true_kind, text in rows:
        result = classify(text)
        if result.status == "assigned" and result.kind != true_kind:
            buckets[true_kind]["misclassified"].append(f"{text} -> {result.kind}")
        elif result.status == "ambiguous":
            matched_kinds = ", ".join(sorted({match.kind for match in result.matches}))
            buckets[true_kind]["ambiguous"].append(f"{text} -> {matched_kinds}")
        elif result.status == "unmatched":
            buckets[true_kind]["unmatched"].append(text)
    return buckets


def _show_misses(rows: list[tuple[str, str]], limit: int) -> None:
    """Print up to the requested number of samples per true-kind bucket."""
    if limit <= 0:
        return
    buckets = _misses(rows)
    for true_kind in _kind_order(rows):
        for bucket_name in ("misclassified", "ambiguous", "unmatched"):
            samples = buckets[true_kind][bucket_name][:limit]
            if samples:
                print(f"{true_kind} {bucket_name}:")
                for sample in samples:
                    print(f"- {sample}")


def main(argv: list[str] | None = None) -> int:
    """Run the evaluator and write its count-only Markdown report."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data-dir", type=Path, help="Mycelium data directory")
    source.add_argument("--snapshot", type=Path, help="Statement JSONL export")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("kind_shape_report.md"),
        help="Output Markdown file (default: ./kind_shape_report.md)",
    )
    parser.add_argument(
        "--label", help="Source label, including its date (default: source path)"
    )
    parser.add_argument(
        "--show-misses",
        type=int,
        default=0,
        metavar="N",
        help="Print up to N samples per miss bucket (default: 0)",
    )
    args = parser.parse_args(argv)

    source_path = args.data_dir if args.data_dir is not None else args.snapshot
    if args.data_dir is not None:
        db_path = args.data_dir / "mycelium.db"
        if not db_path.exists():
            print(f"database not found: {db_path}", file=sys.stderr)
            return 1
        rows = load_store(args.data_dir)
    else:
        rows = load_snapshot(args.snapshot)

    report = summarize(rows)
    source_label = args.label if args.label is not None else str(source_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_markdown(report, source_label=source_label), encoding="utf-8"
    )
    _show_misses(rows, args.show_misses)
    totals = report["totals"]
    precision = totals["precision"] or 0.0
    print(
        f"Classified {totals['statements']} statements: "
        f"{totals['assigned']} assigned, {totals['correct']} correct "
        f"({precision:.1%} precision)"
    )
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
