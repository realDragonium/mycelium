"""What gives an agent each action the web app's HTTP routes offer a person.

Every action a person can take on the knowledge base is also an MCP tool, with
the same role rules, validation and audit because the route and the tool call
the same server function. This table says which tool that is for every route,
or why a route has none. `tests/test_mcp_parity.py` walks the app's routes and
fails on one missing here, so a new route has to choose.

A generated tool route (`POST /<tool-name>`) needs no entry when its tool is
advertised over MCP; one kept off MCP needs an entry like any other route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    """The MCP tool that offers this route's action."""

    name: str


@dataclass(frozen=True)
class Elsewhere:
    """An action another branch is giving agents."""

    branch: str
    action: str


@dataclass(frozen=True)
class ServerOperation:
    """About running the server, not the knowledge in it."""

    reason: str


@dataclass(frozen=True)
class NotAnAction:
    """No action a person takes: browser plumbing or in-process machinery."""

    reason: str


Parity = Tool | Elsewhere | ServerOperation | NotAnAction

_DRAFT_DECISIONS = "feature/agent-draft-decisions"
_SIGN_IN = ServerOperation("signing in: the browser session and its OIDC login")
_OAUTH = ServerOperation("OAuth that MCP clients sign in with")
_GITHUB = ServerOperation("the GitHub app connection")
_TRACES = ServerOperation("request and loop traces for diagnosing the server")
_USERS = ServerOperation("user, invite and token administration")
_BOOTSTRAP = NotAnAction(
    "the whole substrate shaped for the browser's graph and glossary views; "
    "agents read the same rows through list_statements, list_entities, "
    "get_entity and get_statements"
)
_PAGE = NotAnAction("serves or redirects to a browser page")
_PROMPT_ROWS = NotAnAction(
    "raw prompt-store rows no screen uses; get_writing_profile, get_settings "
    "and edit_prompt_text read and edit the texts Settings edits"
)
_REVIEWER = NotAnAction("a step of the internal draft reviewer, called in-process")

