"""One-shot backfill: rebuild every statement's mentions from scratch with
the deterministic matcher, and populate the suspect review queue.

Run this once after the derived-mentions feature lands (or any time the
materialized mentions need a clean rebuild). It is idempotent — running it
twice yields the same rows.

What it does:
  1. Migrate the substrate schema (ensures the v5 tables exist).
  2. Delete ALL existing statement_mentions and pending_mentions — the old
     hand-asserted edges are discarded; the matcher is now the source of
     truth (legacy rows that lexical matching won't reproduce are gone by
     design).
  3. Re-derive every statement's mentions from its text: distinctive
     matches become statement_mentions, suspect matches become open
     pending_mentions for review.
  4. Clear the recompute queue (a full rebuild supersedes any pending work).

Needs no embedder / vector index — derivation is pure text matching — so it
opens a plain store connection rather than booting the server.

Run:
  uv run python scripts/backfill_derived_mentions.py --data-dir /path/to/.mycelium
  uv run python scripts/backfill_derived_mentions.py --dry-run    # report only
(--data-dir defaults to $MYCELIUM_DATA_DIR, then ./.mycelium)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from mycelium import store

CHUNK = 200  # statements re-derived per committed transaction


def _resolve_data_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("MYCELIUM_DATA_DIR")
    if env:
        return Path(env)
    return Path(".mycelium")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=None, help="substrate data dir (holds mycelium.db)")
    ap.add_argument("--dry-run", action="store_true", help="report counts without writing")
    args = ap.parse_args()

    data_dir = _resolve_data_dir(args.data_dir)
    db_path = data_dir / "mycelium.db"
    if not db_path.exists():
        raise SystemExit(f"no substrate at {db_path}")
    history_path = data_dir / "mycelium-history.db"

    conn = store.connect(db_path, history_path=history_path if history_path.exists() else None)
    store.migrate(conn)
    store.set_actor("system:backfill")

    statements = store.all_statements_with_text(conn)
    index = store.build_name_index(conn)
    n_names = sum(len(v) for v in index.values())
    print(f"substrate: {len(statements)} statements, {n_names} names")

    if args.dry_run:
        mentions = suspects = 0
        for row in statements:
            result = store.mentions.match_text(row["text"], index)
            mentions += len(result.mentions)
            suspects += len(result.suspects)
        print(f"[dry-run] would materialize {mentions} mentions, "
              f"{suspects} suspect occurrences across {len(statements)} statements")
        return

    # Wipe the old materialized state — the matcher is now authoritative.
    conn.execute("DELETE FROM statement_mentions")
    conn.execute("DELETE FROM pending_mentions")
    conn.execute("DELETE FROM mention_recompute_queue")
    conn.commit()

    total_mentions = total_suspects = 0
    for i, row in enumerate(statements, 1):
        result = store.derive_mentions(conn, row["id"], row["text"], index, commit=False)
        total_mentions += len(result.mentions)
        total_suspects += len(result.suspects)
        if i % CHUNK == 0:
            conn.commit()
            print(f"  ...{i}/{len(statements)}")
    conn.commit()

    print(
        f"done: {total_mentions} mentions materialized, "
        f"{total_suspects} suspect occurrences queued for review "
        f"across {len(statements)} statements"
    )


if __name__ == "__main__":
    main()
