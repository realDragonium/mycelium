"""Documentation generation: a text prompt -> a durable generated document.

The capability is split the way `research` is. This package holds what a
generation RUN is made of, `doc_runs` holds how one is started and finished,
and `docs_store` holds where its rows land.

Only the config is here so far. The loop that actually writes a document
arrives with the issue that needs it and plugs into `doc_runs.RUNNER`, which
is why the executor can be finished and proven against a stub first.
"""

from __future__ import annotations

from .config import DocgenConfig

__all__ = ["DocgenConfig"]
