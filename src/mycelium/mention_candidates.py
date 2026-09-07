"""Bounded, read-only alias discovery without asserting ambiguous matches."""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel

from . import mentions, store

SCAN_LIMIT = 2000


class MatchedName(BaseModel):
    name_id: str
    text: str


class Candidate(BaseModel):
    statement_id: str
    text: str
    kind: str
    names: list[MatchedName]
    match: Literal["derived", "approved", "possible"]


class CandidatePage(BaseModel):
    matches: list[Candidate]
    next_after: int
    has_more: bool
    scanned: int


def find_candidates(
    conn: sqlite3.Connection, entity_id: str, *, after: int = 0, limit: int = 50
) -> CandidatePage:
    if after < 0 or not 1 <= limit <= 200:
        raise ValueError("after must be nonnegative and limit must be 1..200")
    if store.get_entity_by_id(conn, entity_id) is None:
        raise ValueError("entity does not exist")
    index = store.build_name_index(conn)
    rows = conn.execute(
        "SELECT rowid AS cursor, id, text, kind FROM statements "
        "WHERE rowid > ? ORDER BY rowid LIMIT ?",
        (after, SCAN_LIMIT + 1),
    ).fetchall()
    approvals = {
        (row["statement_id"], row["name_id"])
        for row in conn.execute(
            "SELECT p.statement_id, p.name_id FROM pending_mentions p "
            "JOIN names n ON n.id = p.name_id "
            "JOIN statements s ON s.id = p.statement_id "
            "WHERE n.entity_id = ? AND p.approved_at IS NOT NULL "
            "AND s.rowid > ? AND s.rowid <= ?",
            (
                entity_id,
                after,
                rows[min(len(rows), SCAN_LIMIT) - 1]["cursor"] if rows else after,
            ),
        )
    }
    found: list[Candidate] = []
    cursor = after
    scanned = 0
    for row in rows[:SCAN_LIMIT]:
        cursor = row["cursor"]
        scanned += 1
        result = mentions.match_text(row["text"], index)
        definite = [m for m in result.mentions if m.entity_id == entity_id]
        possible = [m for m in result.suspects if m.entity_id == entity_id]
        if not definite and not possible:
            continue
        approved = any((row["id"], m.name_id) in approvals for m in possible)
        found.append(
            Candidate(
                statement_id=row["id"],
                text=row["text"],
                kind=row["kind"],
                names=[
                    MatchedName(name_id=m.name_id, text=m.name)
                    for m in [*definite, *possible]
                ],
                match="derived" if definite else "approved" if approved else "possible",
            )
        )
        if len(found) == limit:
            break
    return CandidatePage(
        matches=found, next_after=cursor, has_more=scanned < len(rows), scanned=scanned
    )
