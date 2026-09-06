"""One shared model budget that can shrink without replacing active permits."""

from __future__ import annotations

import threading
from collections.abc import Callable


class Capacity:
    def __init__(self, limit: Callable[[], int]) -> None:
        self._limit = limit
        self._condition = threading.Condition()
        self._active = 0

    def acquire(self, blocking: bool = True) -> bool:
        with self._condition:
            while self._active >= self._limit():
                if not blocking:
                    return False
                self._condition.wait()
            self._active += 1
            return True

    def release(self) -> None:
        with self._condition:
            if self._active == 0:
                raise ValueError("Model capacity released without an active run.")
            self._active -= 1
            self._condition.notify_all()

    def changed(self) -> None:
        with self._condition:
            self._condition.notify_all()
