"""Statement mentions, derived matches, recompute queue, pending review."""

from __future__ import annotations

import sqlite3
from typing import Iterable

from .. import mentions as mention_index
from . import kernel
from .kernel import _now, _record
from .statements import list_all_names

# --- mentions ---------------------------------------------------------------


def replace_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> None:
    conn.execute(
        "DELETE FROM statement_mentions WHERE statement_id = ?", (statement_id,)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        [(statement_id, nid) for nid in name_ids],
    )


def get_mentions(conn: sqlite3.Connection, statement_id: str) -> list[sqlite3.Row]:
    """Returns rows with name_id, name (text), and entity_id."""
    return conn.execute(
        "SELECT n.id AS name_id, n.text AS name, n.entity_id "
        "FROM statement_mentions bm "
        "JOIN names n ON n.id = bm.name_id "
        "WHERE bm.statement_id = ?",
        (statement_id,),
    ).fetchall()


def add_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> int:
    """Append mentions idempotently. Returns rows actually inserted —
    pre-existing (statement_id, name_id) pairs are silently skipped."""
    if not name_ids:
        return 0
    cur = conn.executemany(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        [(statement_id, nid) for nid in name_ids],
    )
    return cur.rowcount


def remove_mentions(
    conn: sqlite3.Connection, statement_id: str, name_ids: list[str]
) -> int:
    """Remove the listed mention rows. Missing rows are silently skipped.
    Returns rows actually deleted."""
    if not name_ids:
        return 0
    placeholders = ",".join("?" * len(name_ids))
    cur = conn.execute(
        f"DELETE FROM statement_mentions "
        f"WHERE statement_id = ? AND name_id IN ({placeholders})",
        [statement_id, *name_ids],
    )
    return cur.rowcount


# --- derived mentions -------------------------------------------------------
#
# Mentions are not asserted; they are derived from statement text by the
# pure matcher in `mycelium.mentions`. The functions below are the only
# writers of `statement_mentions` and `pending_mentions` in normal
# operation — the sync statement-upsert path, the async recompute worker,
# and the one-shot backfill all funnel through `derive_mentions`.


def build_name_index(
    conn: sqlite3.Connection,
) -> dict[str, list[mention_index.IndexedName]]:
    """Compile every name/alias into a matcher index. Built once per
    statement-write, per worker drain, or per backfill — never cached on
    the connection, so it always reflects the latest names."""
    rows = list_all_names(conn)
    return mention_index.build_index((r["id"], r["entity_id"], r["text"]) for r in rows)


def _sync_pending(
    conn: sqlite3.Connection,
    statement_id: str,
    suspect_name_ids: list[str],
    keep_name_ids: list[str],
) -> None:
    """Re-queue a statement's suspect occurrences.

    Approved occurrences in `keep_name_ids` are left untouched — their
    decision and the materialized mention persist, because a human approval
    is asserted truth, not a re-derivable guess. Every other pending row for
    the statement is dropped, and each still-matching suspect that isn't
    already approved is re-inserted as a fresh OPEN row. So open and rejected
    occurrences carry no memory — a suspect that still matches is always
    re-surfaced for review (the 'keep it dumb' rule); only explicit approvals
    survive a recompute."""
    keep = set(keep_name_ids)
    for r in conn.execute(
        "SELECT name_id FROM pending_mentions WHERE statement_id = ?",
        (statement_id,),
    ).fetchall():
        if r["name_id"] not in keep:
            conn.execute(
                "DELETE FROM pending_mentions WHERE statement_id = ? AND name_id = ?",
                (statement_id, r["name_id"]),
            )
    now = _now()
    for nid in suspect_name_ids:
        if nid in keep:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO pending_mentions "
            "(statement_id, name_id, created_at) VALUES (?, ?, ?)",
            (statement_id, nid, now),
        )


