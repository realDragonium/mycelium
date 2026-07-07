"""The `ask` consumer entry point: resolve a natural-language question against
the substrate by running an in-process Sonnet reasoning loop over the read
primitives.

This package is additive. It does not touch the write pipeline or the existing
read primitives — it only *exposes* the read primitives to an inner model and
synthesises a structured, uncertainty-honest answer.

Public surface:
    run_ask(question, ...) -> AskResult   # the loop
    AskConfig                             # tunables (model, op cap, wall clock)
    Answered / NeedsClarification         # the discriminated outcome
"""

from .config import AskConfig
from .loop import run_ask
from .schema import Answered, AskResult, Interpretation, NeedsClarification

__all__ = [
    "run_ask",
    "AskConfig",
    "AskResult",
    "Answered",
    "NeedsClarification",
    "Interpretation",
]
