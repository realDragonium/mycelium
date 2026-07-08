"""Audit a mycelium database for statements that trip the phrasing catalog.

Walks every statement in the database, runs `phrasing.check()` on its
text, and writes one CSV row per violation. A statement with multiple
violations produces multiple rows so the file can be sorted, filtered,
or pivoted by category.

Columns: `statement_id, text, category, matched_text, position, rule,
recommendation`. Rows are ordered first by category (compound before
the more interpretive categories), then by statement_id, then by the
violation's position within the text.

Usage:
    uv run python scripts/audit_phrasing.py [--data-dir PATH] [--out PATH]

Defaults: `--data-dir` reads `MYCELIUM_DATA_DIR` (same env var as the
server, falls back to `./.mycelium`); `--out` writes to
`./phrasing_audit.csv`.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from mycelium import phrasing, store


# Sort order for the `category` column. Cheaper / more mechanical fixes
# come first so a reviewer working top-to-bottom hits the easy wins
# before the interpretive ones. Unknown categories sort to the end.
_CATEGORY_ORDER = [
    "compound",
    "precondition_in_text",
    "universal_claim",
    "rule_shaped",
    "property_shaped",
    "hedge",
]
_CATEGORY_RANK = {cat: i for i, cat in enumerate(_CATEGORY_ORDER)}

_COLUMNS = [
    "statement_id",
    "text",
    "category",
    "matched_text",
    "position",
    "rule",
    "recommendation",
]


def _audit(conn) -> tuple[int, list[dict[str, object]]]:
    """Returns (total_scanned, rows). Each row is one violation, ready
    to write to CSV."""
    total = 0
    rows: list[dict[str, object]] = []
    page = 500
    offset = 0
    while True:
        records = store.list_statements(conn, limit=page, offset=offset)
        if not records:
            break
        for rec in records:
            total += 1
            for v in phrasing.check(rec["text"]):
                rows.append(
                    {
                        "statement_id": rec["id"],
                        "text": rec["text"],
                        "category": v["category"],
                        "matched_text": v["matched_text"],
                        "position": v["position"],
                        "rule": v["rule"],
                        "recommendation": v["recommendation"],
                    }
                )
        offset += page

    rows.sort(
        key=lambda r: (
            _CATEGORY_RANK.get(r["category"], len(_CATEGORY_ORDER)),
            r["statement_id"],
            r["position"],
        )
    )
    return total, rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        default=Path("phrasing_audit.csv"),
        help="Output CSV file (default: ./phrasing_audit.csv)",
    )
    args = parser.parse_args()

    db_path = args.data_dir / "mycelium.db"
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    total, rows = _audit(conn)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    violators = len({r["statement_id"] for r in rows})
    print(
        f"Scanned {total} statements; {violators} violators, {len(rows)} violation rows"
    )
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
