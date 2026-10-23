"""Tool entry points into the model loops: Ask, Ingest and Connect.

Each runs their loop inside the call, under the shared model-loop budget (see
`admission`). None writes the substrate directly: Ingest and Connect produce drafts.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from .drafts import _auto_submit
from .registry import tool
from .runtime import _context, _db


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
    from .. import audience_scope, principal_audience
    from ..ask import AskConfig, run_ask
    from ..ask.config import for_depth
    from ..ask.substrate import InProcessSubstrate

    config = for_depth(AskConfig.from_env(), depth)
    if config.trace_log_path is None:
        config = replace(
            config, trace_log_path=str(_context().data_dir / "ask_trace.jsonl")
        )
    # A scoped caller's whole loop reads one snapshot of what its audience
    # may see, so no answer or citation can rest on anything else.
    scope = principal_audience.current_scope()
    substrate = (
        None
        if scope is None
        else audience_scope.ScopedSubstrate(InProcessSubstrate(), scope)
    )
    result = run_ask(question, config=config, substrate=substrate)
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


@tool
def connect_statements(statement_ids: list[str]) -> dict[str, Any]:
    """Propose links and concept mentions for existing statements that have
    none, as a reviewable DRAFT. Never writes to the substrate live.

    Runs the ingest loop over the given statements instead of free text: it
    searches around each one and proposes `add_links` edges that touch a
    given statement, aliases a given statement uses for an existing concept,
    and new concepts a given statement names. It never creates, rewrites,
    merges or deletes a statement; any such proposal is dropped and flagged,
    and so is an edge that points the wrong way.

    The connect action's saved settings choose the model and bound the run:
    at most `batch_size` statements per call, an operation cap, a wall clock
    and a spending cap. The draft goes to review exactly as an ingest draft
    does. Returns the same shapes as `ingest`, with `cost_usd` (null when the
    model has no known price). Refused while the monthly AI budget pauses
    background actions.
    """
    from .. import ai, knowledge_health, model_settings, product_settings, store
    from ..ingest.connect import config_from_settings, run_connect

    if reason := model_settings.credentials_error("connect"):
        raise ValueError(reason)
    limits = product_settings.get(product_settings.ConnectSettings)
    ids = list(dict.fromkeys(statement_ids))
    if not ids:
        raise ValueError("statement_ids must name at least one statement")
    if len(ids) > limits.batch_size:
        raise ValueError(
            f"at most {limits.batch_size} statements per run; got {len(ids)}"
        )
    targets = knowledge_health.targets(_db(), ids)
    config = replace(
        config_from_settings(),
        trace_log_path=str(_context().data_dir / "connect_trace.jsonl"),
    )
    try:
        result = run_connect(
            targets,
            known_name=lambda name: store.get_name_by_text(_db(), name) is not None,
            config=config,
        )
    except ai.usage.Paused as exc:
        raise ValueError(str(exc)) from exc
    response = result.model_dump()
    response["cost_usd"] = result.trace.get("cost_usd")
    if result.outcome == "draft_created":
        response["submitted_for_review"] = _auto_submit(result.draft_id)
    return response
