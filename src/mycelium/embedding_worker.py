"""Background retry worker for statements and names pending embeddings."""

from __future__ import annotations

import logging
import threading

from .server import indexes

logger = logging.getLogger(__name__)

BATCH = 256

_thread: threading.Thread | None = None
_stop = threading.Event()


def start(*, poll_interval: float = 30.0) -> None:
    """Start the daemon worker thread, if it is not already running."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()

    def _run() -> None:
        while not _stop.is_set():
            try:
                while not _stop.is_set():
                    embedded = indexes.reembed_pending(BATCH)
                    if embedded < BATCH:
                        break
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
