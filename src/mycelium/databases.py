"""The SQLite databases the engine keeps in its data directory.

`FILES` is the list a deployment must replicate and restore; read it with
`mycelium databases` rather than copying it. A restore that misses a file is
silent on its own: the engine recreates that database empty and serves on, so
`check_restore` looks for the one shape a fresh install never has — a
substrate holding knowledge beside a missing peer.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)

SUBSTRATE = "mycelium.db"

# Each database, with the earliest substrate schema version (`user_version`)
# whose engine created it on every start. A populated substrate at or past
# that version can only lack the file through a partial restore; an older one
# may predate the file and be upgrading. Migrations v1-v5 shipped with the
# first commit, which already created history, auth and drafts; prompts
# arrived before v7. A new database gets `migrations.CURRENT_VERSION + 1`, so
# it is checked once a later migration proves the substrate has run its code.
FILES: dict[str, int] = {
    SUBSTRATE: 0,
    "mycelium-history.db": 5,
    "mycelium-auth.db": 5,
    "mycelium-drafts.db": 5,
    "mycelium-prompts.db": 7,
    "mycelium-media.db": 25,
}


def partial_restore(data_dir: Path) -> tuple[str, ...]:
    """Databases missing beside a populated substrate that has run code
    creating them.

    Only meaningful before startup opens the data directory: the engine then
    creates every missing database empty and the evidence is gone."""
    substrate = data_dir / SUBSTRATE
    if not _present(substrate):
        return ()
    with closing(sqlite3.connect(substrate)) as conn:
        if not _holds_knowledge(conn):
            return ()
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return tuple(
        name
        for name, since in FILES.items()
        if name != SUBSTRATE and version >= since and not _present(data_dir / name)
    )


def check_restore(data_dir: Path) -> tuple[str, ...]:
    """Log a partial restore at error level and return the missing databases."""
    missing = partial_restore(data_dir)
    if missing:
        names = ", ".join(missing)
        logger.error(
            "PARTIAL RESTORE: %s holds knowledge but %s %s missing from %s at "
            "startup. This is not a fresh instance: the data directory was "
            "restored without every database, and the engine is now recreating "
            "%s empty. Whatever was kept there (users and tokens, drafts, "
            "prompt texts and settings, audit history) is absent from this "
            "instance, and settings may have been re-imported from the "
            "environment. Restore every file `mycelium databases` lists and "
            "restart. (Expected once after `mycelium import` of an archive "
            "that omitted this data.)",
            SUBSTRATE,
            names,
            "was" if len(missing) == 1 else "were",
            data_dir,
            names,
        )
    return missing


def _present(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _holds_knowledge(conn: sqlite3.Connection) -> bool:
    tables = {
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('statements', 'entities')"
        )
    }
    return any(
        conn.execute(f"SELECT EXISTS (SELECT 1 FROM {table})").fetchone()[0]
        for table in tables
    )
