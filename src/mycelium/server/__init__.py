"""MCP server exposing the Mycelium substrate over stdio.

Tools are registered with the local `@tool` decorator (not the bare
`mcp.tool()`) so they show up in the HTTP transport in `mycelium/http.py`
and in the in-process loops. Only the names in `MCP_TOOLS` are also
advertised over MCP: every MCP client pays for each schema it is sent, so
that surface is a deliberate, documented subset (`docs/MCP_TOOLS.md`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json as _json
import logging
import os
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import JsonValue

from .. import (
    databases,
    documentation_profiles,
    link_authoring,
    link_rules,
    mentions,
    phrasing,
    store,
    timestamps,
    vector,
)
from ..app_context import AppContext
from ..auth import Principal as AuthPrincipal
from ..layout_baker import LayoutBaker
from ..require import require
from . import runtime
from .admission import limiter_for, model_loop_slot
from .authoring import (
    delete_statement,
    merge_statements,
    patch_statement,
    replace_text,
    upsert_statement,
    upsert_statements,
)
from .draft_queue import _MUTATION_PREFIXES
from .entities import (
    add_entity_links,
    delete_entity,
    get_entity,
    list_entities,
    merge_entities,
    remove_entity_links,
    search_entities,
    upsert_entity,
)
from .indexes import (
    _clear_dirty_marker,
    _dirty_marker_path,
    _fsync_file,
    _persisted_index_write,
    _rebuild_vector_index,
    _restore_index_snapshots,
    _write_dirty_marker,
)
from .links import add_links, remove_links
from .lookups import get_statements, grep_statements, list_statements, retrieve_context
from .names import (
    delete_name,
    find_entity_duplicates,
    get_mention_candidates,
    move_name,
    rename_name,
    upsert_name,
)
from .registry import _ORIG_SIGNATURES, MCP_TOOLS, TOOLS, mcp, publish, tool
from .runtime import (
    _auth_db,
    _context,
    _db,
    _drafts_db,
    _idx,
    _idx_path,
    _name_idx,
    _name_idx_path,
    _prompts_db,
)
from .search import (
    NEAR_DUPLICATE_THRESHOLD,
    SNIPPET_CHARS,
    discover_facts,
    find_duplicates,
    find_statement_connections,
    search_statements,
    survey_statements,
)
from .specs import (
    BatchStatementSpec,
    EdgeSpec,
    EntityEdgeSpec,
    IncomingLinkSpec,
    LinkSpec,
    ResultLimit,
)

#: The public names, tools first: their order here is the order `publish` gives
#: `TOOLS`, and so the order of every surface built from it.
__all__ = [
    "get_mention_candidates",
    "search_statements",
    "find_statement_connections",
    "survey_statements",
    "ask",
    "ingest",
    "start_research",
    "list_research_runs",
    "get_research_run",
    "request_documentation",
    "revise_document",
    "list_document_revisions",
    "get_document_revision",
    "list_documentation_models",
    "list_documentation_runs",
    "get_documentation_run",
    "list_generated_documents",
    "get_generated_document",
    "deliver_document",
    "list_documentation_destinations",
    "list_research_sources",
    "upsert_entity",
    "upsert_statement",
    "upsert_statements",
    "replace_text",
    "patch_statement",
    "upsert_name",
    "merge_entities",
    "move_name",
    "rename_name",
    "delete_name",
    "delete_entity",
    "merge_statements",
    "delete_statement",
    "add_links",
    "remove_links",
    "get_statements",
    "retrieve_context",
    "get_entity",
    "list_entities",
    "search_entities",
    "list_statements",
    "find_duplicates",
    "find_entity_duplicates",
    "discover_facts",
    "list_link_types",
    "add_entity_links",
    "remove_entity_links",
    "list_statement_kinds",
    "list_entity_link_types",
    "upsert_statement_kind",
    "delete_statement_kind",
    "upsert_link_type",
    "delete_link_type",
    "upsert_link_type_alias",
    "delete_link_type_alias",
    "list_link_type_aliases",
    "upsert_entity_link_type",
    "delete_entity_link_type",
    "grep_statements",
    "report_knowledge_gap",
    "save_prompt_text",
    "get_prompt_text",
    "list_prompt_texts",
    "list_prompt_text_versions",
    "retire_prompt_text",
    "list_documentation_profiles",
    "get_documentation_profile",
    "save_documentation_profile",
    "retire_documentation_profile",
    "restore_prompt_text",
    "submit_draft",
    "request_draft_review",
    "get_draft_review_run",
    "set_draft_review_evidence",
    "list_my_drafts",
    "list_drafts",
    "get_draft",
    "attach_draft_source",
    "find_my_draft_by_source",
    "revise_draft_operation",
    "strike_draft_operation",
    "discard_draft_op",
    "inspect_draft_review",
    "append_draft_correction",
    "record_draft_review",
    "apply_reviewed_draft",
    "MCP_TOOLS",
    "TOOLS",
    "limiter_for",
    "mcp",
    "model_loop_slot",
    "tool",
    "BatchStatementSpec",
    "EdgeSpec",
    "EntityEdgeSpec",
    "IncomingLinkSpec",
    "LinkSpec",
    "ResultLimit",
    "NEAR_DUPLICATE_THRESHOLD",
    "SNIPPET_CHARS",
]

logger = logging.getLogger(__name__)


def init(data_dir: Path) -> None:
    """Open the substrate + auth DBs and load (or create) the two
    vector indexes (statements, entity names).

    Auth lives in its own SQLite file (`mycelium-auth.db`) so the
    substrate file can be replaced without disturbing identity or
    tokens — drop `mycelium.db` and restart, every existing user
    session and bearer token keeps working.
    """
    # Invalidate before reconfiguring: if init is re-entered and fails partway
    # (store providers already repointed at the new data dir), leave the
    # process cleanly uninitialized rather than serving the old context's
    # indexes against the new substrate.
    runtime._ctx = None

    from .. import auth_store, docs_store, drafts_store, prompt_store, research_store

    data_dir.mkdir(parents=True, exist_ok=True)
    # Before anything below recreates a missing database empty.
    partial_restore = databases.check_restore(data_dir)
    prompt_store.configure(data_dir / "mycelium-prompts.db")
    prompts = _prompts_db()
    existing_settings_instance = (data_dir / "mycelium.db").exists() or prompts.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name IN ('prompt_texts', 'model_settings', 'draft_review_settings')"
    ).fetchone() is not None
    # Persist fresh-instance provenance before other databases can make a
    # retry after interrupted startup look like a legacy upgrade.
    prompt_store.prepare_settings(
        prompts, import_environment=existing_settings_instance
    )
    prompt_store.migrate(prompts)
    prompt_store.initialize_settings(
        prompts, import_environment=existing_settings_instance
    )

    store.configure_substrate(
        data_dir / "mycelium.db",
        history_path=data_dir / "mycelium-history.db",
    )
    baker = LayoutBaker(data_dir / "mycelium.db")
    store.migrate(_db())
    baker.ensure_initial()

    # Point each provider at its file and run the one-time migration on this
    # thread's connection; every other thread reopens lazily against the same
    # file (see the provider in each store module).
    auth_store.configure(data_dir / "mycelium-auth.db")
    auth_store.migrate(_auth_db())

    drafts_store.configure(data_dir / "mycelium-drafts.db")
    drafts_store.migrate(_drafts_db())
    from .. import draft_review_store

    draft_review_store.mark_orphaned(
        _drafts_db(),
        lambda application_id: (
            _substrate_application_result(application_id) is not None
        ),
    )
    research_store.migrate(_drafts_db())
    docs_store.migrate(_drafts_db())
    from ..docgen import destinations

    destinations.bind_legacy_deliveries(_drafts_db())

    _seed_prompt_texts()

    orphaned = research_store.mark_orphaned(_drafts_db())
    if orphaned:
        logger.warning(
            "marked %d research run(s) failed: orphaned by restart", orphaned
        )
    orphaned_docs = docs_store.mark_orphaned(_drafts_db())
    if orphaned_docs:
        logger.warning(
            "marked %d documentation run(s) failed: orphaned by restart",
            orphaned_docs,
        )

    # The .vec files are re-derivable from the substrate, so a backup may omit
    # them while keeping the *_vector_ids mappings in the DB. When a .vec is
    # missing (a fresh checkout, or a restore of such a backup) or marked dirty
    # after an interrupted write, rebuild the index by re-embedding, or search
    # could silently use vectors that diverge from the populated substrate.
    index_path = data_dir / "mycelium.vec"
    index_dirty = _dirty_marker_path(index_path).exists()
    if index_path.exists() and not index_dirty:
        index = vector.Index.load(index_path)
    else:
        if index_dirty:
            logger.warning(
                "rebuilding statement vector index: dirty marker indicates a "
                "crash before the index was persisted"
            )
        _write_dirty_marker(index_path)
        index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                index,
                store.all_statements_with_text(_db()),
                store.get_vector_id,
                store.next_vector_id,
                store.set_vector_id,
                label="statement",
            )
        index.save(index_path)
        _fsync_file(index_path)
        _clear_dirty_marker(index_path)

    name_index_path = data_dir / "mycelium-names.vec"
    name_index_dirty = _dirty_marker_path(name_index_path).exists()
    if name_index_path.exists() and not name_index_dirty:
        name_index = vector.Index.load(name_index_path)
        # A migration can drop name rows and their vector mappings while
        # the persisted index keeps the vectors (v6's case-variant merge
        # does). Stranded vectors resolve to nothing but still occupy
        # top-k slots in every name search — prune them on load.
        stranded = [
            vid
            for vid in name_index.ids()
            if store.get_name_id_by_vector_id(_db(), vid) is None
        ]
        if stranded:
            logger.info("pruning %d stranded name vector(s)", len(stranded))
            _write_dirty_marker(name_index_path)
            for vid in stranded:
                name_index.delete(vid)
            name_index.save(name_index_path)
            _fsync_file(name_index_path)
            _clear_dirty_marker(name_index_path)
    else:
        if name_index_dirty:
            logger.warning(
                "rebuilding name vector index: dirty marker indicates a crash "
                "before the index was persisted"
            )
        _write_dirty_marker(name_index_path)
        name_index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                name_index,
                store.list_all_names(_db()),
                store.get_name_vector_id,
                store.next_name_vector_id,
                store.set_name_vector_id,
                label="name",
            )
        name_index.save(name_index_path)
        _fsync_file(name_index_path)
        _clear_dirty_marker(name_index_path)

    runtime._ctx = AppContext(
        data_dir=data_dir,
        index=index,
        index_path=index_path,
        name_index=name_index,
        name_index_path=name_index_path,
        layout_baker=baker,
        partial_restore=partial_restore,
    )

    # Start the background mention worker on its own thread and connection
    # (transport-agnostic: both stdio and HTTP funnel through init). The flag is
    # the test suite's "background worker off" switch, so tests can drain the
    # queue synchronously without thread races.
    if os.environ.get("MYCELIUM_DISABLE_MENTION_WORKER") != "1":
        from .. import mention_worker  # local import: workers are optional

        mention_worker.start(data_dir)
    if os.environ.get("MYCELIUM_DISABLE_REVIEW_SWEEP") != "1":
        from .. import draft_review_runs

        draft_review_runs.start_sweeper()


def _seeded_prompt_texts() -> tuple[tuple[str, str, Callable[[], Path]], ...]:
    """Loop doctrines whose packaged defaults remain available after restart."""
    from ..agentloop import DOCTRINE_TYPE
    from ..docgen.config import DOCTRINE_NAME as DOCGEN_DOCTRINE
    from ..docgen.config import DocgenConfig
    from ..ingest.config import DOCTRINE_NAME as INGEST_DOCTRINE
    from ..ingest.config import IngestConfig
    from ..research.config import DOCTRINE_NAME as RESEARCH_DOCTRINE
    from ..research.config import ResearchConfig

    return (
        (
            DOCTRINE_TYPE,
            INGEST_DOCTRINE,
            lambda: Path(IngestConfig.from_env().doctrine_path),
        ),
        (
            DOCTRINE_TYPE,
            DOCGEN_DOCTRINE,
            lambda: Path(DocgenConfig.from_env().doctrine_path),
        ),
        (
            DOCTRINE_TYPE,
            RESEARCH_DOCTRINE,
            lambda: Path(ResearchConfig.from_env().doctrine_path),
        ),
    )


def _is_seeded(type: str, name: str) -> bool:
    """Whether startup seeds (type, name). Keys are compared as the store
    stores them — stripped."""
    key = (type.strip(), name.strip())
    return any(key == (t, n) for t, n, _ in _seeded_prompt_texts())


def _seed_prompt_texts() -> None:
    """Seed starter profiles once and the loop doctrines when absent, then
    bring untouched seeded texts up to this build's defaults and warn about
    saved texts that predate them (see `prompt_defaults`)."""
    from .. import ai_prompts, prompt_defaults, prompt_store
    from ..agentloop import DOCTRINE_TYPE

    try:
        documentation_profiles.seed_starters(_prompts_db())
    except Exception:
        logger.warning("could not seed documentation starter profiles", exc_info=True)

    for type, name, source in _seeded_prompt_texts():
        try:
            # Resolution inside the guard: `from_env` also parses that loop's
            # numeric tunables, and one malformed op cap must not stop a
            # server booting.
            prompt_store.save_if_absent(
                _prompts_db(),
                type=type,
                name=name,
                text=source().read_text(encoding="utf-8"),
                created_by="seed",
            )
        except Exception:
            logger.warning(
                "could not seed prompt text %s/%s", type, name, exc_info=True
            )

    for action in ai_prompts.ACTIONS:
        try:
            since = prompt_defaults.sync(
                _prompts_db(), DOCTRINE_TYPE, action, ai_prompts.shipped_text(action)
            )
        except Exception:
            logger.warning(
                "could not update the shipped default for %s", action, exc_info=True
            )
            continue
        if since is not None:
            logger.warning(
                "saved %s instructions predate the default this build ships "
                "(first seen %s); compare them in AI settings → Prompts",
                action,
                since,
            )


def _direction_entry(link_type: str) -> dict[str, list[str] | None] | None:
    direction = link_rules.LINK_DIRECTION.get(link_type)
    if direction is None:
        return None
    source_kinds, target_kinds = direction
    return {
        "source_kinds": None if source_kinds is None else sorted(source_kinds),
        "target_kinds": None if target_kinds is None else sorted(target_kinds),
    }


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


def _check_guideline_selection(
    guideline_set: str | None, document_type: str | None
) -> None:
    """Refuse a guideline set, or a document type within one, that nothing is
    stored under.

    Sets are not a registry to consult: they are prompt-store rows named
    `<set>/<slot>` (docs/GUIDELINE_SETS.md), so "does this set exist" is "are
    there live rows with that prefix" — answered from the same listing that
    names the alternatives back to the caller.

    A document type is only checkable once a set is named, since the template
    is a row of that set. Named together, both are checked here rather than
    left to fail deep inside a background run whose only report is an `error`
    column read minutes later.

    The listing comes from `guidelines.catalogue`, which is also what the
    generation loop resolves against — so a request this refuses is exactly a
    request the run could not have written, and vice versa.
    """
    from .. import guidelines

    if guideline_set is None:
        return

    catalogue = guidelines.catalogue(_prompts_db())
    if guideline_set not in catalogue:
        raise ValueError(
            f"unknown guideline set '{guideline_set}'; configured: {sorted(catalogue)}"
        )
    if document_type is None:
        return
    available = catalogue[guideline_set]
    if document_type not in available:
        raise ValueError(
            f"guideline set '{guideline_set}' has no template for document type "
            f"'{document_type}'; available: {available}"
        )


def _optional_name(value: str | None) -> str | None:
    """A caller-supplied optional name, normalized: blank is not a name."""
    return value.strip() or None if value is not None else None


@tool(role="writer", real_role=True)
def request_documentation(
    prompt: str,
    guideline_set: str | None = None,
    document_type: str | None = None,
    provider: Literal["claude", "openai"] | None = None,
    match_existing: bool = True,
) -> dict[str, Any]:
    """Request a background documentation run: generate one document from
    `prompt` and store it as a generated document.

    Writers and admins only — `real_role`, so the drafter equivalence does not
    apply. A drafter clears write gates because the wrapper redirects their
    writes onto a reviewable draft, and this tool sits outside that machinery:
    what it produces lands live and is served to readers as it stands.

    Returns immediately with the serialized run row (its `status` will be
    "running"); poll `get_documentation_run(run_id)` for the outcome and
    `get_generated_document(document_id)` for what it wrote. `guideline_set`
    picks the writing guidance (see `list_prompt_texts(type="guideline-set")`)
    and `document_type` the template within it; left out, they stay null on
    the row and the run resolves them. Raises when the active-run cap is
    reached (saved documentation active-run limit, default 2), when `guideline_set` is
    unknown, when `document_type` is not one that set can write, or when
    `prompt` is blank or longer than the saved prompt length limit.
    `provider` selects claude or openai; omitted uses saved documentation settings
    (default claude). The configured model is captured for writing and review.
    Use list_documentation_models for available choices.
    match_existing defaults to True; False disables matching an existing document.
    Returns {run row: id, prompt, guideline_set, document_type, provider, model, status,
    created_at, created_by, started_at, finished_at, outcome, document_id,
    error}."""
    from .. import auth as _auth
    from .. import doc_runs, docs_store
    from ..docgen import DocgenConfig

    text = prompt.strip()
    if not text:
        raise ValueError("prompt is required")
    max_chars = DocgenConfig.from_env().max_prompt_chars
    if len(text) > max_chars:
        raise ValueError(
            f"prompt is {len(text)} characters; the limit is {max_chars} "
            "(documentation prompt limit)"
        )

    guideline_set = _optional_name(guideline_set)
    document_type = _optional_name(document_type)
    _check_guideline_selection(guideline_set, document_type)

    principal = _auth.current_principal.get()
    created_by = principal.id if principal is not None else None
    run_id = doc_runs.start_run(
        prompt=text,
        guideline_set=guideline_set,
        document_type=document_type,
        created_by=created_by,
        conn=_drafts_db(),
        provider=provider,
        match_existing=match_existing,
    )
    row = require(
        docs_store.get_run(_drafts_db(), run_id), "documentation run just created"
    )
    return docs_store.serialize_run(row)


@tool(role="writer", real_role=True)
def revise_document(
    document_id: str,
    expected_revision: int,
    prompt: str,
    provider: Literal["claude", "openai"] | None = None,
) -> dict[str, object]:
    """Iterate on exactly the selected internal document version."""
    from .. import auth, doc_runs, docs_store
    from ..docgen.config import DocgenConfig

    text = prompt.strip()
    if not text:
        raise ValueError("prompt is required")
    if len(text) > DocgenConfig.from_env().max_prompt_chars:
        raise ValueError(
            "The revision instructions exceed the documentation prompt limit."
        )
    row = docs_store.require_revision(_drafts_db(), document_id, expected_revision)
    _check_guideline_selection(str(row["guideline_set"]), str(row["document_type"]))
    principal = auth.current_principal.get()
    run_id = doc_runs.start_run(
        prompt=text,
        guideline_set=str(row["guideline_set"]),
        document_type=str(row["document_type"]),
        created_by=principal.id if principal is not None else None,
        conn=_drafts_db(),
        provider=provider,
        target_document_id=document_id,
        expected_revision=expected_revision,
        match_existing=False,
    )
    return docs_store.serialize_run(
        require(docs_store.get_run(_drafts_db(), run_id), "new documentation run")
    )


@tool
def list_document_revisions(document_id: str) -> dict[str, object]:
    """List the stored versions of a document, newest first, without bodies."""
    from .. import docs_store

    if docs_store.get_document(_drafts_db(), document_id) is None:
        raise ValueError("generated document not found")
    return {
        "revisions": [
            docs_store.serialize_revision(row, include_body=False)
            for row in docs_store.list_revisions(_drafts_db(), document_id)
        ]
    }


@tool
def get_document_revision(document_id: str, revision: int) -> dict[str, object]:
    """Read an immutable version with grounding, review and generation backlink."""
    from .. import docs_store

    row = docs_store.get_revision(_drafts_db(), document_id, revision)
    if row is None:
        raise ValueError("generated document revision not found")
    result = docs_store.serialize_revision(row)
    delivery = (
        _drafts_db()
        .execute(
            "SELECT destination, target, path, reference, content_revision, created_at "
            "FROM generated_document_deliveries WHERE document_id = ? AND revision = ?",
            (document_id, revision),
        )
        .fetchone()
    )
    result["delivery"] = (
        None
        if delivery is None
        else {
            "destination": delivery["destination"],
            "coordinates": _json.loads(delivery["target"]),
            "path": delivery["path"],
            "reference": delivery["reference"],
            "content_revision": delivery["content_revision"],
            "created_at": delivery["created_at"],
        }
    )
    return result


@tool
def list_documentation_models() -> dict[str, object]:
    """List configured documentation providers and safe availability reasons."""
    from ..docgen.config import model_choices, resolve_provider

    return {"default_provider": resolve_provider(), "models": model_choices()}


@tool
def list_documentation_runs() -> dict[str, Any]:
    """List documentation runs, newest first, each with a derived `status`
    (queued/running/document_written/document_superseded/nothing_written/failed).
    A run whose page was replaced reports `document_superseded`, while its
    stored `outcome` remains `document_written`; the matching
    `document_superseded` boolean stays as explanatory detail.

    Each row carries `draft_chars` rather than the draft itself; fetch one run
    with get_documentation_run to read the text a refused run wrote.

    Returns {"runs": [run rows]}."""
    from .. import docs_store

    return {
        "runs": [
            docs_store.serialize_run(row) for row in docs_store.list_runs(_drafts_db())
        ]
    }


@tool
def get_documentation_run(run_id: str) -> dict[str, Any]:
    """Fetch one documentation run by id, including outcome, document_id,
    error, derived `status`, and `document_superseded`. A run whose page was
    replaced reports status `document_superseded`, not `document_written`,
    while its stored outcome remains `document_written`; the boolean stays as
    explanatory detail.

    A run the review gate turned down carries the draft it refused, as
    `draft_title` and `draft_body`, so the findings can be read against the
    text they quote. Both are null when no document was written.

    Returns the serialized run row. Raises for an unknown run_id."""
    from .. import docs_store

    row = docs_store.get_run(_drafts_db(), run_id)
    if row is None:
        raise ValueError(f"documentation run not found: {run_id}")
    return docs_store.serialize_run_detail(row)


@tool
def list_generated_documents() -> dict[str, Any]:
    """List generated documents, newest first, omitting each document body.

    Returns {"documents": [document summaries]}; get_generated_document returns
    the body."""
    from .. import docs_store

    return {
        "documents": [
            docs_store.serialize_document_summary(row)
            for row in docs_store.list_documents(_drafts_db(), limit=None)
        ]
    }


@tool
def get_generated_document(document_id: str) -> dict[str, Any]:
    """Fetch one generated document by id, including its body.

    Returns the serialized document row. Raises for an unknown document_id."""
    from .. import docs_store

    row = docs_store.get_document(_drafts_db(), document_id)
    if row is None:
        raise ValueError(f"generated document not found: {document_id}")
    return docs_store.serialize_document(row)


@tool(role="writer", real_role=True)
def deliver_document(
    document_id: str,
    destination: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Publish a selected internal version through its GitHub review flow.

    Existing documents reuse recorded repository coordinates and path. A receipt
    belongs to the captured immutable version even when generation advances the
    document while GitHub is processing the publication.
    """
    from .. import docs_store
    from ..docgen import destinations

    with destinations.publication_lock(document_id):
        row = docs_store.get_document(_drafts_db(), document_id)
        if row is None:
            raise ValueError("generated document not found")
        revision = (
            int(row["current_revision"])
            if expected_revision is None
            else expected_revision
        )
        row = docs_store.require_revision(_drafts_db(), document_id, revision)
        try:
            configured, binding = destinations.publishing_destination(row, destination)
        except destinations.DestinationError as exc:
            raise ValueError(str(exc)) from None
        document = destinations.DeliveryDocument(
            id=str(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            body=str(row["body"]),
            guideline_set=str(row["guideline_set"]),
            document_type=str(row["document_type"]),
            statement_ids=tuple(_json.loads(row["statement_ids"])),
            delivered_path=str(row["delivery_path"])
            if row["delivery_path"] is not None
            else None,
            delivered_content_revision=str(row["delivery_content_revision"])
            if row["delivery_content_revision"] is not None
            else None,
            revision_source_content_revision=str(
                row["revision_source_content_revision"]
            )
            if row["revision_source_content_revision"] is not None
            else None,
        )
        try:
            delivery = destinations.deliver_document(configured, document)
        except destinations.DestinationError as exc:
            raise ValueError(str(exc)) from None
        docs_store.record_delivery(
            _drafts_db(),
            document_id,
            destination=delivery.destination,
            path=delivery.path,
            reference=delivery.reference,
            content_revision=delivery.content_revision,
            target=destinations.target_identity(configured),
            revision=revision,
            binding=binding,
        )
        return {**delivery.serialize(), "revision": revision}


@tool
def list_documentation_destinations() -> dict[str, Any]:
    """List configured documentation destinations by generic identity.

    Returns no credential and no credential environment variable name.
    """
    from ..docgen import destinations

    try:
        configured = destinations.load_destinations()
    except destinations.DestinationError as exc:
        raise ValueError(str(exc)) from None
    return {
        "destinations": [
            {
                "name": destination.name,
                "type": destination.type,
                "path_template": destination.path_template,
                "coordinates": destinations.destination_coordinates(destination),
            }
            for destination in configured.values()
        ]
    }


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


@tool
def list_link_types() -> list[dict[str, Any]]:
    """List the statement→statement link types known to the substrate.

    Returns `[{link_type, description, usage_count, direction?}]` sorted
    alphabetically. `description` comes from the
    `statement_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_link_type`); empty string for any type that's
    in the database but has no glossary entry. `usage_count` is the
    number of statement_links rows currently carrying this type — 0
    means the type is defined but not yet used anywhere.

    Reach for this whenever a `get_statements` or `search_statements`
    response shows a `link_type` you're not sure about. Vocabulary is
    open — new types may appear in `in_use` results without a glossary
    entry. Reuse before inventing.

    ─── `when` expressions on edges ──────────────────────────────────
    A link may carry a `when` field that conditions whether the edge
    fires. The grammar is a small tree:

      leaf      = {"statement_id": "stm_…"}
      internal  = {"op": "and", "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "or",  "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "not", "of": [<expr>]}               # exactly 1 child

    A leaf is satisfied when the referenced statement (a `state`-kind
    statement, by convention) currently holds. `and`/`or` combine
    children boolean-fashion; `not` inverts its single child — the edge
    fires when that child does NOT hold. Absence of a `when` field means
    the edge is unconditional — it fires whenever the source fires.

    Example — a rejection trigger that only fires when both a template
    is configured AND the outgoing edge conditions failed:

      {"op": "and", "of": [
        {"statement_id": "stm_template_configured"},
        {"statement_id": "stm_edge_conditions_failed"}
      ]}

    Example — a sharing guard that fires only when the result has NOT
    already been shared:

      {"op": "not", "of": [{"statement_id": "stm_result_already_shared"}]}

    To follow what a `when` leaf refers to, call `get_statements([id])` on
    the leaf's `statement_id` — same pattern as chasing a link target.
    """
    counts = store.count_statement_links_by_type(_db())
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_statement_link_type_glossary(_db())
    }
    all_types = sorted(set(counts) | set(glossary))
    rows: list[dict[str, Any]] = []
    for t in all_types:
        row: dict[str, Any] = {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        direction = _direction_entry(t)
        if direction is not None:
            row["direction"] = direction
        rows.append(row)
    return rows


@tool
def list_statement_kinds() -> list[dict[str, Any]]:
    """List the statement `kind` values known to the substrate.

    Returns `[{kind, description, when_to_use, usage_count}]` sorted
    alphabetically. `description` and `when_to_use` come from the
    `statement_kind_glossary` table (DB-backed, editable via the
    website or `upsert_statement_kind`); empty strings for kinds
    present on statements but missing from the glossary. `usage_count`
    is the number of statements currently carrying that kind — 0
    means the kind is defined but not yet used.

    Use this when you need to know what shape of claim to write —
    each `kind` enforces a different phrasing catalog at the
    substrate boundary (event / state / capability / rule / property
    for descriptive content; procedure / action / check / cause for
    prescriptive how-to and diagnostic content). Vocabulary is open
    — new kinds run the event phrasing catalog as a baseline.
    """
    glossary_rows = store.list_statement_kind_glossary(_db())
    glossary = {
        r["kind"]: (r["description"], r["when_to_use"] or "") for r in glossary_rows
    }
    counts = store.count_statements_by_kind_all(_db())
    all_kinds = sorted(set(counts) | set(glossary))
    return [
        {
            "kind": k,
            "description": glossary.get(k, ("", ""))[0],
            "when_to_use": glossary.get(k, ("", ""))[1],
            "usage_count": counts.get(k, 0),
        }
        for k in all_kinds
    ]


@tool
def list_entity_link_types() -> list[dict[str, Any]]:
    """List entity→entity link types known to the substrate.

    Returns `[{link_type, description, usage_count}]` sorted
    alphabetically. `description` comes from the
    `entity_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_entity_link_type`). `usage_count` is the number
    of entity_links rows currently carrying this type.
    """
    counts = store.count_entity_links_by_type(_db())
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_entity_link_type_glossary(_db())
    }
    all_types = sorted(set(counts) | set(glossary))
    return [
        {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        for t in all_types
    ]


@tool
def upsert_statement_kind(
    kind: str, description: str, when_to_use: str | None = None
) -> dict[str, str]:
    """Create or update a statement-kind glossary entry.

    The `kind` value is the primary key — pass the same `kind` to
    update an existing entry's `description` / `when_to_use`. Pass a
    new `kind` to add a new entry. Authoring this entry does NOT
    register the kind for phrasing validation — phrasing rules live in
    `phrasing.py` and apply by name; an entry here is documentation,
    not enforcement.

    Returns `{kind}` on success.
    """
    if not kind or not kind.strip():
        raise ValueError("kind cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_statement_kind_glossary(_db(), kind, description, when_to_use)
    return {"kind": kind}


@tool
def delete_statement_kind(kind: str) -> dict[str, str]:
    """Remove a statement-kind glossary entry.

    Does not affect any statement records that currently carry this
    kind — they remain valid in the substrate; only the glossary
    documentation goes away. Idempotent: deleting a missing entry is
    a no-op.

    Returns `{kind}`.
    """
    with store.transaction(_db()):
        store.delete_statement_kind_glossary(_db(), kind)
    return {"kind": kind}


@tool
def upsert_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update a statement→statement link-type glossary entry.

    The `link_type` value is the primary key. Authoring this entry
    does NOT register the type for any validation; it is documentation
    that surfaces via `list_link_types`.

    Returns `{link_type}`.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_statement_link_type_glossary(_db(), link_type, description)
    return {"link_type": link_type}


@tool
def delete_link_type(link_type: str) -> dict[str, str]:
    """Remove a statement→statement link-type glossary entry.

    Does not affect any link rows that currently carry this type —
    they remain valid in the substrate; only the documentation goes
    away. Idempotent.

    Returns `{link_type}`.
    """
    with store.transaction(_db()):
        store.delete_statement_link_type_glossary(_db(), link_type)
    return {"link_type": link_type}


#: Provenance values a caller may assert. `seed` is the migration's own tag and
#: is not assertable; a curator re-asserting an auto alias overwrites it, which
#: is how a reviewed alias stops being an automatic one.
ALIAS_PROVENANCE = ("curator", "auto", "auto:low-confidence")


@tool
def upsert_link_type_alias(
    link_type: str,
    alias: str,
    provenance: str = "curator",
    score: float | None = None,
    direction: str = "forward",
) -> dict[str, Any]:
    """Create or update an alternative phrasing for a canonical link type.

    The alias is vocabulary only: links still store the canonical
    `link_type`. The same alias may be registered under more than one type.

    `direction` says how the phrasing reads the edge: `forward` runs it left
    to right off the alias ("A contains B"), `reverse` names the relation
    from the far side ("A is part of B" puts B on the edge's source side).

    The alias set records where a phrasing came from: `curator` for a
    hand-authored one, or `auto`/`auto:low-confidence` with the deciding cosine
    for one an automatic resolver proposed; a later curator write overwrites
    both fields.

    Returns
    `{link_type, alias, provenance, score, direction, created}` with the
    normalized alias and whether this call created it.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not alias or not alias.strip():
        raise ValueError("alias cannot be empty")
    if provenance not in ALIAS_PROVENANCE:
        raise ValueError(
            f"provenance must be one of {', '.join(ALIAS_PROVENANCE)}: {provenance!r}"
        )
    if score is not None and not -1.0 <= float(score) <= 1.0:
        raise ValueError(f"score must be a cosine in [-1, 1]: {score!r}")
    # An automatic absorption with no score is invisible to the audit sweep the
    # provenance tag exists for.
    if provenance != "curator" and score is None:
        raise ValueError(f"provenance {provenance!r} requires a score")
    normalized = store.normalize_alias(alias)
    with store.transaction(_db()):
        created = store.upsert_link_type_alias(
            _db(),
            link_type,
            normalized,
            provenance=provenance,
            score=score,
            direction=direction,
        )
    return {
        "link_type": link_type,
        "alias": normalized,
        "provenance": provenance,
        "score": score,
        "direction": direction,
        "created": created,
    }


@tool
def delete_link_type_alias(link_type: str, alias: str) -> dict[str, Any]:
    """Delete one alternative phrasing from a canonical link type.

    Reach for this to retire vocabulary without changing links already stored
    under the canonical type. Idempotent. Returns `{link_type, alias, deleted}`
    with the normalized alias.
    """
    normalized = store.normalize_alias(alias)
    with store.transaction(_db()):
        deleted = store.delete_link_type_alias(_db(), link_type, normalized)
    return {"link_type": link_type, "alias": normalized, "deleted": deleted}


@tool
def list_link_type_aliases(
    link_type: str | None = None,
) -> list[dict[str, Any]]:
    """List link-type phrasings, optionally for one canonical link type.

    Reach for this to inspect accepted vocabulary. Returns
    `[{link_type, alias, provenance, score, direction}]`;
    hand-authored and seeded aliases have `score: null`.
    """
    return [
        {
            "link_type": row["link_type"],
            "alias": row["alias"],
            "provenance": row["provenance"],
            "score": row["score"],
            "direction": row["direction"],
        }
        for row in store.list_link_type_aliases(_db(), link_type)
    ]


@tool
def upsert_entity_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update an entity→entity link-type glossary entry.

    The `link_type` value is the primary key. Entity link types live
    in a separate namespace from statement link types.

    Returns `{link_type}`.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_entity_link_type_glossary(_db(), link_type, description)
    return {"link_type": link_type}


@tool
def delete_entity_link_type(link_type: str) -> dict[str, str]:
    """Remove an entity→entity link-type glossary entry.

    Does not affect any entity_links rows that currently carry this
    type. Idempotent.

    Returns `{link_type}`.
    """
    with store.transaction(_db()):
        store.delete_entity_link_type_glossary(_db(), link_type)
    return {"link_type": link_type}


@tool(role="reader")
def report_knowledge_gap(text: str) -> dict[str, Any]:
    """Flag a gap, inconsistency, or unclear area in the knowledge base
    for a human curator to review.

    Free-form text body; the reporter writes whatever's most useful —
    a missing topic, a contradiction between two statements, an entity
    that looks incomplete, a typo, a stale claim. If the report
    references a specific entity or statement, include the id in the
    text so the reviewer can jump to it.

    Open reports surface in the UI's Gaps page until a human marks
    them resolved or dismissed; nothing is auto-pruned.

    Returns the assigned `gap_id`.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is required")

    with store.transaction(_db()):
        gap_id = store.create_knowledge_gap(_db(), text)
    return {"gap_id": gap_id}


# --- prompt-text tools ------------------------------------------------------
# Steering texts (doctrines, prompt preambles, guideline sets) as editable
# rows — see `prompt_store`. Deliberately named outside `_MUTATION_PREFIXES`:
# prompt texts are instance configuration, so an edit takes effect directly
# and never queues onto a draft. `retire_` carries the admin gate that the
# `delete_` prefix would otherwise have derived, and because an edit here
# lands live, the write tools re-check the caller's REAL role so the
# drafter-equivalence in `auth.principal_satisfies` can't stand in for one.


def _actor_id() -> str | None:
    from .. import auth as _auth

    principal = _auth.current_principal.get()
    return principal.id if principal is not None else None


@tool(role="writer", real_role=True)
def save_prompt_text(
    type: str, name: str, text: str, expected_version: int | None = None
) -> dict[str, object]:
    """Save a steering text; optional expected_version rejects stale edits.

    Guideline names use profile/slot. Individual saves support creating a
    profile in stages; use save_documentation_profile for one atomic edit.
    """
    return documentation_profiles.save_text(
        type, name, text, _prompt_principal(), revision=expected_version
    ).model_dump()


@tool
def get_prompt_text(type: str, name: str) -> dict[str, Any]:
    """Fetch the current text stored under (type, name), body included.

    Returns the row {id, type, name, text, version, deleted, created_at,
    created_by}. Raises when the name has never been saved or was retired."""
    from .. import prompt_store

    row = prompt_store.latest(_prompts_db(), type, name)
    if row is None:
        raise ValueError(f"prompt text not found: {type}/{name}")
    return prompt_store.serialize(row)


@tool
def list_prompt_texts(type: str | None = None) -> dict[str, Any]:
    """List the prompt texts currently in force, optionally narrowed to one
    `type`. Retired names are omitted.

    Bodies are left out — use `get_prompt_text` for one. Returns
    {"prompt_texts": [{type, name, version, chars, created_at, created_by}]}.
    """
    from .. import prompt_store

    return {
        "prompt_texts": [
            prompt_store.serialize_summary(row)
            for row in prompt_store.list_current(_prompts_db(), type)
        ]
    }


@tool
def list_prompt_text_versions(type: str, name: str) -> dict[str, Any]:
    """List every version ever saved under (type, name), newest first.

    The store is append-only, so this is the full edit history — including
    the tombstone version left by `retire_prompt_text`. Bodies included.
    Returns {"versions": [prompt-text rows]}."""
    from .. import prompt_store

    return {
        "versions": [
            prompt_store.serialize(row)
            for row in prompt_store.history(_prompts_db(), type, name)
        ]
    }


@tool(role="admin", real_role=True)
def retire_prompt_text(
    type: str, name: str, expected_version: int | None = None
) -> dict[str, Any]:
    """Retire a text, preserving history. Packaged loop doctrines remain protected.

    Documentation starters are user-owned; only an active default's final
    template is protected until another default is selected. Pass expected_version
    to reject retirement when another caller has changed the text.
    """
    if _is_seeded(type, name):
        raise ValueError(
            f"prompt text '{type}/{name}' is seeded at startup and cannot be "
            f"retired: the next start would re-seed the packaged default at a "
            f"new version. Edit it with save_prompt_text instead."
        )
    retired = documentation_profiles.retire_text(
        type, name, _prompt_principal(), expected_version=expected_version
    )
    return {"retired": retired}


def _prompt_principal() -> AuthPrincipal:
    from .. import auth

    return auth.current_principal.get() or auth.LOCAL_ADMIN


@tool
def list_documentation_profiles() -> dict[str, object]:
    """List documentation profiles, readiness and editing permissions."""
    return documentation_profiles.view(_prompt_principal()).model_dump()


@tool
def get_documentation_profile(name: str) -> dict[str, object]:
    """Read a profile and its revision for an atomic save."""
    return documentation_profiles.read(name).model_dump()


@tool(role="writer", real_role=True)
def save_documentation_profile(
    name: str,
    revision: str,
    guidance: str = "",
    exposure: str = "",
    templates: list[documentation_profiles.Template] | None = None,
) -> dict[str, object]:
    """Save a complete profile atomically. Removing existing slots requires admin."""
    body = documentation_profiles.SaveProfile.model_validate(
        {
            "revision": revision,
            "guidance": guidance,
            "exposure": exposure,
            "templates": templates or [],
        }
    )
    return documentation_profiles.save(name, body, _prompt_principal()).model_dump()


@tool(role="admin", real_role=True)
def retire_documentation_profile(name: str, revision: str) -> dict[str, object]:
    """Retire a profile while preserving history; configured defaults are protected."""
    return documentation_profiles.retire(
        name, revision, _prompt_principal()
    ).model_dump()


@tool(role="writer", real_role=True)
def restore_prompt_text(
    type: str, name: str, version: int, expected_version: int
) -> dict[str, object]:
    """Restore an earlier text as a new version without overwriting history."""
    return documentation_profiles.restore_text(
        documentation_profiles.RestoreText(
            type=type, name=name, version=version, revision=expected_version
        ),
        _prompt_principal(),
    ).model_dump()


# --- draft management tools -----------------------------------------------
# These manipulate the draft queue itself rather than the substrate.
# Their names don't start with substrate mutation prefixes, so the @tool
# wrapper doesn't auto-attach a `draft_id` parameter — they accept one
# as a normal positional/keyword arg referring to the draft they operate
# on. `submit_draft` requires writer rank, which a drafter satisfies via
# the role-equivalence in auth.principal_satisfies.


@tool
def submit_draft(draft_id: str | None = None) -> dict[str, Any]:
    """Submit a draft for curator review.

    `draft_id` is optional — when omitted, submits the caller's
    currently-open auto-draft (the one their MCP session has been
    accumulating ops into). After submission the draft can no longer
    accept new ops via tool calls; the curator either approves it
    (replays the ops against the substrate) or rejects it.

    Returns the submitted draft's id and final op count.
    """
    from .. import auth as _auth
    from .. import drafts_store

    principal = _auth.current_principal.get()

    if draft_id is None:
        if principal is None:
            raise ValueError("no draft_id given and no caller identity")
        session_id = _auth.current_session_id.get() or f"actor:{principal.id}"
        row = drafts_store.find_open_session_draft(
            _drafts_db(), session_id, principal.id
        )
        if row is None:
            raise ValueError("no open draft to submit for this caller")
        draft_id = row["id"]
    else:
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None:
            raise ValueError(f"draft '{draft_id}' not found")
        if drafts_store.status_for(row) != "open":
            raise ValueError(
                f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
                f"only open drafts can be submitted"
            )

    _submit_for_review(draft_id)
    ops = drafts_store.list_ops(_drafts_db(), draft_id)
    return {"draft_id": draft_id, "op_count": len(ops)}


def _submit_for_review(draft_id: str) -> None:
    from .. import draft_review_runs, drafts_store

    with store.transaction(_drafts_db()):
        drafts_store.set_submitted(_drafts_db(), draft_id)
    draft_review_runs.on_submitted(draft_id)


def _auto_submit(draft_id: str) -> bool:
    """Submit a model-produced draft while internal review is on, so it reaches
    the reviewer instead of waiting for someone to submit it. With review off
    the draft stays open for a person to curate."""
    from .. import draft_review_runs, draft_review_settings, drafts_store

    try:
        if draft_review_runs.mode() == "off":
            return False
    except draft_review_settings.Unavailable:
        return False
    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None or drafts_store.status_for(row) != "open":
        return False
    if not drafts_store.list_ops(_drafts_db(), draft_id):
        return False
    _submit_for_review(draft_id)
    return True


@tool(role="writer", real_role=True)
def request_draft_review(draft_id: str, rerun: bool = False) -> dict[str, JsonValue]:
    """Start internal GPT review, or return its latest run; rerun starts a new attempt.

    Requires an identified curator. Mode off refuses requests; configuration and
    execution failures remain visible on the draft's review_assessment.
    """
    from .. import draft_review_runs

    _identified_principal()
    return draft_review_runs.start(draft_id, rerun=rerun).model_dump(mode="json")


@tool
def get_draft_review_run(run_id: str) -> dict[str, JsonValue]:
    """Inspect an internal review attempt, including failure and staleness."""
    from .. import draft_review_store

    return draft_review_store.get(_drafts_db(), run_id).model_dump(mode="json")


@tool(role="drafter")
def set_draft_review_evidence(
    draft_id: str, evidence: str, expected_revision: int
) -> dict[str, JsonValue]:
    """Replace evidence supplied by the draft creator and invalidate old assessments.

    Supply source excerpts, change descriptions, or concrete supporting facts,
    up to 30000 characters. URLs alone do not provide their contents.
    """
    from .. import drafts_store

    principal = _identified_principal()
    if len(evidence) > 30000:
        raise ValueError("review evidence exceeds 30000 characters")
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        if row["created_by"] != principal.id:
            from .. import auth as _auth

            raise _auth.RoleRequired(
                "only the draft creator can supply review evidence"
            )
        drafts_store._check_revision(row, expected_revision)
        if row["review_evidence"] != evidence:
            conn.execute(
                "UPDATE drafts SET review_evidence = ?, revision = revision + 1 "
                "WHERE id = ?",
                (evidence, draft_id),
            )
    return get_draft(draft_id)


@tool
def list_my_drafts() -> list[dict[str, Any]]:
    """List drafts created by the calling principal, newest first.

    Useful for an agent to inspect what it queued in earlier sessions
    or check on the review state of submitted work.
    """
    from .. import auth as _auth
    from .. import drafts_store

    principal = _auth.current_principal.get()
    creator = principal.id if principal is not None else None
    rows = drafts_store.list_drafts_by_creator(_drafts_db(), creator)
    return [drafts_store.serialize_draft(r) for r in rows]


_DRAFT_STATUS_VALUES = (
    "all",
    "open",
    "submitted",
    "approved",
    "rejected",
    "withdrawn",
)


@tool(role="writer", real_role=True)
def list_drafts(
    status: str = "all", created_by: str | None = None
) -> list[dict[str, Any]]:
    """List *every* draft across all creators, newest first (curators only).

    Unlike `list_my_drafts` (scoped to the caller), this returns the whole
    review queue so a curator can discover work awaiting review and then
    `get_draft(<id>)` to inspect the queued ops and review assessment. Each
    entry carries an `op_count` and omits review evidence and assessment.
    Filter with `status`: all / open / submitted / approved / rejected /
    withdrawn, and with `created_by`: one creator's principal id.

    Requires a real writer or admin role — same bar as approving or
    rejecting a draft. Drafters (whose writes get redirected into their own
    draft) do not pass, so they can't enumerate other people's drafts.
    """
    from .. import auth as _auth
    from .. import drafts_store

    # The role gate is the decorator's (`real_role=True`, so a drafter does
    # not clear it). What remains here is the identity requirement: the
    # review queue spans every creator, so an anonymous caller has no
    # standing to read it even where the wrapper's gate stays out of the way.
    principal = _auth.current_principal.get()
    if principal is None:
        raise PermissionError(
            "tool 'list_drafts' requires an identified caller; "
            "use list_my_drafts to see your own drafts"
        )
    if status not in _DRAFT_STATUS_VALUES:
        raise ValueError("status must be one of: " + ", ".join(_DRAFT_STATUS_VALUES))

    conn = _drafts_db()
    rows = drafts_store.list_drafts(conn, status=status)
    counts = drafts_store.count_ops_by_draft(conn)
    out = []
    for r in rows:
        if created_by is not None and r["created_by"] != created_by:
            continue
        d = drafts_store.serialize_draft(r)
        del d["review_evidence"], d["review_assessment"]
        d["op_count"] = counts.get(r["id"], 0)
        out.append(d)
    return out


@tool
def get_draft(draft_id: str) -> dict[str, Any]:
    """Return a draft and its queued ops, in seq order.

    Anyone with read access can fetch any draft — drafts are intended
    for curator review so visibility is broad. The shape mirrors the
    HTTP `/api/drafts/<id>` response, plus `missing`: always present,
    empty when the draft resolved, and `[draft_id]` when no draft
    carries that id (an id that was never minted, or a draft already
    applied and swept).
    """
    from .. import drafts_store

    row, ops = drafts_store.get_draft_snapshot(_drafts_db(), draft_id)
    if row is None:
        return {"id": draft_id, "missing": [draft_id]}
    return {**drafts_store.serialize_draft(row, ops=ops), "missing": []}


class DraftSourceInput(TypedDict):
    repository: str
    pull_request: int
    merged_commit: str
    workflow_run_id: int
    workflow_run_attempt: int


class DraftMutationReceipt(TypedDict):
    draft_id: str
    operation_ref: str
    revision: int


def _identified_principal():
    from .. import auth as _auth

    principal = _auth.current_principal.get()
    if principal is None:
        raise _auth.RoleRequired("draft source operations require an identified caller")
    return principal


def _require_mutable_draft(draft_id: str):
    from .. import drafts_store

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        raise ValueError(f"cannot modify operations on a {status} draft")
    if drafts_store.active_application(_drafts_db(), draft_id) is not None:
        raise drafts_store.ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )
    return row


@tool(role="drafter")
def attach_draft_source(
    draft_id: str,
    source: DraftSourceInput,
    expected_revision: int | None = None,
) -> dict[str, JsonValue]:
    """Attach complete PR and workflow evidence to the caller's draft."""
    from .. import drafts_store

    principal = _identified_principal()
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        if row["created_by"] != principal.id:
            from .. import auth as _auth

            raise _auth.RoleRequired(
                "draft source evidence may only be set by its creator"
            )
        try:
            drafts_store.set_source(
                conn, draft_id, source, expected_revision=expected_revision
            )
        except sqlite3.IntegrityError as ex:
            existing = drafts_store.find_draft_by_source(conn, principal.id, source)
            owner = existing["id"] if existing is not None else "another draft"
            detail = f"source evidence already belongs to draft '{owner}'"
            raise ValueError(detail) from ex
    return get_draft(draft_id)


@tool(role="drafter")
def find_my_draft_by_source(source: DraftSourceInput) -> dict[str, JsonValue]:
    """Locate the caller's draft from its complete PR workflow identity."""
    from .. import drafts_store

    principal = _identified_principal()
    row = drafts_store.find_draft_by_source(_drafts_db(), principal.id, source)
    if row is None:
        return {"draft": None}
    return {"draft": get_draft(row["id"])}


@tool(role="writer", real_role=True)
def revise_draft_operation(
    draft_id: str,
    operation_ref: str,
    payload: dict[str, JsonValue],
    expected_revision: int | None = None,
) -> DraftMutationReceipt:
    """Replace one operation payload using its stable reference."""
    from .. import drafts_store

    conn = _drafts_db()
    with store.transaction(conn):
        _require_mutable_draft(draft_id)
        revision = drafts_store.update_op_payload_by_ref(
            conn,
            draft_id,
            operation_ref,
            payload,
            expected_revision=expected_revision,
        )
    if revision is None:
        raise ValueError(f"operation '{operation_ref}' not found in draft '{draft_id}'")
    return {"draft_id": draft_id, "operation_ref": operation_ref, "revision": revision}


@tool(role="writer", real_role=True)
def strike_draft_operation(
    draft_id: str,
    operation_ref: str,
    expected_revision: int | None = None,
) -> DraftMutationReceipt:
    """Remove one operation using its stable reference."""
    from .. import drafts_store

    conn = _drafts_db()
    with store.transaction(conn):
        _require_mutable_draft(draft_id)
        revision = drafts_store.remove_op_by_ref(
            conn,
            draft_id,
            operation_ref,
            expected_revision=expected_revision,
        )
    if revision is None:
        raise ValueError(f"operation '{operation_ref}' not found in draft '{draft_id}'")
    return {"draft_id": draft_id, "operation_ref": operation_ref, "revision": revision}


@tool
def discard_draft_op(
    draft_id: str, seq: int, expected_revision: int | None = None
) -> dict[str, Any]:
    """Remove a queued op from an open draft by its seq number.

    Lets a drafter self-correct a mistake without abandoning the whole
    draft. The op's seq stays burned — remaining ops keep their original
    sequence numbers (no renumbering) so any external references to a
    `(draft_id, seq)` pair stay stable.
    """
    from .. import drafts_store

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    if drafts_store.status_for(row) != "open":
        raise ValueError(
            f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
            f"can't modify ops on a non-open draft"
        )
    with store.transaction(_drafts_db()):
        revision = drafts_store.remove_op(
            _drafts_db(), draft_id, seq, expected_revision=expected_revision
        )
    if revision is None:
        raise ValueError(f"no op with seq {seq} in draft '{draft_id}'")
    return {
        "draft_id": draft_id,
        "seq": seq,
        "removed": True,
        "revision": revision,
    }


class KnowledgePrecondition(TypedDict):
    kind: Literal["entity", "statement"]
    id: str
    fingerprint: str


class DraftOperationFinding(TypedDict):
    operation_ref: str
    kind: str
    finding: str


class DraftReviewRecord(TypedDict):
    review_id: str
    draft_id: str
    outcome: Literal["accepted", "refined", "rejected", "needs_context"]
    rationale: str
    draft_revision: int
    knowledge_preconditions: list[KnowledgePrecondition]
    unresolved_questions: list[str]
    reviewed_at: str
    reviewed_by: str


class DraftReviewInspection(TypedDict):
    draft: dict[str, JsonValue]
    draft_revision: int
    knowledge_preconditions: list[KnowledgePrecondition]
    operation_findings: list[DraftOperationFinding]
    unresolved: bool
    reviews: list[DraftReviewRecord]
    applications: list[dict[str, JsonValue]]


class ReviewedApplicationReceipt(TypedDict):
    application_id: str
    applied: int
    skipped: int
    results: list[dict[str, JsonValue]]
    recovered: NotRequired[bool]


class DraftCorrectionReceipt(TypedDict):
    draft_id: str
    operation_ref: str
    seq: int
    revision: int


def _payload_knowledge_ids(
    value: JsonValue,
) -> tuple[set[str], set[str], set[str]]:
    entities: set[str] = set()
    statements: set[str] = set()
    names: set[str] = set()

    def visit(item: JsonValue) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            if item.startswith("ent_"):
                entities.add(item)
            elif item.startswith("stm_"):
                statements.add(item)
            elif item.startswith("nam_"):
                names.add(item)

    visit(value)
    return entities, statements, names


def _fingerprint(value: JsonValue) -> str:
    encoded = _json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


# Only these operations recompute mentions on existing statements; a statement
# that merely mentions an entity the draft touches is not affected otherwise.
_MENTION_REMAPPING_OPERATIONS = frozenset(
    {"merge_entities", "move_name", "rename_name", "delete_name", "delete_entity"}
)


def _name_owner_ids(name_ids: set[str]) -> set[str]:
    owners: set[str] = set()
    for name_id in name_ids:
        row = store.get_name_by_id(_db(), name_id)
        if row is not None:
            owners.add(row["entity_id"])
    return owners


def _named_entity_ids(
    kind: str, payload: dict, all_names: list[sqlite3.Row]
) -> set[str]:
    entity_ids: set[str] = set()
    texts: list[str] = []
    if isinstance(payload.get("text"), str):
        texts.append(payload["text"])
    texts.extend(
        item["text"]
        for item in payload.get("statements", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )
    for name_row in all_names:
        if any(mentions.text_contains_name(text, name_row["text"]) for text in texts):
            entity_ids.add(name_row["entity_id"])
    names: list[str] = []
    if kind == "upsert_entity" and isinstance(payload.get("name"), str):
        names.append(payload["name"])
    if kind == "upsert_entities":
        names.extend(
            item["name"]
            for item in payload.get("entities", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
    for name in names:
        row = store.get_name_by_text(_db(), name)
        if row is not None:
            entity_ids.add(row["entity_id"])
    return entity_ids


def _knowledge_preconditions(ops: list[sqlite3.Row]) -> list[KnowledgePrecondition]:
    entity_ids: set[str] = set()
    remapped_entity_ids: set[str] = set()
    statement_ids: set[str] = set()
    all_names = store.list_all_names(_db())
    for op in ops:
        payload = _json.loads(op["payload_json"])
        entities, statements, names = _payload_knowledge_ids(payload)
        targeted = entities | _name_owner_ids(names)
        entity_ids.update(targeted)
        entity_ids.update(_named_entity_ids(op["kind"], payload, all_names))
        statement_ids.update(statements)
        if op["kind"] in _MENTION_REMAPPING_OPERATIONS:
            remapped_entity_ids.update(targeted)

    for entity_id in remapped_entity_ids:
        for name_row in store.get_names_by_entity(_db(), entity_id):
            statement_ids.update(
                store.statements_mentioning_name(_db(), name_row["id"])
            )

    out: list[KnowledgePrecondition] = []
    for entity_id in sorted(entity_ids):
        entity = get_entity(entity_id)
        out.append(
            {"kind": "entity", "id": entity_id, "fingerprint": _fingerprint(entity)}
        )
    ordered_statement_ids = sorted(statement_ids)
    statements = get_statements(ordered_statement_ids)["statements"]
    statements_by_id = {statement["id"]: statement for statement in statements}
    for statement_id in ordered_statement_ids:
        hydrated = statements_by_id.get(statement_id)
        statement: JsonValue = (
            {"statements": [hydrated], "missing": []}
            if hydrated is not None
            else {"statements": [], "missing": [statement_id]}
        )
        out.append(
            {
                "kind": "statement",
                "id": statement_id,
                "fingerprint": _fingerprint(statement),
            }
        )
    return out


def _review_knowledge_preconditions(
    ops: list[sqlite3.Row], expected: list[KnowledgePrecondition]
) -> list[KnowledgePrecondition]:
    """Include supporting records actually inspected beyond operation targets."""
    current = {
        (item["kind"], item["id"]): item for item in _knowledge_preconditions(ops)
    }
    for item in expected:
        key = (item["kind"], item["id"])
        if key in current:
            continue
        value = (
            get_entity(item["id"])
            if item["kind"] == "entity"
            else get_statements([item["id"]])
        )
        current[key] = {
            "kind": item["kind"],
            "id": item["id"],
            "fingerprint": _fingerprint(value),
        }
    return [current[key] for key in sorted(current)]


def _batch_nested_parameter_findings(payload: dict) -> list[str]:
    findings: list[str] = []
    allowed = set(BatchStatementSpec.__annotations__)
    for index, item in enumerate(payload.get("statements", [])):
        if not isinstance(item, dict):
            continue
        unknown = sorted(set(item) - allowed)
        if unknown:
            findings.append(
                f"unknown_parameters:statements[{index}]." + ",".join(unknown)
            )
        for path, link_allowed in (
            ("links", set(LinkSpec.__annotations__)),
            ("incoming_links", set(IncomingLinkSpec.__annotations__)),
        ):
            for link_index, link in enumerate(item.get(path, [])):
                if isinstance(link, dict):
                    unknown_link = sorted(set(link) - link_allowed)
                    if unknown_link:
                        findings.append(
                            f"unknown_parameters:statements[{index}]."
                            f"{path}[{link_index}]." + ",".join(unknown_link)
                        )
    return findings


def _nested_parameter_findings(kind: str, payload: dict) -> list[str]:
    specs: list[tuple[str, JsonValue, set[str]]] = []
    if kind in ("add_links", "remove_links"):
        specs.append(("links", payload.get("links", []), set(EdgeSpec.__annotations__)))
    elif kind in ("add_entity_links", "remove_entity_links"):
        specs.append(
            ("links", payload.get("links", []), set(EntityEdgeSpec.__annotations__))
        )
    elif kind == "upsert_statement":
        specs.extend(
            (
                ("links", payload.get("links", []), set(LinkSpec.__annotations__)),
                (
                    "incoming_links",
                    payload.get("incoming_links", []),
                    set(IncomingLinkSpec.__annotations__),
                ),
            )
        )
    findings: list[str] = []
    for path, items, allowed in specs:
        if isinstance(items, list):
            for index, item in enumerate(items):
                if isinstance(item, dict):
                    unknown = sorted(set(item) - allowed)
                    if unknown:
                        findings.append(
                            f"unknown_parameters:{path}[{index}]." + ",".join(unknown)
                        )
    if kind == "upsert_statements":
        findings.extend(_batch_nested_parameter_findings(payload))
    return findings


def _unbypassed_phrasing_texts(kind: str, payload: dict) -> list[tuple[str, str, str]]:
    if payload.get("allow_phrasing_violations"):
        return []
    if kind == "upsert_statements":
        return [
            (f"statements[{index}]", item["text"], item["kind"])
            for index, item in enumerate(payload.get("statements", []))
            if isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("kind"), str)
            and not item.get("allow_phrasing_violations")
        ]
    if kind == "upsert_statement" and isinstance(payload.get("text"), str):
        return [("text", payload["text"], str(payload.get("kind") or "event"))]
    if kind in ("replace_text", "patch_statement") and isinstance(
        payload.get("text"), str
    ):
        row = store.get_statement(_db(), str(payload.get("id")))
        statement_kind = payload.get("kind") or (row["kind"] if row else None)
        return [("text", payload["text"], str(statement_kind or "event"))]
    return []


def _phrasing_findings(kind: str, payload: dict) -> list[str]:
    return [
        f"phrasing:{position}:{violation['rule']}: {violation['recommendation']}"
        for position, text, statement_kind in _unbypassed_phrasing_texts(kind, payload)
        for violation in phrasing.check(text, kind=statement_kind)
    ]


def _rejections(result: JsonValue) -> list[JsonValue]:
    if not isinstance(result, dict):
        return []
    if result.get("rejected") is True:
        return [result.get("violations")]
    items = result.get("results")
    return [
        {"index": index, "violations": item.get("violations")}
        for index, item in enumerate(items if isinstance(items, list) else [])
        if isinstance(item, dict) and item.get("rejected") is True
    ]


def _draft_operation_findings(ops: list[sqlite3.Row]) -> list[DraftOperationFinding]:
    from .. import drafts_store

    findings: list[DraftOperationFinding] = []
    tools_by_name = {wrapper.__name__: wrapper for wrapper in TOOLS}
    producers = {int(op["seq"]): op for op in ops}
    for op in ops:
        kind = op["kind"]
        operation_ref = op["id"]
        if kind == drafts_store.ALIAS_SUGGESTION_KIND:
            from ..alias_suggestions import Suggestion

            suggestion = Suggestion.model_validate_json(op["payload_json"])
            messages = (
                ["alias_requires_human_review"]
                if suggestion.status == "pending"
                else []
            )
        elif kind == "flag":
            messages = ["unresolved_flag"]
        elif kind in drafts_store.NON_REPLAYING_OP_KINDS:
            messages = []
        elif kind not in tools_by_name or kind not in _ORIG_SIGNATURES:
            messages = ["obsolete_tool"]
        else:
            payload = _json.loads(op["payload_json"])
            unknown = sorted(set(payload) - set(_ORIG_SIGNATURES[kind].parameters))
            messages = ["unknown_parameters:" + ",".join(unknown)] if unknown else []
            messages.extend(_nested_parameter_findings(kind, payload))
            messages.extend(_phrasing_findings(kind, payload))
        for reference, result_index_text in re.findall(
            r'"@(\d+):(\d+)"', op["payload_json"]
        ):
            producer = int(reference)
            producer_op = producers.get(producer)
            result_index = int(result_index_text)
            if producer_op is None or producer >= int(op["seq"]):
                messages.append(f"unresolved_operation_reference:@{reference}")
            elif producer_op["kind"] != "upsert_statements" or result_index >= len(
                _json.loads(producer_op["payload_json"]).get("statements", [])
            ):
                messages.append(
                    f"unresolved_operation_reference:@{reference}:{result_index_text}"
                )
        findings.extend(
            {"operation_ref": operation_ref, "kind": kind, "finding": message}
            for message in messages
        )
    return findings


@tool(role="writer", real_role=True)
def inspect_draft_review(draft_id: str) -> DraftReviewInspection:
    """Inspect exact draft content and affected knowledge for review."""
    from .. import drafts_store

    _identified_principal()
    row, ops = drafts_store.get_draft_snapshot(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    findings = _draft_operation_findings(ops)
    reviews = drafts_store.list_reviews(_drafts_db(), draft_id)
    applications = drafts_store.list_applications(_drafts_db(), draft_id)
    return {
        "draft": drafts_store.serialize_draft(row, ops=ops),
        "draft_revision": int(row["revision"]),
        "knowledge_preconditions": _knowledge_preconditions(ops),
        "operation_findings": findings,
        "unresolved": bool(findings),
        "reviews": [drafts_store.serialize_review(review) for review in reviews],
        "applications": [
            drafts_store.serialize_application(application)
            for application in applications
        ],
    }


@tool(role="writer", real_role=True)
def append_draft_correction(
    draft_id: str,
    tool_name: str,
    payload: dict[str, JsonValue],
    expected_revision: int | None = None,
) -> DraftCorrectionReceipt:
    """Append one supported substrate mutation to an open or submitted draft."""
    from .. import drafts_store

    principal = _identified_principal()
    wrapper = next((item for item in TOOLS if item.__name__ == tool_name), None)
    if wrapper is None or not tool_name.startswith(_MUTATION_PREFIXES):
        raise ValueError(f"unsupported correction tool '{tool_name}'")
    signature = _ORIG_SIGNATURES[tool_name]
    signature.bind(**payload)
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        drafts_store._check_revision(row, expected_revision)
        seq = drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind=tool_name,
            payload=payload,
            created_by=principal.id,
        )
        revision = drafts_store.current_revision(conn, draft_id)
        operation = next(
            op for op in drafts_store.list_ops(conn, draft_id) if op["seq"] == seq
        )
    return {
        "draft_id": draft_id,
        "operation_ref": operation["id"],
        "seq": seq,
        "revision": revision,
    }


_REVIEW_OUTCOMES = ("accepted", "refined", "rejected", "needs_context")


@tool(role="writer", real_role=True)
def record_draft_review(
    draft_id: str,
    outcome: Literal["accepted", "refined", "rejected", "needs_context"],
    rationale: str,
    draft_revision: int,
    knowledge_preconditions: list[KnowledgePrecondition],
    unresolved_questions: list[str] | None = None,
) -> DraftReviewRecord:
    """Record a durable outcome against exact inspected draft and knowledge state."""
    from .. import drafts_store

    principal = _identified_principal()
    if outcome not in _REVIEW_OUTCOMES:
        raise ValueError("invalid review outcome")
    if not rationale.strip():
        raise ValueError("review rationale is required")
    conn = _drafts_db()
    with store.write_lock():
        inspected = inspect_draft_review(draft_id)
        if inspected["draft"]["status"] != "submitted":
            raise ValueError("only submitted drafts can be reviewed")
        if inspected["draft_revision"] != draft_revision:
            raise drafts_store.StaleDraftRevisionError("draft changed since inspection")
        current_knowledge = _review_knowledge_preconditions(
            drafts_store.list_ops(conn, draft_id), knowledge_preconditions
        )
        if current_knowledge != knowledge_preconditions:
            raise ValueError("affected knowledge changed since inspection")
        unresolved = list(unresolved_questions or [])
        unresolved.extend(
            finding["finding"] for finding in inspected["operation_findings"]
        )
        if outcome in ("accepted", "refined") and unresolved:
            raise ValueError("accepted reviews cannot contain unresolved findings")
        with store.transaction(conn):
            review_id = drafts_store.create_review(
                conn,
                draft_id=draft_id,
                outcome=outcome,
                rationale=rationale.strip(),
                draft_revision=draft_revision,
                preconditions=knowledge_preconditions,
                unresolved_questions=unresolved,
                reviewed_by=principal.id,
            )
            if outcome == "rejected":
                drafts_store.set_decision(
                    conn, draft_id, decision="rejected", by=principal.id
                )
    review = drafts_store.get_review(conn, review_id)
    assert review is not None  # written in the transaction above
    return drafts_store.serialize_review(review)


_DRAFT_RESULT_REF = re.compile(r"^@(\d+):(\d+)$")


def _resolve_draft_refs(payload: Any, results_by_seq: dict[int, Any]) -> Any:
    """Resolve cross-operation statement references in a draft payload.

    `"@<seq>:<index>"` addresses the statement the op at `seq` created at that
    position. A bare `"@N"` is left alone: it belongs to `upsert_statements`'
    own sibling grammar and is resolved by that tool, not here.

    The walk is payload-wide rather than restricted to known id fields: an
    allowlist would have to track every tool's parameter names and would fail
    open — silently skipping resolution — the moment one grows a new endpoint
    argument. The cost is that a free-form value equal in its entirety to
    `@<int>:<int>` (never prose, and never produced by `connect.draft`) would
    be substituted too.
    """
    if isinstance(payload, dict):
        return {
            key: _resolve_draft_refs(value, results_by_seq)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_resolve_draft_refs(value, results_by_seq) for value in payload]
    if not isinstance(payload, str):
        return payload

    match = _DRAFT_RESULT_REF.fullmatch(payload)
    if match is None:
        return payload
    seq, index = (int(value) for value in match.groups())
    result = results_by_seq.get(seq)
    items = result.get("results") if isinstance(result, dict) else None
    item = items[index] if isinstance(items, list) and index < len(items) else None
    if not isinstance(item, dict) or "statement_id" not in item:
        raise ValueError(f"@{seq}:{index} which did not produce a statement")
    return item["statement_id"]


def _replay_draft_op(
    op: sqlite3.Row,
    tools_by_name: dict[str, Callable[..., Any]],
    results_by_seq: dict[int, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve and replay one draft operation with contextual errors."""
    from .. import drafts_store

    kind = op["kind"]
    seq = op["seq"]
    if kind in drafts_store.NON_REPLAYING_OP_KINDS:
        return {"seq": seq, "kind": kind, "skipped": kind}
    wrapper = tools_by_name.get(kind)
    if wrapper is None:
        # The tool was removed since this op was queued — notably
        # `add_mentions` / `remove_mentions`, now that mentions are derived.
        # Such an op is obsolete; skip it rather than fail the whole draft.
        return {"seq": seq, "kind": kind, "skipped": "obsolete_tool"}

    payload = _json.loads(op["payload_json"])
    try:
        payload = _resolve_draft_refs(payload, results_by_seq)
    except ValueError as ex:
        raise RuntimeError(f"op seq={seq} references {ex}") from ex

    if kind == "add_links":
        try:
            link_authoring.reject_entity_statement_additions(payload.get("links"))
        except ValueError as ex:
            raise RuntimeError(
                f"op seq={seq} ({kind}) failed during replay: {ex}"
            ) from ex

    # Drop payload keys the tool no longer accepts (e.g. a stale `mentions` /
    # `strict_mentions` on a queued upsert_statement) so an old draft replays
    # cleanly instead of raising on an unexpected kwarg.
    sig = _ORIG_SIGNATURES.get(kind)
    if sig is not None:
        for key in [key for key in payload if key not in sig.parameters]:
            payload.pop(key)
    try:
        result = wrapper(**payload)
    except Exception as ex:
        raise RuntimeError(f"op seq={seq} ({kind}) failed during replay: {ex}") from ex
    rejected = isinstance(result, dict) and result.get("rejected") is True
    items = result.get("results") if isinstance(result, dict) else None
    if isinstance(items, list):
        rejected = rejected or any(
            isinstance(item, dict) and item.get("rejected") is True for item in items
        )
    if strict and rejected:
        raise RuntimeError(
            f"op seq={seq} ({kind}) was rejected during replay: "
            + _json.dumps(_rejections(result), default=str)
        )
    results_by_seq[seq] = result
    return {"seq": seq, "kind": kind, "result": result}


def apply_draft(
    draft_id: str,
    *,
    application_id: str | None = None,
    review_id: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Replay an `open` or `submitted` draft's ops against the substrate.

    Caller is responsible for having already verified the principal is
    a curator and the draft is in a state that allows approval. Iterates
    in seq order; each op invokes its matching MCP tool wrapper with the
    curator's principal already in the contextvar (so the role gate
    passes naturally). All-or-nothing: a single op raising halts replay
    and surfaces the error. The caller records approval after a successful replay.
    A non-replaying op kind such as `flag` is skipped with its own marker.

    Returns `{applied: int, skipped: int, results: [...]}`. On failure,
    raises with the seq/kind that exploded.
    """
    from .. import drafts_store

    if (application_id is None) != (review_id is None):
        raise ValueError("application_id and review_id must be supplied together")

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        raise ValueError(
            f"draft '{draft_id}' is {status}; only open or submitted "
            f"drafts can be approved"
        )
    active = drafts_store.active_application(_drafts_db(), draft_id)
    if active is not None and active["id"] != application_id:
        raise drafts_store.ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )

    ops = drafts_store.list_ops(_drafts_db(), draft_id)
    from .. import alias_suggestions

    if alias_suggestions.pending(ops):
        raise ValueError(
            "Review pending alias suggestions individually before applying this draft."
        )
    findings = _draft_operation_findings(ops)
    if strict and findings:
        raise ValueError("draft has unresolved operation findings")
    tools_by_name = {w.__name__: w for w in TOOLS}
    results: list[dict[str, Any]] = []
    results_by_seq: dict[int, Any] = {}

    snapshot_id = uuid.uuid4().hex
    index_snapshot_path = _idx_path().with_name(
        _idx_path().name + ".pre-apply-" + snapshot_id
    )
    name_index_snapshot_path = _name_idx_path().with_name(
        _name_idx_path().name + ".pre-apply-" + snapshot_id
    )
    snapshots = (
        (_idx(), index_snapshot_path, _idx_path()),
        (_name_idx(), name_index_snapshot_path, _name_idx_path()),
    )

    # All-or-nothing replay: one transaction owns every op's substrate
    # writes. Each replayed tool opens its own `transaction(_db())`, which
    # joins this outer one (reentrant), so a single op raising rolls the
    # whole draft back. Per-attempt paths preserve recovery artifacts across
    # retries; the write lock serializes snapshots and both recovery paths
    # against index mutations in this process. The persisted-write wrapper
    # marks both indexes before the snapshots. A successful replay clears them
    # only after the outer commit; a failed replay leaves them for startup to
    # rebuild even when its best-effort snapshot restore succeeds.
    snapshots_taken = False
    restored = False
    try:
        with _persisted_index_write(statements=True, names=True):
            try:
                _idx().save(index_snapshot_path)
                _name_idx().save(name_index_snapshot_path)
            except BaseException:
                for _, snapshot_path, _ in snapshots:
                    with contextlib.suppress(OSError):
                        snapshot_path.unlink(missing_ok=True)
                raise
            snapshots_taken = True
            try:
                for op in ops:
                    results.append(
                        _replay_draft_op(
                            op, tools_by_name, results_by_seq, strict=strict
                        )
                    )
                if application_id is not None:
                    replay_result = {
                        "applied": sum("result" in item for item in results),
                        "skipped": sum("skipped" in item for item in results),
                        "results": results,
                    }
                    _db().execute(
                        "INSERT OR IGNORE INTO reviewed_draft_applications "
                        "(application_id, draft_id, review_id, committed_at, result_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            application_id,
                            draft_id,
                            review_id,
                            timestamps.now(),
                            _json.dumps(replay_result),
                        ),
                    )
            except BaseException:
                restored = True
                _restore_index_snapshots(snapshots)
                raise
    except BaseException:
        if snapshots_taken and not restored:
            # A failed commit leaves the connection's transaction open, so a
            # new transaction block could commit the replay it should recover.
            with store.write_lock():
                # Roll back before restoring so no writer can interleave or
                # later commit the failed replay's pending rows.
                with contextlib.suppress(sqlite3.Error):
                    _db().rollback()
                _restore_index_snapshots(snapshots)
        raise

    for _, snapshot_path, _ in snapshots:
        with contextlib.suppress(OSError):
            snapshot_path.unlink(missing_ok=True)
    return {
        "applied": sum("result" in item for item in results),
        "skipped": sum("skipped" in item for item in results),
        "results": results,
    }


def _reviewed_apply_enabled() -> bool:
    from .. import draft_review_settings

    return draft_review_settings.load_controls(_prompts_db()).application_enabled


def _substrate_application_result(
    application_id: str,
) -> dict[str, JsonValue] | None:
    row = (
        _db()
        .execute(
            "SELECT result_json FROM reviewed_draft_applications WHERE application_id = ?",
            (application_id,),
        )
        .fetchone()
    )
    return None if row is None else _json.loads(row["result_json"])


@tool(role="writer", real_role=True)
def apply_reviewed_draft(draft_id: str, review_id: str) -> ReviewedApplicationReceipt:
    """Apply an accepted exact-version review with durable replay recovery."""
    from .. import drafts_store

    principal = _identified_principal()
    conn = _drafts_db()
    with store.write_lock():
        if not _reviewed_apply_enabled():
            raise ValueError("reviewed draft application is disabled")
        stale_knowledge = False
        with store.transaction(conn):
            draft = drafts_store.get_draft(conn, draft_id)
            review = drafts_store.get_review(conn, review_id)
            if draft is None or review is None or review["draft_id"] != draft_id:
                raise ValueError("draft or review not found")
            existing = drafts_store.application_for_review(conn, draft_id, review_id)
            if existing is not None and existing["status"] == "committed":
                stored = _json.loads(existing["result_json"])
                return {"application_id": existing["id"], **stored, "recovered": True}
            if drafts_store.status_for(draft) != "submitted":
                raise ValueError("only submitted drafts can be applied")
            if review["outcome"] not in ("accepted", "refined"):
                raise ValueError("review outcome does not permit application")
            if _json.loads(review["unresolved_json"]):
                raise ValueError("review has unresolved questions")
            if int(draft["revision"]) != int(review["draft_revision"]):
                raise drafts_store.StaleDraftRevisionError(
                    "draft changed after the recorded review"
                )
            application_id = drafts_store.claim_application(
                conn,
                draft_id=draft_id,
                review_id=review_id,
                claimed_by=principal.id,
            )
            result = _substrate_application_result(application_id)
            if result is None:
                current = _review_knowledge_preconditions(
                    drafts_store.list_ops(conn, draft_id),
                    _json.loads(review["preconditions_json"]),
                )
                if current != _json.loads(review["preconditions_json"]):
                    stale_knowledge = True

        if stale_knowledge:
            failure = "affected knowledge changed after the recorded review"
            with store.transaction(conn):
                drafts_store.finish_application(
                    conn, application_id, status="failed", failure=failure
                )
            raise ValueError(failure)

        if result is None:
            try:
                result = apply_draft(
                    draft_id,
                    application_id=application_id,
                    review_id=review_id,
                    strict=True,
                )
            except BaseException as exc:
                committed = _substrate_application_result(application_id)
                if committed is None:
                    with store.transaction(conn):
                        drafts_store.finish_application(
                            conn, application_id, status="failed", failure=str(exc)
                        )
                    raise
                with store.transaction(conn):
                    drafts_store.note_application_failure(
                        conn,
                        application_id,
                        f"replay returned after substrate commit: {exc}",
                    )
                result = {**committed, "recovered": True}
        else:
            result = {**result, "recovered": True}

        try:
            with store.transaction(conn):
                drafts_store.finish_application(
                    conn, application_id, status="committed", result=result
                )
                drafts_store.set_decision(
                    conn,
                    draft_id,
                    decision="approved",
                    by=principal.id,
                    application_id=application_id,
                )
        except BaseException as exc:
            with store.transaction(conn):
                drafts_store.note_application_failure(
                    conn, application_id, f"draft finalization failed: {exc}"
                )
            logger.warning(
                "reviewed draft application %s for %s awaits recovery",
                application_id,
                draft_id,
            )
            raise
    return {"application_id": application_id, **result}


publish(__all__)


def run() -> None:
    mcp.run(transport="stdio")
