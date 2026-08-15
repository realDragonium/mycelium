"""Push the packaged `kb-authoring` guideline set into an instance's store.

Startup already seeds these rows (`server._seed_prompt_texts`), so a fresh
instance has the set before anything is run by hand. This script exists for
the case startup deliberately refuses: the source files have moved on and you
want the instance to follow. It compares each row against the stored latest
version and appends a new one where they differ — including over an operator's
edit, which is why it is a checkout tool with a `--dry-run` rather than
something a boot does behind your back.

Both writes read the same files and build the same names, from
`mycelium.guidelines`. What they do not share is the write: `save` here,
`save_if_absent` at startup. Collapsing them would mean either a redeploy
reverting live edits or a checkout unable to publish a rewritten template.

Idempotent. The store is append-only, so re-running against unchanged sources
writes nothing and creates no versions. `--dry-run` reports which rows would
be superseded before you commit to it.

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

from mycelium import guidelines, prompt_store

ACTOR = "system:seed-guideline-sets"


def outdated(conn: sqlite3.Connection, rows: dict[str, str]) -> list[str]:
    """The rows a seed run would append: those whose stored latest text is
    missing or differs. Empty when the store already matches the sources."""
    return [
        name
        for name, text in rows.items()
        if prompt_store.latest_text(conn, guidelines.TYPE, name) != text
    ]


def seed(conn: sqlite3.Connection, rows: dict[str, str]) -> list[str]:
    """Append the outdated rows and return their names."""
    names = outdated(conn, rows)
    for name in names:
        prompt_store.save(
            conn,
            type=guidelines.TYPE,
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

    rows = guidelines.read_rows()
    db_path = data_dir / "mycelium-prompts.db"

    if args.dry_run:
        names = pending(db_path, rows)
        print(f"[dry-run] would write {len(names)}/{len(rows)} rows")
        for name in names:
            print(f"  {guidelines.TYPE}/{name}")
        return

    conn = prompt_store.connect(db_path)
    prompt_store.migrate(conn)
    written = seed(conn, rows)
    print(
        f"seeded {len(written)}/{len(rows)} rows of the "
        f"'{guidelines.SET_NAME}' guideline set"
    )
    for name in written:
        print(f"  {guidelines.TYPE}/{name}")
    if not written:
        print("  (already current — nothing appended)")


if __name__ == "__main__":
    main()
