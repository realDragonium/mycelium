"""MCP server exposing the Mycelium substrate over stdio.

Tools are registered with the local `@tool` decorator (not the bare
`mcp.tool()`) so they show up in the HTTP transport in `mycelium/http.py`
and in the in-process loops. Only the names in `MCP_TOOLS` are also
advertised over MCP: every MCP client pays for each schema it is sent, so
that surface is a deliberate, documented subset (`docs/MCP_TOOLS.md`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .. import databases, store, vector
from ..app_context import AppContext
from ..layout_baker import LayoutBaker
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
from .documentation import (
    deliver_document,
    get_document_revision,
    get_documentation_run,
    get_generated_document,
    list_document_revisions,
    list_documentation_destinations,
    list_documentation_models,
    list_documentation_runs,
    list_generated_documents,
    request_documentation,
    revise_document,
)
from .draft_application import (
    DraftReplay,
    ReviewedApplicationReceipt,
    _substrate_application_result,
    apply_draft,
    apply_reviewed_draft,
)
from .draft_review import (
    DraftCorrectionReceipt,
    DraftOperationFinding,
    DraftReviewInspection,
    DraftReviewRecord,
    KnowledgePrecondition,
    append_draft_correction,
    inspect_draft_review,
    record_draft_review,
)
from .drafts import (
    attach_draft_source,
    discard_draft_op,
    find_my_draft_by_source,
    get_draft,
    get_draft_review_run,
    list_drafts,
    list_my_drafts,
    request_draft_review,
    revise_draft_operation,
    set_draft_review_evidence,
    strike_draft_operation,
    submit_draft,
)
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
from .gaps import report_knowledge_gap
from .indexes import (
    _clear_dirty_marker,
    _dirty_marker_path,
    _fsync_file,
    _rebuild_vector_index,
    _write_dirty_marker,
)
from .links import add_links, remove_links
from .lookups import get_statements, grep_statements, list_statements, retrieve_context
from .model_loops import (
    ask,
    get_research_run,
    ingest,
    list_research_runs,
    list_research_sources,
    start_research,
)
from .names import (
    delete_name,
    find_entity_duplicates,
    get_mention_candidates,
    move_name,
    rename_name,
    upsert_name,
)
from .prompt_texts import (
    _seed_prompt_texts,
    get_documentation_profile,
    get_prompt_text,
    list_documentation_profiles,
    list_prompt_text_versions,
    list_prompt_texts,
    restore_prompt_text,
    retire_documentation_profile,
    retire_prompt_text,
    save_documentation_profile,
    save_prompt_text,
)
from .registry import _ORIG_SIGNATURES, MCP_TOOLS, TOOLS, mcp, publish, tool
from .runtime import _auth_db, _db, _drafts_db, _prompts_db
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
from .vocabulary import (
    ALIAS_PROVENANCE,
    delete_entity_link_type,
    delete_link_type,
    delete_link_type_alias,
    delete_statement_kind,
    list_entity_link_types,
    list_link_type_aliases,
    list_link_types,
    list_statement_kinds,
    upsert_entity_link_type,
    upsert_link_type,
    upsert_link_type_alias,
    upsert_statement_kind,
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
    "ALIAS_PROVENANCE",
    "KnowledgePrecondition",
    "DraftOperationFinding",
    "DraftReviewRecord",
    "DraftReviewInspection",
    "DraftCorrectionReceipt",
    "ReviewedApplicationReceipt",
    "DraftReplay",
    "apply_draft",
    # Read off this module object by the in-process draft emitter
    # (`ingest.draft.InProcessDraftEmitter`, injectable for tests), which
    # accepts every parameter when `_ORIG_SIGNATURES` is missing. Exported so
    # they stay here even when nothing in this module uses them.
    "_ORIG_SIGNATURES",
    "_db",
    "_drafts_db",
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


publish(__all__)


def run() -> None:
    mcp.run(transport="stdio")
