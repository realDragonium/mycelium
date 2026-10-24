"""The background worker runner: passes, errors, wake-ups and shutdown."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from mycelium import workers


def test_a_failing_pass_does_not_end_the_worker_and_stop_closes_its_session():
    events: list[str] = []
    passed = threading.Event()

    @contextmanager
    def session() -> Iterator[str]:
        events.append("open")
        yield "conn"
        events.append("close")

    def run_pass(conn: str) -> None:
        events.append(f"pass {conn}")
        passed.set()
        if events.count(f"pass {conn}") == 1:
            raise RuntimeError("Provider unavailable.")

    worker = workers.Worker("test-worker", run_pass, interval=60, session=session)
    worker.start()
    assert passed.wait(2)
    passed.clear()
    worker.wake()
    assert passed.wait(2)
    worker.stop()

    assert not worker.running()
    assert events == ["open", "pass conn", "pass conn", "close"]


def test_a_delayed_worker_stopped_before_its_first_interval_runs_no_pass():
    passes: list[None] = []
    worker = workers.Worker(
        "test-sweep",
        passes.append,
        interval=60,
        session=workers.no_session,
        delay_first=True,
    )
    worker.start()
    worker.stop()

    assert not worker.running()
    assert passes == []
