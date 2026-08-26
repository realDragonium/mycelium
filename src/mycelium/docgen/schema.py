"""The discriminated output contract for `docgen`.

`run_docgen` returns exactly one of `DocumentWritten | NothingWritten`. These
are the shapes `doc_runs` persists: it reads `outcome` to decide the run's
terminal state, hands the document fields to `docs_store.upsert_document`,
and records `reason` on a refusal. The review record travels with the
document, so reaching the persistent shape proves that the gate ran.

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


class ReviewFinding(BaseModel):
    """One actionable reason a review check failed."""

    #: Where in the document the problem is — a section heading or a quoted
    #: phrase. A finding a writer cannot locate is not actionable.
    where: str
    #: What failed, in the reviewer's own words.
    problem: str


class ReviewCheck(BaseModel):
    """One independently reported side of the review gate."""

    status: Literal["pass", "fail", "unchecked"]
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReviewRecord(BaseModel):
    """The review gate's verdict carried by a terminal outcome."""

    #: Whether the text respects what this guideline set may reveal.
    #: `unchecked` when the set states no exposure rules.
    exposure: ReviewCheck
    #: Whether it matches the template and the document type's expectations.
    conformance: ReviewCheck
    #: How many times a written document was put to the reviewer. 1 is a
    #: clean first pass; 2 means the retry fired.
    attempts: int
    passed: bool


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
    #: The independent gate that accepted this exact document.
    review: ReviewRecord
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
    #: Present only when a written document reached and failed the review gate.
    review: ReviewRecord | None = None
    #: The refused draft, present only when one was written and the gate turned
    #: it down. Nothing publishes a stored document on its own, so keeping the
    #: text costs no exposure and is what lets a person judge the refusal
    #: instead of paying for another run to see a different document.
    title: str | None = None
    body: str | None = None
    gaps: list[str] = Field(default_factory=list)
    trace: dict = Field(default_factory=dict)


DocgenResult = Union[DocumentWritten, NothingWritten]
