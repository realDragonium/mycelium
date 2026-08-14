"""The discriminated output contract for `docgen`.

`run_docgen` returns exactly one of `DocumentWritten | NothingWritten`. These
are the shapes `doc_runs` persists: it reads `outcome` to decide the run's
terminal state, hands the document fields to `docs_store.upsert_document`,
and records `reason` on a refusal.

Neither shape carries an id. The loop decides *what the document says*; where
it lands — the `gdc_…` row, its `last_run_id` — is the executor's business,
which is what keeps the loop provable without a database.

Both shapes carry the resolved `guideline_set` / `document_type`, including
the refusal: a run that chose a set and then found nothing to say has still
made that choice, and the row should show it.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class DocumentWritten(BaseModel):
    outcome: Literal["document_written"] = "document_written"
    #: Stable identity of the page. Derived from the title by the harness,
    #: never chosen by the model — see `loop._slug`.
    slug: str
    title: str
    body: str
    #: Statement ids the body rests on. Never empty: a document with none is
    #: refused rather than recorded.
    statement_ids: list[str] = Field(default_factory=list)
    guideline_set: str
    document_type: str
    #: What the guideline set asked for that the substrate could not supply —
    #: the run's own account, which is NOT a receipt. What actually reached a
    #: curator's queue is `trace["reported_gaps"]`, and the two are kept apart
    #: there precisely because a run can declare a gap at emit time that it
    #: never filed (a forced finalize has no turn left to file one in).
    gaps: list[str] = Field(default_factory=list)
    #: tool calls + args, op count, latency, token/cost, grounding.
    trace: dict = Field(default_factory=dict)


class NothingWritten(BaseModel):
    outcome: Literal["nothing_written"] = "nothing_written"
    #: Why no document was produced — unresolvable guideline set, a missing
    #: template row, an emit that never carried statement ids, a degraded
    #: finalize.
    reason: str
    guideline_set: str | None = None
    document_type: str | None = None
    gaps: list[str] = Field(default_factory=list)
    trace: dict = Field(default_factory=dict)


DocgenResult = Union[DocumentWritten, NothingWritten]
