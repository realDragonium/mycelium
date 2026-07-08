"""Read-only inventory of every annotation in the substrate.

The annotation tools were removed from the MCP/HTTP surface, but the
underlying rows still exist. This script walks the `annotations` table
and prints each row with its attachments (statements and entities) and
mentions, so an operator can decide per annotation whether to drop it
or promote it into a first-class statement before dropping.

Read-only. No writes, no embeddings, no index access — just SQLite.

Usage:
    uv run python scripts/list_annotations.py /path/to/data_dir
    uv run python scripts/list_annotations.py /path/to/data_dir --kind permission
    uv run python scripts/list_annotations.py /path/to/data_dir --json > anns.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from mycelium import store


def fetch_annotations(conn: sqlite3.Connection, kind: str | None) -> list[sqlite3.Row]:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(annotations)")}
    select = ["id", "kind", "text"]
    for opt in ("created_at", "created_by"):
        if opt in cols:
            select.append(opt)
    sql = f"SELECT {', '.join(select)} FROM annotations"
    params: tuple[Any, ...] = ()
    if kind is not None:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY kind, rowid"
    return conn.execute(sql, params).fetchall()


def attached_statements(
    conn: sqlite3.Connection, annotation_id: str
) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT s.id, s.kind, s.text FROM statements s "
        "JOIN statement_annotations sa ON sa.statement_id = s.id "
        "WHERE sa.annotation_id = ? "
        "ORDER BY s.rowid",
        (annotation_id,),
    ).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows]


def attached_entities(
    conn: sqlite3.Connection, annotation_id: str
) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT e.id, ("
        "  SELECT n.text FROM names n WHERE n.entity_id = e.id "
        "  ORDER BY n.text LIMIT 1"
        ") AS primary_name "
        "FROM entities e "
        "JOIN entity_annotations ea ON ea.entity_id = e.id "
        "WHERE ea.annotation_id = ? "
        "ORDER BY e.rowid",
        (annotation_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["primary_name"] or "<unnamed>"} for r in rows]


def mentioned_entities(
    conn: sqlite3.Connection, annotation_id: str
) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT n.id AS name_id, n.text AS name, n.entity_id "
        "FROM annotation_mentions am "
        "JOIN names n ON n.id = am.name_id "
        "WHERE am.annotation_id = ? "
        "ORDER BY n.text",
        (annotation_id,),
    ).fetchall()
    return [
        {
            "name_id": r["name_id"],
            "name": r["name"],
            "entity_id": r["entity_id"],
        }
        for r in rows
    ]


def hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "kind": row["kind"],
        "text": row["text"],
        "created_at": row["created_at"] if "created_at" in keys else None,
        "created_by": row["created_by"] if "created_by" in keys else None,
        "attached_statements": attached_statements(conn, row["id"]),
        "attached_entities": attached_entities(conn, row["id"]),
        "mentions": mentioned_entities(conn, row["id"]),
    }


def render_text(records: list[dict[str, Any]]) -> str:
    out: list[str] = []
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r)
    for kind in sorted(by_kind):
        bucket = by_kind[kind]
        out.append(f"### kind: {kind}  ({len(bucket)})")
        out.append("")
        for r in bucket:
            out.append(f"  {r['id']}")
            out.append(f"    text: {r['text']!r}")
            if r["created_by"] or r["created_at"]:
                out.append(f"    created: {r['created_at']} by {r['created_by']!r}")
            if r["attached_statements"]:
                out.append(
                    f"    attached to {len(r['attached_statements'])} statement(s):"
                )
                for s in r["attached_statements"]:
                    preview = s["text"].replace("\n", " ")
                    if len(preview) > 100:
                        preview = preview[:100] + "…"
                    out.append(f"      [{s['kind']}] {s['id']}  {preview!r}")
            if r["attached_entities"]:
                out.append(
                    f"    attached to {len(r['attached_entities'])} entit(y/ies):"
                )
                for e in r["attached_entities"]:
                    out.append(f"      {e['id']}  ({e['name']})")
            if not r["attached_statements"] and not r["attached_entities"]:
                out.append("    ORPHAN (no attachments)")
            if r["mentions"]:
                names = ", ".join(m["name"] for m in r["mentions"])
                out.append(f"    mentions: {names}")
            out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="mycelium data directory")
    parser.add_argument(
        "--kind",
        help="filter to a single annotation kind (e.g. permission, property, fact)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of grouped text",
    )
    args = parser.parse_args()

    db_path = args.data_dir / "mycelium.db"
    if not db_path.exists():
        print(f"error: {db_path} does not exist", file=sys.stderr)
        return 1

    conn = store.connect(db_path)

    rows = fetch_annotations(conn, args.kind)
    records = [hydrate(conn, r) for r in rows]

    if args.json:
        json.dump(records, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    total = len(records)
    if args.kind:
        print(f"Annotations of kind {args.kind!r} in {db_path}: {total}")
    else:
        print(f"Annotations in {db_path}: {total}")
    print()

    if total == 0:
        return 0

    orphans = sum(
        1
        for r in records
        if not r["attached_statements"] and not r["attached_entities"]
    )
    if orphans:
        print(f"({orphans} orphan — no statement or entity attachment)")
        print()

    print(render_text(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
