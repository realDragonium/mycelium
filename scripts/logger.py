"""JSONL logging for cleanup tool.

Every decision is logged: suspect detection, context gathering, model output,
user input, and final actions.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class Logger:
    """Logs events to JSONL for auditability and resumability."""

    def __init__(self, logfile: str | Path, verbose: bool = False):
        self.logfile = Path(logfile)
        self.verbose = verbose

    def log(self, event: str, **kwargs: Any) -> None:
        """Log an event with structured data."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            **kwargs,
        }
        with open(self.logfile, "a") as f:
            f.write(json.dumps(entry) + "\n")

        if self.verbose:
            print(f"[{event}] {kwargs}", file=sys.stderr)

    def info(self, message: str) -> None:
        """Print an info message to stdout."""
        print(message)
        self.log("info", message=message)

    def read_events(self) -> list[dict[str, Any]]:
        """Read all logged events from the file."""
        if not self.logfile.exists():
            return []

        events = []
        with open(self.logfile) as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events
