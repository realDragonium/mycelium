"""The discriminated output contract for `research`.

`run_research` returns exactly one of `ResearchDraftCreated | NothingFound`.
The inner model fills the same `emit_draft` tool schema ingest uses
(`ingest/tools.py`); deterministic code validates it and maps it onto these
models, attaching the machine-readable `trace` (which additionally carries
`source`, `topic`, and `files_read`).

The op vocabulary is ingest's `OpKind`, re-exported unchanged — research
proposes corrections with the exact same op kinds (`patch_statement`,
`replace_text`, `merge_statements`, `upsert_statement` with `id`, ...) and
invents none of its own.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

from ..ingest.schema import CandidateLedger, OpKind, ProposedOp

__all__ = [
    "OpKind",
    "ProposedOp",
    "CandidateLedger",
    "ResearchDraftCreated",
    "NothingFound",
    "ResearchResult",
]


class ResearchDraftCreated(BaseModel):
    outcome: Literal["draft_created"] = "draft_created"
    #: the queued draft id ("drf_…") in the drafts DB.
    draft_id: str
    #: the configured source name the run explored.
    source: str
    #: the research topic the run was asked to investigate.
    topic: str
    #: ops that passed validation and were queued.
    ops: list[ProposedOp] = Field(default_factory=list)
    #: contradictions + ops that failed hard validation (with reason).
    flagged: list[str] = Field(default_factory=list)
    #: candidates skipped as duplicates, each "candidate :: existing_id".
    skipped_duplicates: list[str] = Field(default_factory=list)
    #: tool calls + args, files read, op count, latency, token/cost, ledger.
    trace: dict = Field(default_factory=dict)


class NothingFound(BaseModel):
    outcome: Literal["nothing_found"] = "nothing_found"
    #: why no draft was created (nothing substantiated / all duplicates /
    #: source fetch failed / degraded).
    reason: str
    source: str = ""
    topic: str = ""
    trace: dict = Field(default_factory=dict)


ResearchResult = Union[ResearchDraftCreated, NothingFound]
