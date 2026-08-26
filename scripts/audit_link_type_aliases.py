"""Audit automatically absorbed link-type aliases for human review.

The report puts low-confidence and low-scoring decisions first so a reviewer
can quickly find direction-blind cue-resolution misroutes.

Columns: `link_type, alias, provenance, score, created_at, created_by`. A cell
whose text a spreadsheet would evaluate as a formula is written with a leading
apostrophe, because alias text comes from ingested prose.

Usage:
    uv run python scripts/audit_link_type_aliases.py [--data-dir PATH]
        [--out PATH] [--all]

Defaults: `--data-dir` reads `MYCELIUM_DATA_DIR` (same env var as the server,
falls back to `./.mycelium`); `--out` writes to
`./link_type_alias_audit.csv`.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

from mycelium import store

_AUTOMATIC_PROVENANCE = ("auto", "auto:low-confidence")
# A leading one of these makes a spreadsheet evaluate the cell as a formula.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")
_COLUMNS = [
    "link_type",
    "alias",
    "provenance",
    "score",
    "direction",
    "created_at",
    "created_by",
]


def _csv_cell(value: Any) -> Any:
    """Quote a cell a spreadsheet would otherwise read as a formula."""
    # Alias text comes from ingested prose, not from the operator running this.
    if isinstance(value, str) and value[:1] in _FORMULA_LEAD:
        return f"'{value}"
    return value


def _audit(conn, *, include_all: bool) -> tuple[int, int, int, list[dict]]:
    """Collect alias counts and CSV-ready audit rows."""
    aliases = store.list_link_type_aliases(conn)
    automatic = [row for row in aliases if row["provenance"] in _AUTOMATIC_PROVENANCE]
    low_confidence = sum(row["provenance"] == "auto:low-confidence" for row in aliases)
    selected = aliases if include_all else automatic
    rows = [{column: row[column] for column in _COLUMNS} for row in selected]

    # The least-trustworthy decisions are worth a human's first minutes.
    rows.sort(
        key=lambda row: (
            row["provenance"] != "auto:low-confidence",
            row["score"] if row["score"] is not None else float("inf"),
            row["link_type"],
            row["alias"],
        )
    )
    return len(aliases), len(automatic), low_confidence, rows


def main() -> int:
    """Write the configured link-type alias audit report."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser(),
        help="Mycelium data directory (default: $MYCELIUM_DATA_DIR or ./.mycelium)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("link_type_alias_audit.csv"),
        help="Output CSV file (default: ./link_type_alias_audit.csv)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include curator and seed aliases in the CSV",
    )
    args = parser.parse_args()

    db_path = args.data_dir / "mycelium.db"
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    total, automatic, low_confidence, rows = _audit(
        conn,
        include_all=args.all,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: _csv_cell(value) for column, value in row.items()} for row in rows
        )

    print(
        f"Scanned {total} aliases; {automatic} automatic "
        f"({low_confidence} low-confidence)"
    )
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
