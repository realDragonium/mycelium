"""A per-thread SQLite connection provider.

Each thread gets its OWN connection to a database file, opened lazily and
reused for the thread's life. On WAL every connection reads a consistent
last-committed snapshot, so a reader on one thread never observes another
request's in-flight (uncommitted) writes.

One provider owns one database. `configure()` records the connection config
and bumps an epoch; a thread caches `(epoch, conn)` and lazily reopens when
the epoch moves (a reconfigure — e.g. a test pointing at a fresh temp DB),
without any other thread having to reach in. `use()` pins an explicit
connection on the current thread, for `:memory:` DBs and unit tests whose
single connection cannot be reopened per thread.

The provider is deliberately generic: what `connect()` does (pragmas, an
attached history DB, …) lives in the `opener` callable passed at construction,
so the substrate, auth, and drafts DBs each own one instance without copying
the thread-local bookkeeping.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Callable, Generic, TypeVar

ConfigT = TypeVar("ConfigT")


class ConnectionProvider(Generic[ConfigT]):
    """Hands each thread its own connection to one database.

    `opener(config)` opens a fresh connection from the configured value —
    it carries all the DB-specific setup (path, pragmas, attachments).
    """

    def __init__(
        self, name: str, opener: Callable[[ConfigT], sqlite3.Connection]
    ) -> None:
        self._name = name
        self._opener = opener
        self._config: tuple[ConfigT, int] | None = None
        self._epoch = 0
        self._config_lock = threading.Lock()
        self._tls = threading.local()

    def configure(self, config: ConfigT) -> None:
        """Point the provider at a database. Threads (re)open lazily."""
        with self._config_lock:
            self._epoch += 1
            self._config = (config, self._epoch)

    def use(self, conn: sqlite3.Connection) -> None:
        """Pin `conn` as this thread's connection, overriding the configured
        value. For :memory: DBs and unit tests."""
        self._tls.override = conn

    def reset(self) -> None:
        """Forget the configured value and this thread's cached/override
        connection. Used between tests for isolation."""
        with self._config_lock:
            self._config = None
        self._tls.override = None
        self._tls.entry = None

    def connection(self) -> sqlite3.Connection:
        """The calling thread's connection.

        An explicit override wins; otherwise the thread's cached connection is
        returned when its epoch matches the current config, and reopened when
        it doesn't. Raises if nothing is configured and no override is pinned.
        """
        override = getattr(self._tls, "override", None)
        if override is not None:
            return override
        cfg = self._config
        if cfg is None:
            raise RuntimeError(
                f"{self._name} connection not configured; call configure() or use()"
            )
        config, epoch = cfg
        entry = getattr(self._tls, "entry", None)
        if entry is not None and entry[0] == epoch:
            return entry[1]
        if entry is not None:
            # Stale connection from a previous config — drop it before reopening.
            try:
                entry[1].close()
            except sqlite3.Error:
                pass
        conn = self._opener(config)
        self._tls.entry = (epoch, conn)
        return conn
