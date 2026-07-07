"""The `ingest` write-harness entry point: turn a block of free text into a
reviewable DRAFT of proposed substrate changes by running an in-process Sonnet
loop over the read primitives.

One Sonnet context drives extract -> reconcile -> classify -> link -> emit;
deterministic code does vocab-fetch, draft assembly, validation, and trace. The
model is handed ONLY read tools plus one terminal `emit_draft` tool — it never
sees a write tool. The draft is created in deterministic code via `drafts_store`
(see `draft.py`), so there is provably no live-write path.

Public surface:
    run_ingest(text, ...) -> IngestResult       # the loop
    IngestConfig                                 # tunables
    DraftCreated / NothingToIngest               # the discriminated outcome
    ProposedOp                                   # one queued draft op
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import IngestConfig
from .schema import DraftCreated, IngestResult, NothingToIngest, ProposedOp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .loop import run_ingest as run_ingest


def run_ingest(text: str, **kwargs: Any) -> IngestResult:
    """Lazy re-export of the loop entry point.

    `loop.py` pulls in `prompts`/`tools`; importing it lazily keeps the package
    importable (and the config/schema/draft surface usable) without those — and
    without an Anthropic client present.
    """
    from .loop import run_ingest as _run_ingest

    return _run_ingest(text, **kwargs)


__all__ = [
    "run_ingest",
    "IngestConfig",
    "IngestResult",
    "DraftCreated",
    "NothingToIngest",
    "ProposedOp",
]
