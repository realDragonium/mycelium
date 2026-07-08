"""Resumable checkpoint state.

Reads the JSONL log to figure out which behaviors are already settled, so
restarting after a crash (or hitting Ctrl-C mid `needs-input`) doesn't
re-investigate them. A behavior is "done" when the log contains a
terminal event — `applied`, `proposed`, `merged`, `skipped`, `error`.
"""

from __future__ import annotations

import json
from pathlib import Path

_TERMINAL_EVENTS = {
    "applied",
    "proposed",
    "merged",
    "skipped",
    "error_terminal",
}


class CheckpointState:
    def __init__(self, logfile: str | Path):
        self.logfile = Path(logfile)
        self._done: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.logfile.exists():
            return
        with open(self.logfile) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("event") in _TERMINAL_EVENTS and "behavior_id" in entry:
                    self._done.add(entry["behavior_id"])

    def is_done(self, behavior_id: str) -> bool:
        return behavior_id in self._done

    def mark_done(self, behavior_id: str) -> None:
        self._done.add(behavior_id)

    def has_pending(self) -> bool:
        return bool(self._done)
