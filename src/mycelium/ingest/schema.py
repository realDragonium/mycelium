"""The discriminated output contract for `ingest`.

`run_ingest` returns exactly one of `DraftCreated | NothingToIngest`. These are
the caller-facing shapes; the inner model fills the `emit_draft` *tool* schema
(see `tools.py`), which deterministic code validates and maps onto these
models, attaching the machine-readable `trace`.

The op vocabulary (`OpKind`) is the set of substrate *write*-tool function
names a draft op may carry — but `ingest` itself never calls those tools. It
queues ops into a draft via `drafts_store`; a curator's all-or-nothing replay
is the only thing that ever runs them live (see `draft.py`).
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

#: The substrate mutation tools a draft op may target. A draft op's `kind` is
#: exactly one of these function names; its payload is that tool's kwargs.
OpKind = Literal[
    "upsert_statement",
    "upsert_statements",
    "upsert_entity",
    "add_links",
    "add_entity_links",
    "patch_statement",
    "replace_text",
    "merge_statements",
]


class ProposedOp(BaseModel):
    #: The substrate write-tool function name this op replays as.
    op: OpKind
    #: The tool's kwargs (None-valued keys dropped at queue time).
    payload: dict
    #: Why this op — for a REFINEMENT, the old->new change goes here.
    rationale: str
    #: Existing statement/entity ids this op targets or links to (provenance).
    targets_existing: list[str] = Field(default_factory=list)


class CandidateLedger(BaseModel):
    """One row of the per-candidate reconcile ledger — the anti-premature-
    closure record proving each extracted fact was reconciled before
    classification."""

    candidate: str
    classification: Literal[
        "new", "duplicate", "refinement", "contradiction", "unphraseable", "unprocessed"
    ]
    #: existing ids this candidate was reconciled against.
    matched_against: list[str] = Field(default_factory=list)
    #: existing statements considered as link targets (the adjacency search).
    link_candidates_considered: list[str] = Field(default_factory=list)
    note: str = ""


class DraftCreated(BaseModel):
    outcome: Literal["draft_created"] = "draft_created"
    #: the queued draft id ("drf_…") in the drafts DB.
    draft_id: str
    #: ops that passed validation and were queued.
    ops: list[ProposedOp] = Field(default_factory=list)
    #: contradictions + ops that failed hard validation (with reason).
    flagged: list[str] = Field(default_factory=list)
    #: candidates skipped as duplicates, each "candidate :: existing_id".
    skipped_duplicates: list[str] = Field(default_factory=list)
    #: tool calls + args, op count, latency, token/cost, candidate ledger.
    trace: dict = Field(default_factory=dict)


class NothingToIngest(BaseModel):
    outcome: Literal["nothing_to_ingest"] = "nothing_to_ingest"
    #: why no draft was created (all duplicates / nothing extractable /
    #: degraded).
    reason: str
    trace: dict = Field(default_factory=dict)


IngestResult = Union[DraftCreated, NothingToIngest]
