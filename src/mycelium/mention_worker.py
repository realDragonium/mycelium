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
it directly and deterministically. `start` wraps it in a daemon thread with
a periodic wake-up; `wake` nudges it after an enqueue; `stop` joins it.

Durability: claiming a batch stamps `claimed_at` and commits before
processing, so a crash mid-drain strands at most one chunk as claimed-
but-undeleted. `store.reset_claimed_recompute` (run on start) un-claims
those so they are retried — at-least-once, and recompute is idempotent.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import mentions, store

logger = logging.getLogger(__name__)

#: Queue rows claimed (and statements recomputed) per transaction. Small
#: enough that the writer is released frequently; large enough to amortize
#: the per-chunk index build.
CHUNK = 50

_thread: threading.Thread | None = None
_wake = threading.Event()
_stop = threading.Event()


def drain(conn, *, chunk: int = CHUNK) -> int:
    """Drain the recompute queue to empty on `conn`, one chunk per
    transaction. Returns the number of statement recomputes performed.

    Each chunk: claim up to `chunk` rows, build the name index once, gather
    the statements to recompute (direct `statement_id` jobs plus, for
    `scan_text` jobs, every statement whose text now contains that name),
    re-derive each, delete the claimed rows, commit. Idempotent and safe to
    call repeatedly."""
    total = 0
    while True:
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
                    mentions.text_contains_name(row["text"], st) for st in scan_texts
                ):
                    stmt_ids.add(row["id"])

        for sid in stmt_ids:
            srow = store.get_statement(conn, sid)
            if srow is None:
                continue  # deleted between enqueue and drain
            store.derive_mentions(conn, sid, srow["text"], index, commit=False)
            total += 1

        store.delete_recompute_rows(conn, [r["id"] for r in rows], commit=False)
        conn.commit()


def wake() -> None:
    """Nudge the worker to drain now (called after an enqueue). No-op if no
    worker thread is running — the next periodic tick picks the work up, or
    a test drains explicitly."""
    _wake.set()


def start(data_dir: Path | str, *, poll_interval: float = 2.0) -> None:
    """Start the daemon worker thread (idempotent). Opens its OWN
    connection so blocking SQLite calls never touch the event loop's
    connection or thread. Un-claims any rows stranded by a previous crash
    before looping."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    db_path = Path(data_dir) / "mycelium.db"
    history_path = Path(data_dir) / "mycelium-history.db"
    _stop.clear()

    def _run() -> None:
        conn = store.connect(db_path, history_path=history_path)
        store.reset_claimed_recompute(conn)
        while not _stop.is_set():
            try:
                drain(conn)
            except Exception:  # never let the thread die on one bad drain
                logger.exception("mention recompute drain failed")
            _wake.wait(poll_interval)
            _wake.clear()

    _thread = threading.Thread(target=_run, name="mention-worker", daemon=True)
    _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Signal the worker to exit and join it. Mostly for clean test
    teardown; in production the daemon thread dies with the process."""
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout)
        _thread = None
