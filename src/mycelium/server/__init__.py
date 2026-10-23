"""MCP server exposing the Mycelium substrate over stdio.

Tools are registered with the local `@tool` decorator (not the bare
`mcp.tool()`) so they show up in the HTTP transport in `mycelium/http/`
and in the in-process loops. Only the names in `MCP_TOOLS` are also
advertised over MCP: every MCP client pays for each schema it is sent, so
that surface is a deliberate, documented subset (`docs/MCP_TOOLS.md`).
"""

from __future__ import annotations

from .admission import limiter_for, model_loop_slot
from .authoring import (
    delete_statement,
    merge_statements,
    patch_statement,
    replace_text,
    upsert_statement,
    upsert_statements,
)
from .curation import claim_curation_work, release_curation_work
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
    retry_documentation_run,
    revise_document,
)
from .draft_application import (
    DraftOpsRejectedError,
    DraftReplay,
    RejectedStatement,
    ReviewedApplicationReceipt,
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
    set_operation_evidence,
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
from .links import add_links, remove_links
from .lookups import get_statements, grep_statements, list_statements, retrieve_context
from .model_loops import ask, connect_statements, ingest
from .names import (
    delete_name,
    find_entity_duplicates,
    get_mention_candidates,
    move_name,
    rename_name,
    upsert_name,
)
from .prompt_texts import (
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
from .runtime import _db, _drafts_db
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
from .startup import init
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
    "connect_statements",
    "claim_curation_work",
    "release_curation_work",
    "request_documentation",
    "retry_documentation_run",
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
    "set_operation_evidence",
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
    "init",
    "run",
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
    "DraftOpsRejectedError",
    "RejectedStatement",
    "apply_draft",
    # Read off this module object by the in-process draft emitter
    # (`ingest.draft.InProcessDraftEmitter`, injectable for tests), which
    # accepts every parameter when `_ORIG_SIGNATURES` is missing. Exported so
    # they stay here even when nothing in this module uses them.
    "_ORIG_SIGNATURES",
    "_db",
    "_drafts_db",
]


publish(__all__)


def run() -> None:
    mcp.run(transport="stdio")
