"""Background retry worker for statements and names pending embeddings.

A failing batch is halved on each later pass until the row that fails it
is alone. A row failing alone is set aside so the rest embed past it, and
once others embed it is tried alone again: only a failure then, while the
provider works, counts in `automation_stops`. Past `embedding_retries` the
row is passed over until its text changes or an admin retries it. A
provider outage fails every row alike and so counts against none.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import automation_stops, embed, store
from .server import indexes

logger = logging.getLogger(__name__)

BATCH = 256

_thread: threading.Thread | None = None
_stop = threading.Event()


@dataclass
class Isolation:
    """What one worker learned of failing rows since it started."""

    batch: int = BATCH
    #: Rows that failed alone, by key.
    suspects: dict[str, indexes.Pending] = field(default_factory=dict)


def run_pass(state: Isolation, stop: threading.Event | None = None) -> int:
    """Embed what is pending, isolating rows that fail. Returns how many
    rows were embedded."""
    total = 0
    while stop is None or not stop.is_set():
        requested = state.batch
        rows = indexes.pending(requested, state.suspects)
        if not rows:
            break
        try:
            total += indexes.embed_pending(rows)
        except embed.EmbeddingError:
            if len(rows) == 1:
                state.suspects[rows[0].key] = rows[0]
            else:
                state.batch = max(1, len(rows) // 2)
            # The provider refuses calls for a while after a failure.
            return total
        state.batch = BATCH
        if len(rows) < requested:
            break
    if total:
        _recheck(state)
    return total


def _recheck(state: Isolation) -> None:
    """Try each set-aside row alone while the provider works, counting a
    failure, and stop at the first: the provider then refuses for a while."""
    for key, row in list(state.suspects.items()):
        try:
            indexes.embed_pending([row])
        except embed.EmbeddingError as exc:
            reason = f"Embedding the {row.kind} failed while others embedded: {exc}"
            conn = store.substrate_connection()
            with store.transaction(conn):
                stopped = automation_stops.fail(
                    conn,
                    "embedding",
                    key,
                    row.text,
                    reason[:500],
                    retries=automation_stops.limits().embedding_retries,
                    now=datetime.now(UTC),
                )
            if stopped:
                del state.suspects[key]
            return
        del state.suspects[key]


def start(*, poll_interval: float = 30.0) -> None:
    """Start the daemon worker thread, if it is not already running."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()

    def _run() -> None:
        state = Isolation()
        while not _stop.is_set():
            try:
                run_pass(state, _stop)
            except Exception:
                logger.exception("pending embedding pass failed")
            _stop.wait(poll_interval)

    _thread = threading.Thread(target=_run, name="embedding-worker", daemon=True)
    _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Signal the worker to exit and wait briefly for it."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout)
        if _thread.is_alive():
            logger.warning("embedding worker did not stop within %.1fs", timeout)
            return
        _thread = None