def derive_mentions(
    conn: sqlite3.Connection,
    statement_id: str,
    text: str,
    index: dict[str, list[mention_index.IndexedName]],
) -> mention_index.MatchResult:
    """Run the matcher over `text` and materialize the result.

    Distinctive matches become `statement_mentions` rows. Suspect matches go
    to the `pending_mentions` review queue. A previously-APPROVED suspect
    whose name still matches the text is preserved — its decision stands and
    its materialized mention is re-asserted — so an unrelated recompute (a
    name change elsewhere, a typo fix) never silently destroys a human's
    review work. Open and rejected suspects carry no memory and are re-queued
    fresh (the 'keep it dumb' rule). Returns the raw `MatchResult`."""
    result = mention_index.match_text(text, index)
    auto_ids = [m.name_id for m in result.mentions]
    suspect_ids = [s.name_id for s in result.suspects]
    approved = {
        r["name_id"]
        for r in conn.execute(
            "SELECT name_id FROM pending_mentions "
            "WHERE statement_id = ? AND approved_at IS NOT NULL",
            (statement_id,),
        ).fetchall()
    }
    keep_approved = [nid for nid in suspect_ids if nid in approved]
    replace_mentions(conn, statement_id, auto_ids + keep_approved)
    _sync_pending(conn, statement_id, suspect_ids, keep_approved)
    return result


def clear_derived_for_statement(conn: sqlite3.Connection, statement_id: str) -> int:
    """Remove a statement's derived rows so the statement can be deleted:
    its `statement_mentions`, its `pending_mentions`, and any queued
    recompute jobs (all FK statements(id) under RESTRICT). Returns the
    number of mention rows removed."""
    removed = conn.execute(
        "DELETE FROM statement_mentions WHERE statement_id = ?", (statement_id,)
    ).rowcount
    conn.execute("DELETE FROM pending_mentions WHERE statement_id = ?", (statement_id,))
    conn.execute(
        "DELETE FROM mention_recompute_queue WHERE statement_id = ?", (statement_id,)
    )
    return removed


def statements_mentioning_name(conn: sqlite3.Connection, name_id: str) -> list[str]:
    """All statement ids that currently mention `name_id` (via the reverse
    index). Used to find recompute targets when a name's binding changes."""
    return [
        r["statement_id"]
        for r in conn.execute(
            "SELECT statement_id FROM statement_mentions WHERE name_id = ?",
            (name_id,),
        ).fetchall()
    ]


def all_statement_ids(conn: sqlite3.Connection) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM statements").fetchall()]


