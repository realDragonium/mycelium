"""Research runs: (source codebase + topic) -> reviewable draft.

This package generalizes `ingest` (free text -> draft) to a codebase: a
research run shallow-clones a configured GitHub source, drives one model
context that EXPLORES the checkout with bounded workspace read tools,
RECONCILES what it finds against the substrate with the same read primitives
ingest uses, and EMITS a draft of proposed ops through the existing
`ingest/draft.py` seam. A human curator reviews and applies the draft in the
cockpit — that flow is unchanged.

Structural no-live-write guarantee
----------------------------------
The inner model is handed READ tools only — the workspace tools
(`ws_list_files` / `ws_grep` / `ws_read_file`), the substrate read
primitives, and exactly one terminal tool, `emit_draft`. It never sees a
substrate write tool, and this package never touches `server._conn`. The
only write path is `ingest.draft.DraftEmitter` into the drafts DB, whose
contents a curator must approve before anything replays live.

Prompt injection posture
------------------------
The model reads arbitrary repository content, so every file in the workspace
is potentially adversarial model input. The structural guarantee above IS the
defense: instructions smuggled into the source can, at worst, distort the
*draft* — which a curator reviews and rejects. No tool reachable from the
loop mutates the substrate, the filesystem outside the workspace, or the
network.
"""

from __future__ import annotations

from typing import Any

from .config import ResearchConfig
from .schema import NothingFound, ResearchDraftCreated, ResearchResult
from .sources import Source, SourceError
from .workspace import WorkspaceReader

__all__ = [
    "run_research",
    "ResearchConfig",
    "ResearchResult",
    "ResearchDraftCreated",
    "NothingFound",
    "Source",
    "SourceError",
    "WorkspaceReader",
]


def run_research(topic: str, source: Any = None, **kwargs: Any) -> ResearchResult:
    """Lazy re-export of :func:`mycelium.research.loop.run_research`.

    Deferred so importing the package never pulls the anthropic SDK.
    """
    from .loop import run_research as _run

    return _run(topic, source, **kwargs)
