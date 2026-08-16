"""Persist the instance's admissible statement-link types by kind pair.

The seeded matrix is configuration: once it has rows, migrations leave curator
edits untouched.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ..link_rules import derive_kind_link_matrix
from . import kernel
from .glossary import (
    list_statement_kind_glossary,
    list_statement_link_type_glossary,
)
from .kernel import _now
from .links import count_statements_by_kind_all, list_link_types


def _live_link_types(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(list_link_types(conn)) | frozenset(
        row["link_type"] for row in list_statement_link_type_glossary(conn)
    )


def seed_kind_link_matrix(conn: sqlite3.Connection) -> int:
    """Seed an empty matrix from the live kinds, link types, and direction rules.

    Link types added later are not admissible for known kind pairs until a row is
    added. The allow-all fallback covers unknown kinds, not unknown link types.
    """
    if conn.execute("SELECT 1 FROM kind_link_matrix LIMIT 1").fetchone() is not None:
        return 0

    kinds = frozenset(
        row["kind"] for row in list_statement_kind_glossary(conn)
    ) | frozenset(count_statements_by_kind_all(conn))
    rows = derive_kind_link_matrix(kinds, _live_link_types(conn))
    now = _now()
    actor = kernel.get_actor()
    conn.executemany(
        "INSERT INTO kind_link_matrix "
        "(from_kind, to_kind, link_type, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            (from_kind, to_kind, link_type, now, actor)
            for from_kind, to_kind, link_type in sorted(rows)
        ),
    )
    return len(rows)


def matrix_kinds(conn: sqlite3.Connection) -> frozenset[str]:
    """Return every kind represented on either side of the matrix."""
    rows = conn.execute(
        "SELECT from_kind AS kind FROM kind_link_matrix "
        "UNION SELECT to_kind AS kind FROM kind_link_matrix"
    ).fetchall()
    return frozenset(row["kind"] for row in rows)


def admissible_link_types(
    conn: sqlite3.Connection, from_kind: str, to_kind: str
) -> frozenset[str]:
    """Return the configured link types for a kind pair."""
    # A kind counts as configured only while some row still mentions it, so a
    # kind added to the ontology after seeding falls back to the whole
    # vocabulary rather than to silence. The cost is the mirror case: empty
    # every pair touching a kind and it reverts to the fallback too.
    known_kinds = matrix_kinds(conn)
    if from_kind not in known_kinds or to_kind not in known_kinds:
        return _live_link_types(conn)
    rows = conn.execute(
        "SELECT link_type FROM kind_link_matrix WHERE from_kind = ? AND to_kind = ?",
        (from_kind, to_kind),
    ).fetchall()
    return frozenset(row["link_type"] for row in rows)


def list_kind_link_matrix(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """List the configured matrix rows in stable kind and link-type order."""
    return conn.execute(
        "SELECT from_kind, to_kind, link_type, created_at, created_by "
        "FROM kind_link_matrix ORDER BY from_kind, to_kind, link_type"
    ).fetchall()


def set_admissible(
    conn: sqlite3.Connection,
    from_kind: str,
    to_kind: str,
    link_types: Iterable[str],
) -> None:
    """Replace a kind pair's configured link types."""
    normalized = frozenset(link_types)
    conn.execute(
        "DELETE FROM kind_link_matrix WHERE from_kind = ? AND to_kind = ?",
        (from_kind, to_kind),
    )
    now = _now()
    actor = kernel.get_actor()
    conn.executemany(
        "INSERT INTO kind_link_matrix "
        "(from_kind, to_kind, link_type, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            (from_kind, to_kind, link_type, now, actor)
            for link_type in sorted(normalized)
        ),
    )
