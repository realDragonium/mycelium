"""Background worker that drains the mention recompute queue.

Statement upserts derive mentions synchronously (the hot path stays
consistent). A name/alias/entity change can instead touch many existing
statements, so it enqueues recompute work into
`store.mention_recompute_queue` and returns immediately. This worker drains
that queue OFF the asyncio event loop — its own OS thread and its own
SQLite connection — in cooperative chunks, committing and releasing the
single writer between chunks so foreground tool-calls interleave (there is
one writer; this is cooperation, not parallelism).

The core (`drain`) is a synchronous function of a connection, so tests call
it directly and deterministically. `start` runs it on a `workers.Worker`
with a periodic wake-up; `wake` nudges it after an enqueue; `stop` joins it.

Durability: each chunk — claim, recompute, delete — is one
`store.transaction(conn)`, so a crash mid-chunk rolls the whole chunk back
and its claimed rows revert to unclaimed for retry. `store.reset_claimed_
recompute` (run on start) additionally un-claims anything an older build may
have stranded — at-least-once, and recompute is idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from . import mentions, request_timing, store, workers

logger = logging.getLogger(__name__)

#: Queue rows claimed (and statements recomputed) per transaction. Small
#: enough that the writer is released frequently; large enough to amortize
#: the per-chunk index build.
CHUNK = 50

_worker: workers.Worker[sqlite3.Connection] | None = None


@request_timing.tracked("background mention recompute")
def drain(conn: sqlite3.Connection, *, chunk: int = CHUNK) -> int:
    """Drain the recompute queue to empty on `conn`, one chunk per
    transaction. Returns the number of statement recomputes performed.

    Each chunk: claim up to `chunk` rows, build the name index once, gather
    the statements to recompute (direct `statement_id` jobs plus, for
    `scan_text` jobs, every statement whose text now contains that name),
    re-derive each, delete the claimed rows — all in one `transaction`.
    Idempotent and safe to call repeatedly."""
    total = 0
    while True:
        with store.transaction(conn):
            rows = store.claim_recompute_batch(conn, chunk)
            if not rows:
                return total

            index = store.build_name_index(conn)
            stmt_ids: set[str] = set()
            scan_texts: list[str] = []
            for r in rows:
                if r["statement_id"] is not None:
                    stmt_ids.add(r["statement_id"])
                elif r["scan_text"] is not None:
                    scan_texts.append(r["scan_text"])

            # Scan jobs: a new/renamed name became matchable — find statements
            # whose text contains it. One pass over the corpus per chunk,
            # coalesced across all scan texts in the chunk.
            if scan_texts:
                for row in store.all_statements_with_text(conn):
                    if any(
                        mentions.text_contains_name(row["text"], st)
                        for st in scan_texts
                    ):
                        stmt_ids.add(row["id"])

            for sid in stmt_ids:
                srow = store.get_statement(conn, sid)
                if srow is None:
                    continue  # deleted between enqueue and drain
                store.derive_mentions(conn, sid, srow["text"], index)
                total += 1

            store.delete_recompute_rows(conn, [r["id"] for r in rows])


def wake() -> None:
    """Nudge the worker to drain now (called after an enqueue). No-op if no
    worker is running — the next periodic tick picks the work up, or a test
    drains explicitly."""
    if _worker is not None:
        _worker.wake()


@contextmanager
def _connection(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """Un-claims any rows stranded by a previous crash before the first drain."""
    with workers.substrate_connection(data_dir) as conn:
        store.reset_claimed_recompute(conn)
        yield conn


def start(data_dir: Path | str, *, poll_interval: float = 2.0) -> None:
    """Start the worker (idempotent)."""
    global _worker
    if _worker is not None and _worker.running():
        return
    _worker = workers.Worker(
        "mention-worker",
        drain,
        interval=poll_interval,
        session=partial(_connection, Path(data_dir)),
    )
    _worker.start()


def stop(timeout: float = 5.0) -> None:
    if _worker is not None:
        _worker.stop(timeout)
