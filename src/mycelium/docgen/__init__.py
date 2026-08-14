"""Documentation generation: a text prompt -> a durable generated document.

The capability is split the way `research` is. This package holds what a
generation RUN is made of — the loop, its prompts, its tools, its doctrine —
`doc_runs` holds how one is started and finished, and `docs_store` holds where
its rows land.

The loop resolves which guideline set and document type the request wants,
gathers from the substrate through the read primitives `ask/substrate.py`
discovers, and terminates on a document plus the statement ids it rests on.
It has no write tool, so nothing it produces can enter the draft pipeline or
become substrate truth.
"""

from __future__ import annotations

from typing import Any

from .config import DocgenConfig
from .schema import DocgenResult, DocumentWritten, NothingWritten

__all__ = [
    "run_docgen",
    "DocgenConfig",
    "DocgenResult",
    "DocumentWritten",
    "NothingWritten",
]


def run_docgen(prompt: str, **kwargs: Any) -> DocgenResult:
    """Lazy re-export of :func:`mycelium.docgen.loop.run_docgen`.

    Deferred so importing the package never pulls the anthropic SDK.
    """
    from .loop import run_docgen as _run

    return _run(prompt, **kwargs)
