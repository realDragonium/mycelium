"""Tool entry points into the model loops: Ask, Ingest and Research.

`ask` and `ingest` run their loop inside the call, under the shared
model-loop budget (see `admission`). `start_research` only queues a background
run and returns its id; the run draws on the same budget when it starts. None
of them writes the substrate directly: Ingest and Research produce drafts.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from ..require import require
from .drafts import _auto_submit
from .registry import tool
from .runtime import _context, _drafts_db


@tool(role="asker")
def ask(
    question: str,
    depth: Literal["standard", "quick"] = "standard",
    verbose: bool = False,
) -> dict[str, object]:
    """Resolve a natural-language question against the substrate, honestly.

    The higher-level entry point for callers who don't want to compose the read
    primitives by hand (docs generation, internal support). Under the hood it
    runs an in-process Sonnet reasoning loop that drives the same read
    primitives, follows typed links, re-searches for semantically-adjacent
    statements, and synthesises a structured answer that is explicit about gaps
    and provenance.

    By default returns only `outcome`, `answer`, and `confidence` for an
    answered question, or `outcome` and `question` when clarification is needed.
    Important limitations remain in the answer text. Re-ask with the clarified
    question to resolve ambiguity.

    Set `verbose=True` for the full result: interpretation, gaps, provenance,
    and trace for answers; candidates, known_so_far, and trace for clarification.
    This affects response detail only, not retrieval or reasoning effort.

    `depth` trades thoroughness for latency:
      * `standard` (default) — the full loop: recon, targeted retrieval, and a
        concept-seeded adjacency re-search before concluding. Most thorough;
        can run tens of seconds.
      * `quick` — a latency-boxed fast path for callers with a hard timeout
        (e.g. an MCP client that drops the call at ~30s). Drops the adjacency
        floor and tightens the caps so it collapses to recon -> a targeted read
        or two -> answer, returning a real answer well inside the window. It can
        miss unlinked-but-relevant statements the adjacency re-search would find,
        so gaps/confidence are your guide.

    The call runs a multi-second reasoning loop bounded by an operation cap and
    a wall-clock budget; on exhaustion it degrades to a low-confidence partial
    answer rather than raising.
    """
    from ..ask import AskConfig, run_ask
    from ..ask.config import for_depth

    config = for_depth(AskConfig.from_env(), depth)
    if config.trace_log_path is None:
        config = replace(
            config, trace_log_path=str(_context().data_dir / "ask_trace.jsonl")
        )
    result = run_ask(question, config=config)
    if verbose:
        return result.model_dump()
    if result.outcome == "answered":
        return {
            "outcome": result.outcome,
            "answer": result.answer,
            "confidence": result.confidence,
        }
    return {"outcome": result.outcome, "question": result.question}


@tool
def ingest(text: str) -> dict[str, Any]:
    """Extract knowledge from free text and emit a reviewable DRAFT of proposed
    substrate changes. Never writes to the substrate live.

    The higher-level write-side counterpart to `ask`: hand it a block of text
    (release notes, a spec excerpt, support transcript) and it runs an
    in-process Sonnet loop that extracts atomic statements, reconciles each one
    against existing knowledge with the read primitives, classifies it
    (new/duplicate/refinement/contradiction), and proposes links — then queues
    the result as a DRAFT for review before anything is applied. The inner model is
    given only read tools plus one terminal emit tool; it has no write path. The
    draft is created in deterministic code, so nothing is ever written live.

    While internal draft review is on, the draft is submitted to the
    reviewer at once; otherwise it stays open for curation. Alias
    suggestions go to a separate draft, each awaiting a person's decision.

    Returns one of two shapes (discriminated by `outcome`):
      * `draft_created` — `draft_id` ("drf_…"), `alias_draft_id` (or null),
        `submitted_for_review`, the queued `ops`, `flagged` contradictions,
        `skipped_duplicates`, and `trace`.
      * `nothing_to_ingest` — a `reason` (all duplicates / nothing extractable /
        degraded) and `trace`.

    The call runs a multi-second reasoning loop bounded by an operation cap and
    a wall-clock budget; on exhaustion it degrades to a forced emit (or
    `nothing_to_ingest`) rather than raising.
    """
    from ..ingest import IngestConfig, run_ingest

    config = IngestConfig.from_env()
    if config.trace_log_path is None:
        config = replace(
            config, trace_log_path=str(_context().data_dir / "ingest_trace.jsonl")
        )
    result = run_ingest(text, config=config)
    response = result.model_dump()
    if result.outcome == "draft_created":
        response["submitted_for_review"] = _auto_submit(result.draft_id)
    return response


def _resolve_research_source(name: str | None) -> str:
    from ..research import sources as research_sources

    try:
        configured = research_sources.load_sources()
    except research_sources.SourceError as exc:
        raise ValueError(str(exc)) from exc

    if name is not None:
        if name not in configured:
            raise ValueError(
                f"unknown source '{name}'; configured: {sorted(configured)}"
            )
        return name

    if not configured:
        raise ValueError("no research sources configured (add one in AI settings)")
    if len(configured) == 1:
        return next(iter(configured))
    raise ValueError(
        "source must be specified when multiple research sources are configured: "
        f"{sorted(configured)}"
    )


@tool(role="drafter")
def start_research(topic: str, source: str | None = None) -> dict[str, Any]:
    """Start a background research run: explore a configured source codebase
    on `topic` and, if anything substantiated is found, emit a reviewable
    DRAFT (never a live write).

    Returns immediately with the serialized run row (its `status` will be
    "running"); poll `get_research_run(run_id)` for the outcome. `source` may
    be omitted when exactly one source is configured. Raises when the
    active-run cap is reached (MYCELIUM_RESEARCH_MAX_ACTIVE, default 2), when
    `source` is unknown, or when it is omitted with several sources
    configured. Returns {run row: id, topic, source, created_at, created_by,
    started_at, finished_at, outcome, draft_id, error, trace_ref, status}."""
    from .. import auth as _auth
    from .. import research_runs, research_store

    source_name = _resolve_research_source(source)
    principal = _auth.current_principal.get()
    created_by = principal.id if principal is not None else None
    run_id = research_runs.start_run(
        topic=topic,
        source=source_name,
        created_by=created_by,
        data_dir=_context().data_dir,
        conn=_drafts_db(),
    )
    row = require(
        research_store.get_run(_drafts_db(), run_id), "research run just created"
    )
    return research_store.serialize_run(row)


@tool
def list_research_runs() -> dict[str, Any]:
    """List research runs, newest first, each with a derived `status`
    (queued/running/draft_created/nothing_found/failed).

    Returns {"runs": [run rows]}."""
    from .. import research_store

    return {
        "runs": [
            research_store.serialize_run(row)
            for row in research_store.list_runs(_drafts_db())
        ]
    }


@tool
def get_research_run(run_id: str) -> dict[str, Any]:
    """Fetch one research run by id, including outcome, draft_id (when a
    draft was created), error, and trace_ref.

    Returns the serialized run row. Raises for an unknown run_id."""
    from .. import research_store

    row = research_store.get_run(_drafts_db(), run_id)
    if row is None:
        raise ValueError(f"research run not found: {run_id}")
    return research_store.serialize_run(row)


@tool
def list_research_sources() -> dict[str, Any]:
    """List the configured research sources a run can target (names and repo
    coordinates only - never credentials).

    Returns {"sources": [{name, owner, repo, ref}]}."""
    from ..research import sources

    try:
        configured = sources.load_sources()
    except sources.SourceError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "sources": [
            {
                "name": source.name,
                "owner": source.owner,
                "repo": source.repo,
                "ref": source.ref,
            }
            for source in configured.values()
        ]
    }
