"""Seed the `kb-authoring` guideline set into the prompt-text store.

Six rows under type `guideline-set`: the set-wide guidance plus one template
per Diátaxis document type, so a generation run fetches exactly the type it
is writing. See `docs/GUIDELINE_SETS.md` for the naming convention.

Each row is its source file verbatim. The guidance has its own source under
`guidelines/`, addressed to a run whose only handle on the set is the store:
it names the templates as the sibling rows they are. The templates are the
kb-authoring skill's files, which say the same thing to either consumer.

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

REPO_ROOT = Path(__file__).resolve().parents[1]

_SKILL_TEMPLATES = ".claude/skills/kb-authoring/templates"

# Row slot -> source file, relative to REPO_ROOT. `guidance` is the set-wide
# instruction; the rest are named for the document type they produce.
SOURCES = {
    "guidance": "guidelines/kb-authoring/guidance.md",
    "tutorial": f"{_SKILL_TEMPLATES}/tutorial.md",
    "how-to": f"{_SKILL_TEMPLATES}/how-to.md",
    "reference": f"{_SKILL_TEMPLATES}/reference.md",
    "explanation": f"{_SKILL_TEMPLATES}/explanation.md",
    "troubleshooting": f"{_SKILL_TEMPLATES}/troubleshooting.md",
}


def read_rows(root: Path) -> dict[str, str]:
    """The set's rows as {name: text}, each its source file verbatim."""
    return {
        f"{SET_NAME}/{slot}": (root / rel).read_text(encoding="utf-8")
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
    """`outdated` for a dry run, which must store nothing.

    `prompt_store.connect` writes: it creates the file and sets its journal
    mode. So an absent DB is answered without opening it — nothing is stored
    there, so every row is pending — and an existing one is opened `mode=ro`,
    which SQLite refuses to write to. Reading a WAL database still
    coordinates through its `-shm` sidecar; the guarantee is over the
    database, not over every file sitting next to it."""
    if not db_path.exists():
        return list(rows)
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return outdated(conn, rows)
    finally:
        conn.close()


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

    rows = read_rows(REPO_ROOT)
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
