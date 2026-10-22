"""Persist alternative phrasings for canonical statement link types.

The substrate stores only canonical link types; aliases are vocabulary beside
them.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from . import kernel
from .kernel import _now


def normalize_alias(alias: str) -> str:
    """Casefold an alias and collapse its surrounding and internal whitespace."""
    normalized = " ".join(alias.casefold().split())
    if not normalized:
        raise ValueError("alias cannot be empty")
    return normalized


# The canonical surface form of each type and a few unambiguous synonyms.
_ALIAS_SEED: dict[str, tuple[str, ...]] = {
    "contains": (
        "contains",
        "includes",
        "comprises",
        "consists of",
        "is made up of",
        "is part of",
        "belongs to",
        "is owned by",
    ),
    "triggers": ("triggers", "fires", "kicks off", "causes", "results in", "leads to"),
    "establishes": ("establishes", "marks", "sets", "becomes", "transitions to"),
    "enables": (
        "enables",
        "unlocks",
        "allows",
        "permits",
        "makes available",
        "is enabled by",
        "is unlocked by",
    ),
    "requires": ("requires", "needs", "must have", "is required for"),
    "accepts": ("accepts", "optionally", "may include", "may provide"),
    "varies-by": ("varies by", "varies with", "varies per", "differs by", "depends on"),
    "configures": (
        "configures",
        "configured",
        "set",
        "adjusted",
        "customised",
        "customized",
        "toggled",
    ),
    "replaces": (
        "replaces",
        "overrides",
        "takes precedence over",
        "instead of",
        "in place of",
    ),
    "restricts": (
        "restricts",
        "limit",
        "limits",
        "disabled",
        "locked",
        "frozen",
        "suspended",
        "read-only",
        "is limited by",
        "is bounded by",
        "is locked by",
        "is capped by",
        "is disabled by",
        "is frozen by",
        "is suspended by",
    ),
    "proceeds": (
        "proceeds to",
        "then",
        "and then",
        "afterwards",
        "hands off to",
        "is followed by",
        "redirected",
        "routed",
        "forwarded",
        "returned",
    ),
    "fallback-to": ("falls back to", "fallback to", "otherwise", "defaults to"),
    "governed-by": ("is governed by", "according to", "subject to", "as defined by"),
    "composes": (
        "composes",
        "equal",
        "equals",
        "plus",
        "minus",
        "multiplied by",
        "divided by",
        "times",
        "sum of",
        "product of",
        "difference of",
        "difference between",
    ),
    "cases": ("is one of", "either", "any of"),
    "valued-by": ("is derived from", "is computed from", "is determined by"),
    "supersedes": ("supersedes", "deprecates"),
    "teaches": ("teaches", "how to"),
    "performs": ("performs", "carries out"),
    "verifies": ("verifies", "checks", "inspects"),
    "violates": ("violates", "is missing", "is not set"),
    "obtained-by": ("obtained by", "found by"),
    "next": ("next", "followed by"),
    "on-success": ("on success", "if successful"),
    "on-failure": ("on failure", "if it fails"),
    "confirms": ("confirms", "indicates", "means"),
    "refutes": ("refutes", "rules out"),
    "resolves": ("resolves", "fixes", "to fix"),
}

DIRECTIONS = ("forward", "reverse")
Direction = Literal["forward", "reverse"]

#: Aliases whose English reads the edge from the far side: "A is required for
#: B" means B requires A.
_REVERSE_SEED: frozenset[tuple[str, str]] = frozenset(
    {
        ("requires", "is required for"),
        ("cases", "is one of"),
        ("contains", "is part of"),
        ("contains", "belongs to"),
        ("contains", "is owned by"),
        ("restricts", "is limited by"),
        ("restricts", "is bounded by"),
        ("restricts", "is locked by"),
        ("restricts", "is capped by"),
        ("restricts", "is disabled by"),
        ("restricts", "is frozen by"),
        ("restricts", "is suspended by"),
        ("enables", "is enabled by"),
        ("enables", "is unlocked by"),
    }
)


def _validate_direction(direction: str) -> str:
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}")
    return direction


def seed_rows() -> list[tuple[str, str, str]]:
    """Flatten the seed into (link_type, alias, direction) rows.

    The single source for what a fresh vocabulary contains; seeding, the v9
    migration, and tests all read the same rows.
    """
    return [
        (
            link_type,
            alias,
            "reverse" if (link_type, alias) in _REVERSE_SEED else "forward",
        )
        for link_type, aliases in _ALIAS_SEED.items()
        for alias in aliases
    ]


def seed_link_type_aliases(conn: sqlite3.Connection) -> int:
    """Seed aliases when the alias table is empty."""
    if conn.execute("SELECT 1 FROM link_type_aliases LIMIT 1").fetchone() is not None:
        return 0

    rows = seed_rows()
    now = _now()
    actor = kernel.get_actor()
    conn.executemany(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, direction, created_at, created_by) "
        "VALUES (?, ?, 'seed', ?, ?, ?)",
        (
            (link_type, alias, direction, now, actor)
            for link_type, alias, direction in rows
        ),
    )
    return len(rows)


def list_link_type_aliases(
    conn: sqlite3.Connection, link_type: str | None = None
) -> list[sqlite3.Row]:
    """List aliases in stable type and alias order."""
    sql = (
        "SELECT link_type, alias, provenance, score, direction, created_at, "
        "created_by FROM link_type_aliases"
    )
    params: tuple[str, ...] = ()
    if link_type is not None:
        sql += " WHERE link_type = ?"
        params = (link_type,)
    return conn.execute(sql + " ORDER BY link_type, alias", params).fetchall()


def upsert_link_type_alias(
    conn: sqlite3.Connection,
    link_type: str,
    alias: str,
    *,
    provenance: str = "curator",
    score: float | None = None,
    direction: str = "forward",
) -> bool:
    """Create an alias or update its provenance, score, and direction."""
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    _validate_direction(direction)
    alias = normalize_alias(alias)
    created = (
        conn.execute(
            "SELECT 1 FROM link_type_aliases WHERE link_type = ? AND alias = ?",
            (link_type, alias),
        ).fetchone()
        is None
    )
    conn.execute(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, score, direction, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(link_type, alias) DO UPDATE SET "
        "provenance = excluded.provenance, score = excluded.score, "
        "direction = excluded.direction",
        (link_type, alias, provenance, score, direction, _now(), kernel.get_actor()),
    )
    return created


def delete_link_type_alias(
    conn: sqlite3.Connection, link_type: str, alias: str
) -> bool:
    """Delete an alias."""
    alias = normalize_alias(alias)
    cursor = conn.execute(
        "DELETE FROM link_type_aliases WHERE link_type = ? AND alias = ?",
        (link_type, alias),
    )
    return cursor.rowcount > 0
