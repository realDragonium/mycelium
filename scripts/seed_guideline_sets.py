"""Seed the `kb-authoring` guideline set into the prompt-text store.

Six rows under type `guideline-set`: the set-wide guidance from the
kb-authoring skill plus one template per Diátaxis document type, so a
generation run fetches exactly the type it is writing. See
`docs/GUIDELINE_SETS.md` for the naming convention.

Idempotent. The store is append-only, so the seed reads the latest version
of each row first and appends only what differs — re-running it against
unchanged sources writes nothing and creates no versions. An operator edit
that has drifted from the file is a difference like any other and gets
superseded; `--dry-run` reports which rows that would be before you commit
to it.

Writes through `prompt_store` rather than the `save_prompt_text` tool: the
rows land in an instance's own SQLite file, so there is no server to boot
and no role to satisfy.

Run:
  uv run python scripts/seed_guideline_sets.py --data-dir /path/to/.mycelium
  uv run python scripts/seed_guideline_sets.py --dry-run    # report only
(--data-dir defaults to $MYCELIUM_DATA_DIR, then ./.mycelium)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from mycelium import prompt_store

GUIDELINE_TYPE = "guideline-set"
SET_NAME = "kb-authoring"
ACTOR = "system:seed-guideline-sets"

SOURCE_DIR = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "kb-authoring"

# Row slot -> source file under SOURCE_DIR. `guidance` is the set-wide
# instruction; the rest are named for the document type they produce.
SOURCES = {
    "guidance": "SKILL.md",
    "tutorial": "templates/tutorial.md",
    "how-to": "templates/how-to.md",
    "reference": "templates/reference.md",
    "explanation": "templates/explanation.md",
    "troubleshooting": "templates/troubleshooting.md",
}


def read_rows(source_dir: Path) -> dict[str, str]:
    """The set's rows as {name: text}, read from the skill directory."""
    return {
        f"{SET_NAME}/{slot}": (source_dir / rel).read_text(encoding="utf-8")
        for slot, rel in SOURCES.items()
    }


def outdated(conn: sqlite3.Connection, rows: dict[str, str]) -> list[str]:
    """The rows a seed run would append: those whose stored latest text is
    missing or differs. Empty when the store already matches the sources."""
    return [
        name
        for name, text in rows.items()
        if prompt_store.latest_text(conn, GUIDELINE_TYPE, name) != text
    ]


def seed(conn: sqlite3.Connection, rows: dict[str, str]) -> list[str]:
    """Append the outdated rows and return their names."""
    names = outdated(conn, rows)
    for name in names:
        prompt_store.save(
            conn,
            type=GUIDELINE_TYPE,
            name=name,
            text=rows[name],
            created_by=ACTOR,
        )
    return names


def pending(db_path: Path, rows: dict[str, str]) -> list[str]:
    """`outdated`, read-only down to the filesystem: opening the DB would
    create the file and WAL-mode it, so an absent prompts DB is answered
    without touching it — nothing is stored, so every row is pending."""
    if not db_path.exists():
        return list(rows)
    return outdated(prompt_store.connect(db_path), rows)


def _resolve_data_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("MYCELIUM_DATA_DIR")
    if env:
        return Path(env)
    return Path(".mycelium")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir", default=None, help="instance data dir (holds the prompts DB)"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    args = ap.parse_args()

    data_dir = _resolve_data_dir(args.data_dir)
    if not data_dir.is_dir():
        raise SystemExit(f"no data dir at {data_dir}")

    rows = read_rows(SOURCE_DIR)
    db_path = data_dir / "mycelium-prompts.db"

    if args.dry_run:
        names = pending(db_path, rows)
        print(f"[dry-run] would write {len(names)}/{len(rows)} rows")
        for name in names:
            print(f"  {GUIDELINE_TYPE}/{name}")
        return

    conn = prompt_store.connect(db_path)
    prompt_store.migrate(conn)
    written = seed(conn, rows)
    print(f"seeded {len(written)}/{len(rows)} rows of the '{SET_NAME}' guideline set")
    for name in written:
        print(f"  {GUIDELINE_TYPE}/{name}")
    if not written:
        print("  (already current — nothing appended)")


if __name__ == "__main__":
    main()
