"""Persist cue-layer surface forms for canonical statement link types.

The substrate stores only canonical link types. Seeded aliases are queued for
embedding instead of embedded inline because embedding is I/O and seeding runs
inside `store.migrate`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from . import kernel
from .kernel import _now


def normalize_alias(alias: str) -> str:
    """Casefold an alias and collapse its surrounding and internal whitespace."""
    normalized = " ".join(alias.casefold().split())
    if not normalized:
        raise ValueError("alias cannot be empty")
    return normalized


# Keep the canonical surface form of each type, the exact cue phrasings the
# shipped lexical patterns accept today, and a few unambiguous synonyms.
# Two omissions are deliberate, not gaps. Conditional subordinators (`if`,
# `when`, `unless`, …) and the coordinator `and` are absent: their cuts run
# right→left or express no relation, and the segmenter links left→right. And
# the vocabulary of a deliberately UNSHIPPED pattern is absent (`blocks`,
# `prevents`, `suppresses`, `capped`, `bounded` for `restricts`; `combines`,
# `aggregates` for `composes`) — two shipped templates take a bare cue slot, so
# seeding those words would ship the phrasings the hit-rate report rejected.
_ALIAS_SEED: dict[str, tuple[str, ...]] = {
    "contains": ("contains", "includes", "comprises", "consists of", "is made up of"),
    "triggers": ("triggers", "fires", "kicks off", "causes", "results in", "leads to"),
    "establishes": ("establishes", "marks", "sets", "becomes", "transitions to"),
    "enables": ("enables", "unlocks", "allows", "permits", "makes available"),
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


def seed_link_type_aliases(conn: sqlite3.Connection) -> int:
    """Seed aliases and embedding jobs when the alias table is empty."""
    if conn.execute("SELECT 1 FROM link_type_aliases LIMIT 1").fetchone() is not None:
        return 0

    rows = [
        (link_type, alias)
        for link_type, aliases in _ALIAS_SEED.items()
        for alias in aliases
    ]
    now = _now()
    actor = kernel.get_actor()
    conn.executemany(
        "INSERT INTO link_type_aliases "
        "(link_type, alias, provenance, created_at, created_by) "
        "VALUES (?, ?, 'seed', ?, ?)",
        ((link_type, alias, now, actor) for link_type, alias in rows),
    )
    conn.executemany(
        "INSERT INTO link_type_alias_embed_queue "
        "(link_type, alias, enqueued_at) VALUES (?, ?, ?)",
        ((link_type, alias, now) for link_type, alias in rows),
    )
    return len(rows)


def list_link_type_aliases(
    conn: sqlite3.Connection, link_type: str | None = None
) -> list[sqlite3.Row]:
    """List aliases and embedding status in stable type and alias order."""
    sql = (
        "SELECT link_type, alias, provenance, score, created_at, created_by, "
        "embedding IS NOT NULL AS embedded FROM link_type_aliases"
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
) -> bool:
    """Create an alias or update its provenance and score."""
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
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
        "(link_type, alias, provenance, score, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(link_type, alias) DO UPDATE SET "
        "provenance = excluded.provenance, score = excluded.score",
        (link_type, alias, provenance, score, _now(), kernel.get_actor()),
    )
    # An existing alias has unchanged carrier text, so its stored vector stands.
    if created:
        enqueue_alias_embedding(conn, link_type, alias)
    return created


def delete_link_type_alias(
    conn: sqlite3.Connection, link_type: str, alias: str
) -> bool:
    """Delete an alias and its unclaimed embedding jobs."""
    alias = normalize_alias(alias)
    cursor = conn.execute(
        "DELETE FROM link_type_aliases WHERE link_type = ? AND alias = ?",
        (link_type, alias),
    )
    conn.execute(
        "DELETE FROM link_type_alias_embed_queue "
        "WHERE link_type = ? AND alias = ? AND claimed_at IS NULL",
        (link_type, alias),
    )
    return cursor.rowcount > 0


def link_type_alias_exists(
    conn: sqlite3.Connection, link_type: str, alias: str
) -> bool:
    """Report whether an alias row still exists for this exact pair."""
    return (
        conn.execute(
            "SELECT 1 FROM link_type_aliases WHERE link_type = ? AND alias = ?",
            (link_type, alias),
        ).fetchone()
        is not None
    )


def alias_lookup(conn: sqlite3.Connection) -> dict[str, frozenset[str]]:
    """Map each alias to every canonical link type that carries it."""
    lookup: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT link_type, alias FROM link_type_aliases ORDER BY alias, link_type"
    ):
        lookup.setdefault(row["alias"], set()).add(row["link_type"])
    return {alias: frozenset(link_types) for alias, link_types in lookup.items()}


def aliases_by_type(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Group aliases by link type, longest first so regex alternatives win."""
    grouped: dict[str, list[str]] = {}
    for row in conn.execute("SELECT link_type, alias FROM link_type_aliases"):
        grouped.setdefault(row["link_type"], []).append(row["alias"])
    return {
        link_type: tuple(sorted(aliases, key=lambda alias: (-len(alias), alias)))
        for link_type, aliases in grouped.items()
    }


def set_alias_embedding(
    conn: sqlite3.Connection, link_type: str, alias: str, embedding: bytes
) -> None:
    """Store an alias embedding blob."""
    conn.execute(
        "UPDATE link_type_aliases SET embedding = ? WHERE link_type = ? AND alias = ?",
        (embedding, link_type, alias),
    )


def alias_vectors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """List aliases carrying embeddings in stable type and alias order."""
    return conn.execute(
        "SELECT link_type, alias, embedding FROM link_type_aliases "
        "WHERE embedding IS NOT NULL ORDER BY link_type, alias"
    ).fetchall()


def enqueue_alias_embedding(
    conn: sqlite3.Connection, link_type: str, alias: str
) -> None:
    """Enqueue an alias for background embedding."""
    conn.execute(
        "INSERT INTO link_type_alias_embed_queue "
        "(link_type, alias, enqueued_at) VALUES (?, ?, ?)",
        (link_type, alias, _now()),
    )


def claim_alias_embeddings(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Claim and return up to `limit` open embedding jobs."""
    rows = conn.execute(
        "SELECT id, link_type, alias FROM link_type_alias_embed_queue "
        "WHERE claimed_at IS NULL ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    if rows:
        now = _now()
        conn.executemany(
            "UPDATE link_type_alias_embed_queue SET claimed_at = ? WHERE id = ?",
            [(now, row["id"]) for row in rows],
        )
    return rows


def finish_alias_embeddings(conn: sqlite3.Connection, ids: Iterable[int]) -> None:
    """Delete completed embedding jobs."""
    ids = list(ids)
    if ids:
        conn.executemany(
            "DELETE FROM link_type_alias_embed_queue WHERE id = ?",
            [(row_id,) for row_id in ids],
        )


def reset_claimed_alias_embeddings(conn: sqlite3.Connection) -> None:
    """Unclaim embedding jobs stranded by an interrupted worker."""
    conn.execute(
        "UPDATE link_type_alias_embed_queue SET claimed_at = NULL "
        "WHERE claimed_at IS NOT NULL"
    )


def count_open_alias_embeddings(conn: sqlite3.Connection) -> int:
    """Count unclaimed alias embedding jobs."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM link_type_alias_embed_queue WHERE claimed_at IS NULL"
        ).fetchone()[0]
    )