def all_statements_with_text(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """(id, text) for every statement. Used by the recompute worker's scan
    pass and by the backfill."""
    return conn.execute("SELECT id, text FROM statements").fetchall()


# --- mention recompute queue (drained by mention_worker) --------------------


def enqueue_recompute_statements(
    conn: sqlite3.Connection, statement_ids: Iterable[str]
) -> None:
    """Mark statements dirty: their derivable mentions may have changed
    because a name they reference moved, was deleted, or its representative
    shifted. Idempotent in effect — duplicate rows just recompute twice."""
    rows = [(sid, _now()) for sid in dict.fromkeys(statement_ids)]
    if rows:
        conn.executemany(
            "INSERT INTO mention_recompute_queue (statement_id, enqueued_at) "
            "VALUES (?, ?)",
            rows,
        )


def enqueue_recompute_scan(conn: sqlite3.Connection, scan_text: str) -> None:
    """Mark that a new/renamed name text became matchable; the worker scans
    statement text for this token-sequence and recomputes every statement
    that now contains it."""
    conn.execute(
        "INSERT INTO mention_recompute_queue (scan_text, enqueued_at) VALUES (?, ?)",
        (scan_text, _now()),
    )


def claim_recompute_batch(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Claim up to `limit` unclaimed queue rows (stamp claimed_at) and
    return them. Claiming and reading happen in one transaction so two
    workers (or a restart mid-drain) can't double-process — though there is
    only ever one worker."""
    rows = conn.execute(
        "SELECT id, statement_id, scan_text FROM mention_recompute_queue "
        "WHERE claimed_at IS NULL ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    if rows:
        now = _now()
        conn.executemany(
            "UPDATE mention_recompute_queue SET claimed_at = ? WHERE id = ?",
            [(now, r["id"]) for r in rows],
        )
    return rows


def delete_recompute_rows(conn: sqlite3.Connection, ids: Iterable[int]) -> None:
    ids = list(ids)
    if ids:
        conn.executemany(
            "DELETE FROM mention_recompute_queue WHERE id = ?",
            [(i,) for i in ids],
        )


def reset_claimed_recompute(conn: sqlite3.Connection) -> None:
    """Un-claim every claimed-but-undeleted row. Run once on worker startup
    so a drain interrupted by a crash/restart is retried rather than
    stranded."""
    conn.execute(
        "UPDATE mention_recompute_queue SET claimed_at = NULL WHERE claimed_at IS NOT NULL"
    )


def count_open_recompute(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM mention_recompute_queue WHERE claimed_at IS NULL"
        ).fetchone()[0]
    )


# --- pending mentions (suspect-match review queue) --------------------------
#
# Never exposed through MCP. The website reviews these; approving inserts
# the real statement_mentions row.


def list_pending_mentions(
    conn: sqlite3.Connection,
    status: str = "open",
    limit: int = 100,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Hydrated suspect occurrences for review. `status` is open /
    approved / rejected / all. Each row carries the statement text and the
    suspect name so a reviewer can judge the occurrence in context."""
    where = {
        "open": "WHERE p.approved_at IS NULL AND p.rejected_at IS NULL",
        "approved": "WHERE p.approved_at IS NOT NULL",
        "rejected": "WHERE p.rejected_at IS NOT NULL",
        "all": "",
    }.get(status, "WHERE p.approved_at IS NULL AND p.rejected_at IS NULL")
    return conn.execute(
        f"""
        SELECT p.id AS id, p.statement_id, p.name_id, p.created_at,
               p.approved_at, p.rejected_at,
               n.text AS name, n.entity_id AS entity_id,
               s.text AS statement_text, s.kind AS statement_kind
        FROM pending_mentions p
        JOIN names n      ON n.id = p.name_id
        JOIN statements s ON s.id = p.statement_id
        {where}
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()


def get_pending_mention(
    conn: sqlite3.Connection, pending_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, statement_id, name_id, approved_at, rejected_at "
        "FROM pending_mentions WHERE id = ?",
        (pending_id,),
    ).fetchone()


def approve_pending_mention(conn: sqlite3.Connection, pending_id: int) -> bool:
    """Approve a suspect occurrence: stamp approved_at and materialize the
    real mention. No-op (returns False) if already resolved or unknown."""
    row = get_pending_mention(conn, pending_id)
    if row is None or row["approved_at"] is not None or row["rejected_at"] is not None:
        return False
    conn.execute(
        "UPDATE pending_mentions SET approved_at = ?, approved_by = ? WHERE id = ?",
        (_now(), kernel._actor, pending_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO statement_mentions (statement_id, name_id) VALUES (?, ?)",
        (row["statement_id"], row["name_id"]),
    )
    _record(
        conn,
        "link",
        "statement_mention",
        f"{row['statement_id']}|{row['name_id']}",
        context={"reason": "approve_pending_mention", "pending_id": pending_id},
    )
    return True


def reject_pending_mention(conn: sqlite3.Connection, pending_id: int) -> bool:
    """Reject a suspect occurrence: stamp rejected_at, write no mention.
    No-op (returns False) if already resolved or unknown."""
    row = get_pending_mention(conn, pending_id)
    if row is None or row["approved_at"] is not None or row["rejected_at"] is not None:
        return False
    conn.execute(
        "UPDATE pending_mentions SET rejected_at = ?, rejected_by = ? WHERE id = ?",
        (_now(), kernel._actor, pending_id),
    )
    return True


def count_pending_mentions(conn: sqlite3.Connection, status: str = "open") -> int:
    where = {
        "open": "WHERE approved_at IS NULL AND rejected_at IS NULL",
        "approved": "WHERE approved_at IS NOT NULL",
        "rejected": "WHERE rejected_at IS NOT NULL",
        "all": "",
    }.get(status, "WHERE approved_at IS NULL AND rejected_at IS NULL")
    return int(
        conn.execute(f"SELECT COUNT(*) FROM pending_mentions {where}").fetchone()[0]
    )
