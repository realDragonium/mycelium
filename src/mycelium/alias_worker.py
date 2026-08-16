"""Background worker that drains durable link-type alias embedding jobs.

Alias writes enqueue work in the same transaction as the vocabulary change.
This worker embeds those rows on its own thread and SQLite connection, in
chunks. A chunk claims, then embeds OUTSIDE any transaction, then writes: the
embedding round trip must not hold the single writer. Startup unclaims jobs a
previously interrupted worker stranded mid-chunk, so delivery is at-least-once
and re-embedding is idempotent.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import embed, store
from .connect import aliases

logger = logging.getLogger(__name__)

CHUNK = 50

_thread: threading.Thread | None = None
_wake = threading.Event()
_stop = threading.Event()


def drain(conn, *, chunk: int = CHUNK) -> int:
    """Drain the alias embedding queue to empty on `conn`."""
    return aliases.drain_alias_embeddings(conn, embed_text=embed.embed, chunk=chunk)


def _reopen_claimed(conn) -> None:
    """Un-claim every claimed job so a failed chunk is retried, not stranded.

    Safe because this worker is the only claimant and holds no chunk when it
    runs — a drain either finished its chunk or raised out of it.
    """
    try:
        with store.transaction(conn):
            store.reset_claimed_alias_embeddings(conn)
    except Exception:
        logger.exception("could not re-open claimed alias embedding jobs")


def wake() -> None:
    """Nudge the worker to drain now, or the next periodic tick if stopped."""
    _wake.set()


def start(data_dir: Path | str, *, poll_interval: float = 2.0) -> None:
    """Start the daemon worker with its own connection, idempotently."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    db_path = Path(data_dir) / "mycelium.db"
    history_path = Path(data_dir) / "mycelium-history.db"
    _stop.clear()

    def _run() -> None:
        conn = store.connect(db_path, history_path=history_path)
        _reopen_claimed(conn)
        while not _stop.is_set():
            try:
                drain(conn)
            except Exception:  # never let the thread die on one bad drain
                logger.exception("alias embedding drain failed")
                # The failed chunk is already committed as claimed, so without
                # this an unreachable embedder strands its work until restart.
                _reopen_claimed(conn)
            _wake.wait(poll_interval)
            _wake.clear()

    _thread = threading.Thread(target=_run, name="alias-worker", daemon=True)
    _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Signal the worker to exit and join it."""
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout)
        _thread = None
