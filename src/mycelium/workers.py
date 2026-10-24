"""Background workers: one daemon thread per periodic, wakeable job.

A `Worker` owns the thread, its lifecycle and error reporting; the feature
module keeps what a pass does, its eligibility, claims and retry policy. A
worker's `session` opens what its passes share (a connection of its own,
opened on the worker thread) and closes it when the worker stops.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from pathlib import Path
from typing import Generic, TypeVar

from . import store

logger = logging.getLogger(__name__)

S = TypeVar("S")


@contextmanager
def no_session() -> Iterator[None]:
    yield


@contextmanager
def substrate_connection(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """A substrate connection of the worker's own, so its blocking SQLite
    calls never share a request thread's connection."""
    with closing(
        store.connect(
            data_dir / "mycelium.db", history_path=data_dir / "mycelium-history.db"
        )
    ) as conn:
        yield conn


class Worker(Generic[S]):
    """Runs `run_pass` every `interval` seconds and whenever woken.

    With `delay_first`, the first pass waits one interval after start. A pass
    that raises is logged and the next one runs on schedule.
    """

    def __init__(
        self,
        name: str,
        run_pass: Callable[[S], object],
        *,
        interval: float,
        session: Callable[[], AbstractContextManager[S]],
        delay_first: bool = False,
    ) -> None:
        self.name = name
        self.interval = interval
        self._run_pass = run_pass
        self._session = session
        self._delay_first = delay_first
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()

    def start(self) -> None:
        """Start the thread unless one is still running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Run a pass now. A no-op until the worker is started."""
        self._wake.set()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the thread to finish and wait for it.

        Keeps the reference when the wait times out, so `start` refuses a
        second thread on the same work while the first is still finishing.
        """
        self._stop.set()
        self._wake.set()
        if self._thread is None:
            return
        self._thread.join(timeout)
        if self._thread.is_alive():
            logger.warning("%s did not stop within %.1fs", self.name, timeout)
            return
        self._thread = None

    def _loop(self) -> None:
        try:
            with self._session() as state:
                if self._delay_first:
                    self._pause()
                while not self._stop.is_set():
                    try:
                        self._run_pass(state)
                    except Exception:  # never let the thread die on one bad pass
                        logger.exception("%s pass failed", self.name)
                    self._pause()
        except Exception:
            logger.exception("%s stopped", self.name)

    def _pause(self) -> None:
        self._wake.wait(self.interval)
        self._wake.clear()