ROUTES: dict[tuple[str, str], Parity] = {
    # --- sign-in, OAuth and the GitHub app ---------------------------------
    ("GET", "/auth/login"): _SIGN_IN,
    ("GET", "/auth/callback"): _SIGN_IN,
    ("GET", "/auth/logout"): _SIGN_IN,
    ("POST", "/auth/logout"): _SIGN_IN,
    ("GET", "/auth/invite/{token}"): _SIGN_IN,
    ("GET", "/.well-known/oauth-protected-resource"): _OAUTH,
    ("GET", "/.well-known/oauth-authorization-server"): _OAUTH,
    ("POST", "/register"): _OAUTH,
    ("GET", "/authorize"): _OAUTH,
    ("POST", "/authorize/decide"): _OAUTH,
    ("POST", "/token"): _OAUTH,
    ("GET", "/api/github"): _GITHUB,
    ("POST", "/api/github/start"): _GITHUB,
    ("GET", "/api/github/setup"): _GITHUB,
    ("GET", "/api/github/callback"): _GITHUB,
    ("GET", "/api/github/repositories"): _GITHUB,
    ("POST", "/api/github/connections"): _GITHUB,
    ("POST", "/api/github/disconnect"): _GITHUB,
    # --- account and administration ----------------------------------------
    ("GET", "/api/server-info"): ServerOperation(
        "the browser's server identity and sign-in options; MCP clients get "
        "the server's identity when they connect"
    ),
    ("GET", "/api/me"): ServerOperation("the signed-in session's identity"),
    ("GET", "/api/me/tokens"): _USERS,
    ("POST", "/api/me/tokens"): _USERS,
    ("DELETE", "/api/me/tokens/{token_id}"): _USERS,
    ("GET", "/api/admin/users"): _USERS,
    ("POST", "/api/admin/users"): _USERS,
    ("PATCH", "/api/admin/users/{user_id}"): _USERS,
    ("GET", "/api/admin/users/{user_id}/tokens"): _USERS,
    ("POST", "/api/admin/users/{user_id}/tokens"): _USERS,
    ("DELETE", "/api/admin/tokens/{token_id}"): _USERS,
    ("GET", "/api/admin/invites"): _USERS,
    ("POST", "/api/admin/invites"): _USERS,
    ("DELETE", "/api/admin/invites/{invite_id}"): _USERS,
    ("GET", "/api/admin/performance"): ServerOperation(
        "request timings for operating the server"
    ),
    ("GET", "/api/traces"): _TRACES,
    ("GET", "/api/traces/{trace_id}"): _TRACES,
    ("GET", "/api/tracing"): _TRACES,
    ("POST", "/api/tracing/enable"): _TRACES,
    ("POST", "/api/tracing/disable"): _TRACES,
    # --- settings ----------------------------------------------------------
    ("GET", "/api/product-settings"): Tool("get_settings"),
    ("PATCH", "/api/product-settings"): ServerOperation(
        "the server's limits, concurrency and retry budgets"
    ),
    ("GET", "/api/model-settings"): Tool("get_settings"),
    ("PATCH", "/api/model-settings/{action}"): ServerOperation(
        "which provider and model each AI action runs on"
    ),
    ("GET", "/api/draft-review/settings"): Tool("get_settings"),
    ("PATCH", "/api/draft-review/settings"): ServerOperation(
        "whether the internal reviewer runs and what it may apply"
    ),
    ("GET", "/api/ai-usage"): Tool("get_settings"),
    ("GET", "/api/setup"): Tool("get_settings"),
    ("PUT", "/api/setup/steps/{step}"): ServerOperation(
        "the operator's setup checklist"
    ),
    ("GET", "/api/ai-instructions"): Tool("get_settings"),
    ("GET", "/api/ai-instructions/{action}"): Tool("get_settings"),
    ("POST", "/api/ai-instructions/{action}/preview"): Tool("get_settings"),
    ("GET", "/api/documentation/prompts/history"): Tool("get_settings"),
    ("PUT", "/api/documentation/prompts"): Tool("edit_prompt_text"),
    ("POST", "/api/documentation/prompts/restore"): Tool("edit_prompt_text"),
    # --- the substrate as the browser loads it --------------------------------
    ("GET", "/api/data"): _BOOTSTRAP,
    ("GET", "/api/graph/concepts"): _BOOTSTRAP,
    ("GET", "/api/graph/neighbourhood"): _BOOTSTRAP,
    ("GET", "/api/entity-positions"): NotAnAction(
        "where the graph view draws each concept"
    ),
    ("GET", "/api/substrate-counts"): Tool("get_knowledge_health"),
    ("GET", "/api/history"): Tool("get_history"),
    # --- knowledge health and gaps -------------------------------------------
    ("GET", "/api/knowledge-health"): Tool("get_knowledge_health"),
    ("GET", "/api/knowledge-health/statements/{which}"): Tool("get_knowledge_health"),
    ("GET", "/api/knowledge-health/entities/{which}"): Tool("get_knowledge_health"),
    ("POST", "/api/knowledge-health/claims/free"): Tool("unblock_automation"),
    ("POST", "/api/knowledge-health/stopped/retry"): Tool("unblock_automation"),
    ("GET", "/api/knowledge-gaps"): Tool("list_knowledge_gaps"),
    ("PATCH", "/api/knowledge-gaps/{gap_id}"): Tool("update_knowledge_gap"),
    # --- names and aliases ---------------------------------------------------
    ("GET", "/api/mention-candidates"): Tool("get_mention_candidates"),
    ("GET", "/api/names-workspace"): Tool("get_names_workspace"),
    ("GET", "/api/names-workspace/{entity_id}"): Tool("get_names_workspace"),
    ("GET", "/api/names-workspace/duplicates/dismissed"): Tool("get_names_workspace"),
    ("POST", "/api/names-workspace/preview"): Tool("edit_names"),
    ("POST", "/api/names-workspace/apply"): Tool("edit_names"),
    ("POST", "/api/names-workspace/duplicates/dismiss"): Tool("edit_names"),
    ("POST", "/api/names-workspace/duplicates/restore"): Tool("edit_names"),
    ("GET", "/api/alias-suggestions"): Tool("get_names_workspace"),
    ("POST", "/api/alias-suggestions/scan"): Tool("edit_names"),
    ("POST", "/api/alias-suggestions/{draft_id}/{operation_ref}/review"): Tool(
        "edit_names"
    ),
    # --- audiences -----------------------------------------------------------
    ("GET", "/api/audiences"): Tool("get_audiences"),
    ("GET", "/api/audiences/labelling"): Tool("get_audiences"),
    ("GET", "/api/statements/{statement_id}/audiences"): Tool("get_audiences"),
    ("GET", "/api/audiences/statements"): Tool("get_audiences"),
    ("GET", "/api/audiences/{audience_id}/pending"): Tool("get_audiences"),
    ("GET", "/api/audiences/{audience_id}/pending/sample"): Tool("get_audiences"),
    ("GET", "/api/audiences/spot-checks"): Tool("get_audiences"),
    ("POST", "/api/audiences"): Tool("manage_audiences"),
    ("PUT", "/api/audiences/{audience_id}"): Tool("manage_audiences"),
    ("POST", "/api/audiences/{audience_id}/retire"): Tool("manage_audiences"),
    ("POST", "/api/audiences/labelling/backfill"): Tool("manage_audiences"),
    ("PUT", "/api/statements/{statement_id}/audiences"): Tool("curate_audiences"),
    ("POST", "/api/statements/{statement_id}/audiences/confirm"): Tool(
        "curate_audiences"
    ),
    ("DELETE", "/api/statements/{statement_id}/audiences"): Tool("curate_audiences"),
    ("POST", "/api/audiences/{audience_id}/pending/decide"): Tool("curate_audiences"),
    ("POST", "/api/audiences/{audience_id}/pending/accept-rest"): Tool(
        "curate_audiences"
    ),
    ("POST", "/api/statements/{statement_id}/audiences/spot-check"): Tool(
        "curate_audiences"
    ),
    # --- media ---------------------------------------------------------------
    ("GET", "/api/media"): Tool("list_media"),
    ("GET", "/api/media/{media_id}"): Tool("list_media"),
    # A drafter may also make an upload link, to cite the media as draft
    # evidence; the item stays unattached and internal until a real writer
    # attaches or labels it with `edit_media`.
    ("POST", "/api/media"): Tool("create_media_upload"),
    ("POST", "/api/media/uploads/{token}"): Tool("create_media_upload"),
    ("PATCH", "/api/media/{media_id}"): Tool("edit_media"),
    ("PUT", "/api/media/{media_id}/content"): Tool("edit_media"),
    ("DELETE", "/api/media/{media_id}"): Tool("edit_media"),
    ("PUT", "/api/media/{media_id}/audiences"): Tool("edit_media"),
    ("POST", "/api/media/{media_id}/audiences/confirm"): Tool("edit_media"),
    ("POST", "/api/media/{media_id}/attachments"): Tool("edit_media"),
    ("DELETE", "/api/media/{media_id}/attachments/{kind}/{target_id}"): Tool(
        "edit_media"
    ),
    ("GET", "/api/media/{media_id}/content"): NotAnAction(
        "serves the bytes at the url list_media returns; agents fetch it over "
        "HTTP with their token, since MCP results carry no files"
    ),
    # --- documentation -------------------------------------------------------
    ("GET", "/api/documentation/profiles"): Tool("list_writing_profiles"),
    ("GET", "/api/documentation/profiles/{name}"): Tool("get_writing_profile"),
    ("PUT", "/api/documentation/profiles/{name}"): Tool("save_writing_profile"),
    ("DELETE", "/api/documentation/profiles/{name}"): Tool("retire_writing_profile"),
    ("GET", "/api/documentation/options"): Tool("list_documentation"),
    ("POST", "/api/documentation/runs"): Tool("request_documentation"),
    ("GET", "/api/documentation/runs"): Tool("list_documentation"),
    ("GET", "/api/documentation/runs/{run_id}"): Tool("get_documentation_run"),
    ("POST", "/api/documentation/runs/{run_id}/retry"): Tool("retry_documentation"),
    ("POST", "/api/documentation/preview"): NotAnAction(
        "renders a Markdown body as HTML for the editor's preview"
    ),
    ("POST", "/api/documentation/documents/{document_id}/edits"): Tool("edit_document"),
    ("POST", "/api/documentation/runs/{run_id}/edits"): Tool("edit_document"),
    ("GET", "/api/documentation/documents"): Tool("list_documentation"),
    ("GET", "/api/documentation/destinations"): Tool("list_documentation"),
    ("GET", "/api/documentation/maintenance"): Tool("list_documentation"),
    ("GET", "/api/documentation/documents/{document_id}"): Tool(
        "get_generated_document"
    ),
    ("GET", "/api/documentation/documents/{document_id}/revisions"): Tool(
        "get_document_history"
    ),
    ("GET", "/api/documentation/documents/{document_id}/revisions/{revision}"): Tool(
        "get_document_history"
    ),
    (
        "GET",
        "/api/documentation/documents/{document_id}/revisions/{revision}/diff",
    ): Tool("get_document_history"),
    ("POST", "/api/documentation/documents/{document_id}/revisions"): Tool(
        "revise_document"
    ),
    # Agents deliver only for a writing profile that lets them: publishing
    # outside the instance stays a person's call until a writer hands it over.
    ("POST", "/api/documentation/documents/{document_id}/delivery"): Tool(
        "deliver_document"
    ),
    ("GET", "/api/documentation/plans/{guideline_set}"): Tool("get_documentation_plan"),
    ("POST", "/api/documentation/plans/{guideline_set}"): Tool(
        "request_documentation_plan"
    ),
    ("POST", "/api/documentation/plan-items/approve"): Tool(
        "decide_documentation_plan"
    ),
    ("POST", "/api/documentation/plan-items/{item_id}/retry"): Tool(
        "retry_documentation"
    ),
    ("POST", "/api/documentation/plan-items/{item_id}/dismiss"): Tool(
        "decide_documentation_plan"
    ),
    (
        "POST",
        "/api/documentation/plans/{guideline_set}/uncovered/{statement_id}/dismiss",
    ): Tool("decide_documentation_plan"),
    (
        "POST",
        "/api/documentation/plans/{guideline_set}/uncovered/{statement_id}/restore",
    ): Tool("decide_documentation_plan"),
    ("POST", "/api/documentation/plans/{guideline_set}/stale/{document_id}/dismiss"): (
        Tool("decide_documentation_plan")
    ),
    # --- drafts and their review ---------------------------------------------
    # `list_drafts` is for real writers, while the route lists every draft to
    # any caller; its filters and roles are that branch's.
    ("GET", "/api/drafts"): Elsewhere(_DRAFT_DECISIONS, "list_drafts filters"),
    ("GET", "/api/drafts/{draft_id}"): Tool("get_draft"),
    ("PATCH", "/api/drafts/{draft_id}/ops/{seq}"): Elsewhere(
        _DRAFT_DECISIONS, "editing a submitted draft's operations"
    ),
    ("DELETE", "/api/drafts/{draft_id}/ops/{seq}"): Elsewhere(
        _DRAFT_DECISIONS,
        "removing a submitted draft's operation (discard_draft_op covers the "
        "creator's open draft)",
    ),
    ("POST", "/api/drafts/{draft_id}/submit"): Tool("submit_draft"),
    ("POST", "/api/drafts/{draft_id}/approve"): Elsewhere(
        _DRAFT_DECISIONS, "review_draft: approve"
    ),
    ("POST", "/api/drafts/{draft_id}/reject"): Elsewhere(
        _DRAFT_DECISIONS, "review_draft: reject"
    ),
    ("POST", "/api/drafts/{draft_id}/withdraw"): Tool("withdraw_draft"),
    ("POST", "/api/drafts/{draft_id}/review"): Tool("request_draft_review"),
    ("POST", "/api/drafts/{draft_id}/review/answer"): Tool("answer_draft_review"),
    ("POST", "/api/drafts/{draft_id}/review/accept"): Elsewhere(
        _DRAFT_DECISIONS, "review_draft: approve with corrections"
    ),
    ("GET", "/api/draft-review/backlog"): Tool("manage_draft_review_backlog"),
    ("POST", "/api/draft-review/backlog"): Tool("manage_draft_review_backlog"),
    ("POST", "/api/draft-review/backlog/pause"): Tool("manage_draft_review_backlog"),
    ("POST", "/api/draft-review/backlog/resume"): Tool("manage_draft_review_backlog"),
    # --- browser pages -------------------------------------------------------
    ("GET", "/"): _PAGE,
    ("GET", "/ui"): _PAGE,
    ("GET", "/connect"): _PAGE,
    ("GET", "/cockpit"): _PAGE,
    ("GET", "/cockpit/{rest:path}"): _PAGE,
    # --- tool routes kept off MCP --------------------------------------------
    ("POST", "/list-document-revisions"): Tool("get_document_history"),
    ("POST", "/get-document-revision"): Tool("get_document_history"),
    ("GET", "/list-documentation-models"): Tool("list_documentation"),
    ("GET", "/list-documentation-runs"): Tool("list_documentation"),
    ("GET", "/list-generated-documents"): Tool("list_documentation"),
    ("GET", "/list-documentation-destinations"): Tool("list_documentation"),
    # The same edit as `patch_statement(id, text=...)`: the same phrasing
    # gate, re-embedding and mention derivation.
    ("POST", "/replace-text"): Tool("patch_statement"),
    ("POST", "/move-name"): Tool("edit_names"),
    ("POST", "/rename-name"): Tool("edit_names"),
    ("POST", "/delete-name"): Tool("edit_names"),
    ("POST", "/delete-entity"): NotAnAction(
        "no screen deletes a concept outright; drafts replay it, and "
        "merge_entities and edit_names consolidate concepts over MCP"
    ),
    ("POST", "/retrieve-context"): NotAnAction(
        "the Ask loop's composite read; the reads it combines are on MCP"
    ),
    ("POST", "/find-duplicates"): NotAnAction(
        "a whole-substrate duplicate audit no screen calls; claim_curation_work "
        "hands out duplicate statement pairs"
    ),
    ("POST", "/upsert-statement-kind"): Tool("edit_vocabulary"),
    ("POST", "/delete-statement-kind"): Tool("edit_vocabulary"),
    ("POST", "/upsert-link-type"): Tool("edit_vocabulary"),
    ("POST", "/delete-link-type"): Tool("edit_vocabulary"),
    ("POST", "/upsert-link-type-alias"): Tool("edit_vocabulary"),
    ("POST", "/delete-link-type-alias"): Tool("edit_vocabulary"),
    ("POST", "/upsert-entity-link-type"): Tool("edit_vocabulary"),
    ("POST", "/delete-entity-link-type"): Tool("edit_vocabulary"),
    ("POST", "/get-prompt-text"): _PROMPT_ROWS,
    ("POST", "/list-prompt-texts"): _PROMPT_ROWS,
    ("POST", "/retire-prompt-text"): _PROMPT_ROWS,
    ("POST", "/get-draft-review-run"): Tool("get_draft"),
    ("POST", "/attach-draft-source"): NotAnAction(
        "CI pipeline provenance, recorded by pipeline steps over HTTP"
    ),
    ("POST", "/find-my-draft-by-source"): NotAnAction(
        "CI pipeline provenance, looked up by pipeline steps over HTTP"
    ),
    ("POST", "/revise-draft-operation"): Elsewhere(
        _DRAFT_DECISIONS, "editing a submitted draft's operations"
    ),
    ("POST", "/strike-draft-operation"): Elsewhere(
        _DRAFT_DECISIONS, "editing a submitted draft's operations"
    ),
    ("POST", "/inspect-draft-review"): _REVIEWER,
    ("POST", "/append-draft-correction"): _REVIEWER,
    ("POST", "/record-draft-review"): _REVIEWER,
    ("POST", "/apply-reviewed-draft"): _REVIEWER,
}
