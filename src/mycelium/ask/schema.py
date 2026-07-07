"""The discriminated output contract for `ask`.

`run_ask` returns exactly one of `Answered | NeedsClarification`. These are the
caller-facing shapes; the inner model fills *tool* schemas (see `tools.py`)
which we map onto these models, attaching the machine-readable `trace`.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class Interpretation(BaseModel):
    as_asked: str           # the caller's literal question
    resolved_to: str        # what we actually set out to answer
    reframed: bool
    reframe_reason: str | None = None


class Answered(BaseModel):
    outcome: Literal["answered"] = "answered"
    answer: str
    confidence: Literal["high", "medium", "low"]
    interpretation: Interpretation
    #: unresolved parts, zero-result terms, relevant-but-unfollowed links,
    #: adjacency considered-and-rejected, open contradictions.
    gaps: list[str] = Field(default_factory=list)
    #: statement ids the answer rests on.
    provenance: list[str] = Field(default_factory=list)
    #: tool calls + args, op count, latency, token/cost, sub-question ledger.
    trace: dict = Field(default_factory=dict)


class NeedsClarification(BaseModel):
    outcome: Literal["needs_clarification"] = "needs_clarification"
    #: the clarifying question to hand back to the caller.
    question: str
    #: each: a candidate interpretation + the topics/entities it would pull.
    candidates: list[dict] = Field(default_factory=list)
    #: what recon established, so the caller has context.
    known_so_far: str
    trace: dict = Field(default_factory=dict)


AskResult = Union[Answered, NeedsClarification]
