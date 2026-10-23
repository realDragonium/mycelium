"""Layout subprocess wiring and debounce behavior without timers or processes."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest

from mycelium import layout_baker


def test_bake_argv_shape() -> None:
    db_path = Path("/data/mycelium.db")
    output_path = Path("/data/entity-positions.json")

    argv = layout_baker._bake_argv(db_path, output_path)

    assert argv == [
        sys.executable,
        "-m",
        "mycelium.entity_layout",
        "--db",
        str(db_path),
        "--output",
        str(output_path),
    ]


def test_bake_argv_uses_current_interpreter() -> None:
    argv = layout_baker._bake_argv(Path("db"), Path("out"))
    assert argv[0] == sys.executable


def test_bake_argv_flags_precede_their_values() -> None:
    db_path = Path("some/db.sqlite")
    output_path = Path("some/out.json")

    argv = layout_baker._bake_argv(db_path, output_path)

    assert argv[3] == "--db"
    assert argv[4] == str(db_path)
    assert argv[5] == "--output"
    assert argv[6] == str(output_path)


def test_trigger_during_running_bake_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timers: list[FakeTimer] = []

    class FakeTimer:
        def __init__(self, interval: float, callback: Callable[[], None]) -> None:
            assert interval == layout_baker.DEBOUNCE_SECONDS
            self.callback = callback
            self.daemon = False
            self.cancelled = False

        def start(self) -> None:
            assert self.daemon
            timers.append(self)

        def cancel(self) -> None:
            self.cancelled = True

    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(layout_baker.threading, "Timer", FakeTimer)
    monkeypatch.setattr(layout_baker.subprocess, "Popen", popen)
    baker = layout_baker.LayoutBaker(Path("/data/mycelium.db"))

    baker.schedule_rebake()
    timers[-1].callback()
    popen.assert_called_once()
    assert "cwd" not in popen.call_args.kwargs

    baker.schedule_rebake()
    baker.schedule_rebake()
    assert timers[-2].cancelled
    for _ in range(2):
        timer = timers[-1]
        timer.callback()
        assert timers[-1] is not timer
        popen.assert_called_once()

    process.poll.return_value = 0
    timer_count = len(timers)
    timers[-1].callback()
    assert popen.call_count == 2
    assert len(timers) == timer_count
    assert baker._timer is None
