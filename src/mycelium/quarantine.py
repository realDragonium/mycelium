"""Quarantine: serving a copy of production data without acting on its behalf.

A restored copy still holds the original's review settings, writing profiles
and GitHub destinations, so starting it would review drafts, revise documents
and open pull requests as if it were the original. In quarantine the server
starts no background AI worker, treats draft review as off and refuses GitHub
delivery, without changing any saved setting: the same data starts normally
once the flag is gone.
"""

from __future__ import annotations

import os

ENV = "MYCELIUM_QUARANTINE"


def active() -> bool:
    return os.environ.get(ENV) == "1"


def enable() -> None:
    os.environ[ENV] = "1"
