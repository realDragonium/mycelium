"""Per-thread substrate connections isolate uncommitted writes.

Before this, the process shared one substrate connection across the request
threadpool, so a read on one thread could observe another thread's in-flight
(uncommitted) rows. Now each thread gets its own connection; a reader sees only
committed state. Writers still serialize process-wide through `transaction()`.
"""

from __future__ import annotations

import threading

from mycelium import store


def test_uncommitted_write_is_invisible_to_another_thread(tmp_path):
    store.reset_substrate()
    store.configure_substrate(tmp_path / "sub.db")
    # Create the schema on the main thread's connection (migrate commits).
    store.migrate(store.substrate_connection())

    in_txn = threading.Event()
    may_commit = threading.Event()
    seen: dict[str, int] = {}
    errors: list[BaseException] = []

    def writer():
        try:
            conn = store.substrate_connection()
            with store.transaction(conn):
                store.create_statement(conn, "event", "isolation probe")
                # Row is written but NOT committed. Let the reader look now.
                in_txn.set()
                may_commit.wait(3)
            # transaction() commits here on block exit.
        except BaseException as exc:  # pragma: no cover - surfaced via errors
            errors.append(exc)
            in_txn.set()

    def reader():
        try:
            in_txn.wait(3)
            # The reader's OWN connection (different thread) must not see the
            # writer's uncommitted row.
            seen["mid"] = store.count_statements(store.substrate_connection())
        finally:
            may_commit.set()

    tw, tr = threading.Thread(target=writer), threading.Thread(target=reader)
    tw.start()
    tr.start()
    tw.join(5)
    tr.join(5)

    assert not errors, errors
    assert seen["mid"] == 0  # uncommitted write was invisible cross-thread
    # After the writer committed, a fresh read sees the row.
    assert store.count_statements(store.substrate_connection()) == 1

    store.reset_substrate()


def test_actor_is_isolated_per_context():
    """`set_actor` writes a ContextVar, so a value set in one thread's context
    does not leak into another thread (which starts from the default)."""
    store.set_actor(None)
    seen: dict[str, str | None] = {}

    def worker():
        # A fresh thread starts from the default context: no actor.
        seen["before"] = store.get_actor()
        store.set_actor("worker-principal")
        seen["after"] = store.get_actor()

    store.set_actor("main-principal")
    t = threading.Thread(target=worker)
    t.start()
    t.join(3)

    assert seen["before"] is None
    assert seen["after"] == "worker-principal"
    # The worker's set did not clobber the main thread's actor.
    assert store.get_actor() == "main-principal"
    store.set_actor(None)
