"""FastAPI HTTP transport — auto-generated mirror of every registered tool.

Every function in `server.TOOLS` (i.e., everything decorated with `@tool`)
is exposed as an endpoint here, including the tools `server.MCP_TOOLS`
keeps off the MCP surface. Path is the kebab-case tool name; method
is GET when the tool takes no args, POST otherwise. The request body's
Pydantic schema is derived from the function signature.

Add a tool to a module in `mycelium/server/` with `@tool`, list it in
`mycelium.server.__all__` (its position there is its place in every listing),
and you'll find it here too at `/<kebab-case-name>` after a server restart —
no edits needed in this file.
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import anyio.from_thread
import anyio.to_thread
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, JsonValue
from pydantic import Field as PydField
from starlette.middleware.sessions import SessionMiddleware

from .. import (
    ai_prompts,
    alias_suggestions,
    auth,
    connect_page,
    documentation_profiles,
    github_connect,
    model_settings,
    names_workspace,
    oauth_server,
    oidc,
    product_settings,
    server,
    store,
    tracing,
)
from .. import (
    draft_review_settings as review_settings,
)
from ..docgen.publication import BothSidesEdited
from ..docgen.schema import ManualDocument
from ..server import registry, runtime
from . import gaps, history, substrate, tool_routes
from .access import _enforce_curator, _enforce_role, _require_admin, _require_principal
from .authentication import AuthMiddleware, _session_secret

# Build the streamable-HTTP sub-app once at import time. Transport
# configuration lives here rather than on the MCPServer: `MCPServer` holds
# the server's identity and tools, the app builder decides how they are
# served. The same endpoint answers both MCP protocol revisions — a
# 2025-era client's `initialize` handshake and a 2026-07-28 client's
# self-describing requests — with nothing to configure.
_MCP_SUBAPP = server.mcp.streamable_http_app(
    transport_security=registry._build_transport_security(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = Path(os.environ.get("MYCELIUM_DATA_DIR", "./.mycelium")).expanduser()
    server.init(data_dir)
    # Start the MCP session manager under our lifespan. A mounted sub-app's
    # own lifespan never runs, so nothing else initialises it — without this
    # every `/mcp` call fails with "Task group is not initialized".
    #
    # `MYCELIUM_DISABLE_MCP_HTTP=1` skips this; the test suite sets the flag
    # because `StreamableHTTPSessionManager.run()` may only be called once
    # per instance, and a test that brings up a second TestClient against
    # this module would otherwise raise on the second lifespan entry. The
    # REST mirror and the auth-gated /api/* endpoints work without the
    # manager; only `/mcp` JSON-RPC needs it.
    if os.environ.get("MYCELIUM_DISABLE_MCP_HTTP") == "1":
        yield
        return
    async with server.mcp.session_manager.run():
        yield


app = FastAPI(title="Mycelium", lifespan=lifespan)


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(auth.RoleRequired)
async def _role_required_handler(
    request: Request, exc: auth.RoleRequired
) -> JSONResponse:
    """The `@tool` wrapper's role gate rejects with `RoleRequired` — reached
    when a call arrives by a route that did not already run `_enforce_role`.
    That's a deliberate 403, not a server fault, and the message names the
    role required."""
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort capture for any error that isn't a deliberate 4xx. Emits one
    structured `MYCELIUM_ERROR` line (→ stderr, where a deployment's log-metric
    filter can count it) and returns an opaque 500. More specific handlers win, so
    ValueError keeps its 400 and FastAPI's HTTPException/validation responses are
    untouched — only genuinely unexpected failures land here."""
    tracing.emit_error(
        where="http",
        exc=exc,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# Middleware in Starlette runs in *reverse* registration order (last
# added wraps the outermost). We want session decoding to happen
# *before* auth resolution reads from `request.session`, so register
# AuthMiddleware FIRST (inner) and SessionMiddleware LAST (outer).
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    session_cookie="myc_session",
    same_site="lax",
    https_only=False,  # local dev runs on http
)

app.include_router(oidc.router)
app.include_router(oauth_server.router)
app.include_router(github_connect.router)
app.include_router(tool_routes.router)
app.include_router(history.router)
app.include_router(substrate.router)
app.include_router(gaps.router)


# MCP-over-HTTP is mounted at the bottom of this file so it doesn't
# shadow more-specific routes; search for "MCP transport mount" below.


# --- account & token endpoints --------------------------------------------
# Used by the bundled UI's settings page. Authenticated principal is read
# from `request.state.principal`, which the middleware populates from a
# session cookie, a bearer token, or the synthetic local-admin when auth
# is off. The synthetic principal is allowed to mint tokens too — handy
# in single-user local mode for bootstrapping an MCP client without ever
# enabling auth.


def _serialize_token_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "scope": row["scope"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


@app.get("/api/mention-candidates")
def mention_candidates(
    request: Request, entity_id: str, after: int = 0, limit: int = 50
) -> dict[str, JsonValue]:
    _require_principal(request)
    return server.get_mention_candidates(entity_id=entity_id, after=after, limit=limit)


# --- timing traces (pyinstrument flamegraphs) -----------------------------
# When tracing is enabled, each ask / ingest / find run drops a self-contained
# pyinstrument `*.html` flamegraph (+ a `.meta.json` sidecar) under the trace
# dir (see mycelium/tracing.py). `/api/traces` lists them with a `view_url` per
# trace; `GET /api/traces/{id}` serves that trace's HTML so it renders straight
# in the browser — no download, no speedscope.app. Admin-only.
_TRACE_SUFFIX = tracing.TRACE_SUFFIX
_META_SUFFIX = tracing.META_SUFFIX


def _trace_dir() -> Path:
    return tracing.default_trace_dir()


@app.get("/api/traces")
def list_traces(request: Request) -> Any:
    """Recent flamegraph traces for this task, newest first. Each entry's
    `view_url` renders the flamegraph in the browser."""
    _enforce_role(request, "admin")
    d = _trace_dir()
    if not d.exists():
        return {"traces": []}
    files = sorted(
        d.glob(f"*{_TRACE_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:100]
    traces = []
    for p in files:
        trace_id = p.name[: -len(_TRACE_SUFFIX)]
        meta: dict[str, Any] = {}
        meta_path = d / f"{trace_id}{_META_SUFFIX}"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a corrupt sidecar shouldn't hide the rest
                pass
        traces.append(
            {
                "id": trace_id,
                "mtime": p.stat().st_mtime,
                "kind": meta.get("kind"),
                "label": meta.get("label"),
                "latency_ms": meta.get("latency_ms"),
                "view_url": f"/api/traces/{trace_id}",
            }
        )
    return {"traces": traces}


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str, request: Request) -> Any:
    """Render one trace's flamegraph — open this URL in a browser."""
    from fastapi.responses import HTMLResponse
    from fastapi.responses import JSONResponse as _JSON

    _enforce_role(request, "admin")
    if "/" in trace_id or "\\" in trace_id or ".." in trace_id:
        return _JSON(status_code=400, content={"detail": "bad trace id"})
    path = _trace_dir() / f"{trace_id}{_TRACE_SUFFIX}"
    if not path.exists():
        return _JSON(status_code=404, content={"detail": "trace not found"})
    return HTMLResponse(path.read_text(encoding="utf-8"))


# --- tracing on/off switch -------------------------------------------------
# Tracing is OFF by default; nothing is written until an admin turns it on for
# a debugging window. `/api/tracing` (status), `/api/tracing/enable?minutes=N`
# (auto-disarms after N minutes if given, else stays on until disabled), and
# `/api/tracing/disable`. Distinct path prefix from `/api/traces` (the files),
# so no route collision.
# Status is a safe GET. The state-changing enable/disable are POST-only: a GET
# toggle would be flippable by a cross-site top-level navigation riding the
# admin's session cookie (CSRF). Flip them with curl + a bearer token, which is
# also CSRF-immune (no ambient cookie):
#   curl -X POST -H "Authorization: Bearer $TOK" "$S/api/tracing/enable?minutes=15"
@app.get("/api/tracing")
def tracing_status_endpoint(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.tracing_status()


@app.post("/api/tracing/enable")
def tracing_enable(request: Request, minutes: float | None = None) -> Any:
    """Turn tracing on. `?minutes=N` auto-disarms after N minutes."""
    _enforce_role(request, "admin")
    ttl = minutes * 60.0 if minutes and minutes > 0 else None
    return tracing.set_tracing(True, ttl_seconds=ttl)


@app.post("/api/tracing/disable")
def tracing_disable(request: Request) -> Any:
    _enforce_role(request, "admin")
    return tracing.set_tracing(False)


@app.get("/api/server-info")
async def get_server_info(request: Request) -> dict[str, Any]:
    """Public-ish discovery endpoint used by the setup help page so the
    UI can render config snippets containing the actual MCP URL the
    client should connect to.

    Exempt from auth (path starts with /api/ but the endpoint itself
    returns no secrets) — but to keep the surface honest we only
    expose data the user would learn just by looking at the address
    bar. No tokens, no env, no internal config.

    Deliberately `async` while every other endpoint here is sync: deployments
    tend to point their health check at this path, and a sync endpoint would
    need a slot in the same worker pool the tool calls occupy. Enough concurrent
    tools in flight and the probe queues behind them and times out — so a
    deployment that replaces unhealthy instances kills a server for being busy.
    Answering on the event loop makes the probe mean "this process's loop is
    still turning", which is the condition a restart can actually fix. It does
    no I/O, so there is nothing here that needs a thread. Keep it that way.

    `partial_restore` breaks the address-bar rule on purpose: it names the
    databases startup found missing beside a populated substrate, so a
    broken restore is visible to whoever watches the probe. It stays 200 —
    a replacement task would restore the same incomplete set.
    """
    base = str(request.base_url).rstrip("/")
    ctx = runtime._ctx
    return {
        "base_url": base,
        "mcp_url": f"{base}/mcp",
        "auth_enabled": auth.is_enabled(),
        "partial_restore": list(ctx.partial_restore) if ctx else [],
    }


@app.get("/api/me")
def get_me(request: Request) -> dict[str, Any]:
    """Return the current principal. The UI uses this to decide whether
    to show admin-only affordances and whose tokens to list."""
    p = _require_principal(request)
    return {
        "id": p.id,
        "name": p.name,
        "role": p.role,
        "type": p.type,
        "synthetic": p.synthetic,
        "auth_enabled": auth.is_enabled(),
    }


@app.get("/api/me/tokens")
def list_my_tokens(request: Request) -> dict[str, Any]:
    """List the calling user's MCP tokens. Revoked tokens stay in the
    list (UI greys them out) so a user can see what was revoked and
    when — useful when the same label was reused later."""
    p = _require_principal(request)
    conn = runtime._auth_db()
    rows = auth.list_tokens(conn, auth.owner_id_for(p))
    return {"tokens": [_serialize_token_row(r) for r in rows]}


class CreateTokenBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=80)
    scope: auth.Scope = "writer"


@app.post("/api/me/tokens")
def create_my_token(body: CreateTokenBody, request: Request) -> dict[str, Any]:
    """Mint a new MCP token for the calling user. Scope can't exceed
    the user's current role — the server caps it server-side rather
    than trusting the client.

    Returns the raw token exactly once. The client is expected to copy
    it immediately; it cannot be retrieved later.
    """
    p = _require_principal(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        raw, row = auth.mint_own_token(
            conn, principal=p, name=body.name, scope=body.scope
        )
    return {"token": raw, **_serialize_token_row(row)}


@app.delete("/api/me/tokens/{token_id}")
def revoke_my_token(token_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            auth.revoke_own_token(
                conn, token_id=token_id, owner_id=auth.owner_id_for(p)
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"ok": True}


# --- drafts ---------------------------------------------------------------
# Drafts are pending change sets submitted by drafters (or anyone passing
# an explicit draft_id to a write tool). Curators review and either
# approve (replay ops against the substrate) or reject (drop without
# applying). Status is derived from terminal timestamps + decision, same
# pattern as knowledge_gaps.


@app.exception_handler(documentation_profiles.Conflict)
async def _profile_conflict(
    request: Request, exc: documentation_profiles.Conflict
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(names_workspace.Conflict)
async def _names_conflict(
    request: Request, exc: names_workspace.Conflict
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/names-workspace")
def names_catalogue_http(request: Request, q: str = "") -> names_workspace.Catalogue:
    principal = _require_principal(request)
    result = names_workspace.catalogue(server._db(), q)
    result.can_write = auth.principal_has_real_role(principal, "writer")
    if result.can_write:
        result.allowed_actions = ["add", "correct", "prefer", "move", "split"]
    if auth.principal_has_real_role(principal, "admin"):
        result.allowed_actions.extend(("merge", "remove"))
    return result


@app.post("/api/names-workspace/preview")
def names_preview_http(
    body: names_workspace.PreviewRequest, request: Request
) -> names_workspace.Preview:
    _enforce_curator(request, "editing names and aliases")
    if body.action.kind in {"merge", "remove"}:
        _require_admin(request)
    return names_workspace.preview(server._db(), body.action)


@app.post("/api/names-workspace/apply")
def names_apply_http(
    body: names_workspace.ApplyRequest, request: Request
) -> names_workspace.Applied:
    _enforce_curator(request, "editing names and aliases")
    if body.action.kind in {"merge", "remove"}:
        _require_admin(request)
    return names_workspace.apply(body)


@app.get("/api/names-workspace/{entity_id}")
def names_detail_http(entity_id: str, request: Request) -> names_workspace.Detail:
    _require_principal(request)
    return names_workspace.detail(server._db(), entity_id)


@app.get("/api/documentation/profiles")
def documentation_profiles_http(request: Request) -> documentation_profiles.Profiles:
    return documentation_profiles.view(_require_principal(request))


@app.get("/api/documentation/profiles/{name}")
def documentation_profile_http(
    name: str, request: Request
) -> documentation_profiles.Profile:
    _require_principal(request)
    return documentation_profiles.read(name)


@app.put("/api/documentation/profiles/{name}")
def save_documentation_profile_http(
    name: str, body: documentation_profiles.SaveProfile, request: Request
) -> documentation_profiles.Profile:
    return documentation_profiles.save(name, body, _require_principal(request))


@app.delete("/api/documentation/profiles/{name}")
def retire_documentation_profile_http(
    name: str, body: documentation_profiles.RevisionRequest, request: Request
) -> documentation_profiles.Profile:
    return documentation_profiles.retire(
        name, body.revision, _require_principal(request)
    )


@app.get("/api/documentation/prompts/history")
def documentation_prompt_history_http(
    type: str, name: str, request: Request
) -> dict[str, object]:
    _require_principal(request)
    documentation_profiles.editable_key(type, name)
    from .. import prompt_store

    return {
        "versions": [
            documentation_profiles.text_version(row).model_dump()
            for row in prompt_store.history(prompt_store.connection(), type, name)
        ]
    }


@app.put("/api/documentation/prompts")
def save_documentation_prompt_http(
    body: documentation_profiles.SaveText, request: Request
) -> documentation_profiles.TextVersion:
    documentation_profiles.editable_key(body.type, body.name)
    return documentation_profiles.save_text(
        body.type,
        body.name,
        body.text,
        _require_principal(request),
        revision=body.revision,
    )


@app.post("/api/documentation/prompts/restore")
def restore_documentation_prompt_http(
    body: documentation_profiles.RestoreText, request: Request
) -> documentation_profiles.TextVersion:
    documentation_profiles.editable_key(body.type, body.name)
    return documentation_profiles.restore_text(body, _require_principal(request))


@app.get("/api/ai-instructions")
def ai_instructions_http(request: Request) -> dict[str, object]:
    principal = _require_principal(request)
    return {
        "names": documentation_profiles.INSTRUCTIONS,
        "actions": [
            {"name": name, "title": ai_prompts.TITLES[name]}
            for name in ai_prompts.ACTIONS
        ],
        "can_write": auth.principal_has_real_role(principal, "writer"),
    }


@app.get("/api/ai-instructions/{action}")
def ai_instruction_http(
    action: ai_prompts.Action, request: Request
) -> ai_prompts.EditorView:
    _require_principal(request)
    return ai_prompts.editor(action)


class PromptPreviewBody(BaseModel):
    text: str = PydField(max_length=100000)


@app.post("/api/ai-instructions/{action}/preview")
def ai_instruction_preview_http(
    action: ai_prompts.Action, body: PromptPreviewBody, request: Request
) -> dict[str, str]:
    _require_principal(request)
    return {"preview": ai_prompts.preview(action, body.text)}


@app.get("/api/product-settings")
def read_product_settings(request: Request) -> product_settings.SettingsView:
    from fastapi import HTTPException

    principal = _require_principal(request)
    try:
        return product_settings.view(principal)
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.patch("/api/product-settings")
def save_product_settings(
    body: product_settings.SaveSettings, request: Request
) -> product_settings.Snapshot:
    from fastapi import HTTPException

    principal = _require_admin(request)
    try:
        saved = product_settings.save(body, principal)
        if isinstance(body.settings, product_settings.ConcurrencySettings):
            anyio.from_thread.run_sync(lambda: server.limiter_for("ask"))
        return saved
    except model_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/model-settings")
def ai_model_settings(request: Request) -> model_settings.SettingsView:
    from fastapi import HTTPException

    principal = _require_principal(request)
    try:
        return model_settings.view(principal)
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.patch("/api/model-settings/{action}")
def save_ai_model_settings(
    action: model_settings.Action, body: model_settings.SaveSelection, request: Request
) -> model_settings.ActionView:
    from fastapi import HTTPException

    principal = _require_admin(request)
    try:
        model_settings.save(action, body, principal)
        return model_settings.action_view(action)
    except model_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except model_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/draft-review/settings")
def draft_review_settings(request: Request) -> review_settings.SettingsView:
    from fastapi import HTTPException

    principal = _require_principal(request)
    try:
        return review_settings.view(principal)
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.patch("/api/draft-review/settings")
def save_draft_review_settings(
    body: review_settings.SaveSettings, request: Request
) -> review_settings.SettingsView:
    from fastapi import HTTPException

    principal = _require_admin(request)
    try:
        review_settings.save(body, principal)
        return review_settings.view(principal)
    except review_settings.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/api/draft-review/backlog")
def draft_review_backlog(request: Request) -> dict[str, list[str]]:
    """Submitted drafts the current review configuration has not reached, to
    offer reviewing them once when review is switched on."""
    from fastapi import HTTPException

    from .. import draft_review_runs

    _require_admin(request)
    try:
        return {"draft_ids": draft_review_runs.backlog()}
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.post("/api/draft-review/backlog")
def review_draft_backlog(request: Request) -> dict[str, list[str]]:
    """Start reviewing every draft in the backlog; returns their ids."""
    from fastapi import HTTPException

    from .. import draft_review_runs

    _require_admin(request)
    try:
        return {"draft_ids": draft_review_runs.review_backlog()}
    except review_settings.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.post("/api/drafts/{draft_id}/review")
def run_draft_review_http(
    draft_id: str, request: Request
) -> dict[str, dict[str, JsonValue]]:
    _enforce_curator(request, action="running an internal draft review")
    return {"review": server.request_draft_review(draft_id, rerun=True)}


class DraftReviewAnswerBody(BaseModel):
    run_id: str
    answer: str


@app.post("/api/drafts/{draft_id}/review/answer")
def answer_draft_review_http(
    draft_id: str, body: DraftReviewAnswerBody, request: Request
) -> dict[str, dict[str, JsonValue]]:
    """Answer the internal reviewer's questions; the draft is reviewed again."""
    from pydantic import ValidationError

    from .. import draft_review_runs

    principal = _enforce_curator(request, action="answering the internal reviewer")
    try:
        run = draft_review_runs.answer(draft_id, body.run_id, body.answer, principal)
    except ValidationError as exc:
        raise ValueError("answer must be 1 to 6000 characters") from exc
    return {"review": run.model_dump(mode="json")}


def _serialize_draft(row, *, ops=None) -> dict[str, Any]:
    from .. import drafts_store

    return drafts_store.serialize_draft(row, ops=ops)


class DocumentationRequestBody(BaseModel):
    prompt: str
    guideline_set: str | None = None
    document_type: str | None = None
    provider: Literal["claude", "openai"] | None = None
    anchor_entity_id: str | None = None


@app.get("/api/documentation/options")
def documentation_options(request: Request) -> dict[str, object]:
    principal = _require_principal(request)
    from .. import guidelines, prompt_store
    from ..docgen.config import DocgenConfig

    return {
        **server.list_documentation_models(),
        "can_generate": auth.principal_has_real_role(principal, "writer"),
        "guideline_sets": guidelines.catalogue(prompt_store.connection()),
        "max_prompt_chars": DocgenConfig.from_env().max_prompt_chars,
    }


@app.post("/api/documentation/runs")
def request_documentation_http(
    body: DocumentationRequestBody, request: Request
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return server.request_documentation(**body.model_dump(), match_existing=False)


@app.get("/api/documentation/runs")
def documentation_runs_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_documentation_runs()


@app.get("/api/documentation/runs/{run_id}")
def documentation_run_http(run_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    try:
        return server.get_documentation_run(run_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


class DocumentEditBody(ManualDocument):
    provider: Literal["claude", "openai"] | None = None


class SavedDocumentEditBody(DocumentEditBody):
    expected_revision: int = PydField(ge=1, strict=True)


@app.post("/api/documentation/preview")
def preview_document_edit(body: ManualDocument, request: Request) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return _document_preview({"body": body.body})


@app.post("/api/documentation/documents/{document_id}/edits")
def edit_saved_document_http(
    document_id: str, body: SavedDocumentEditBody, request: Request
) -> dict[str, object]:
    from .. import docs_store, document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    try:
        run_id = document_edits.start_document_edit(
            server._drafts_db(),
            document_id,
            body.expected_revision,
            ManualDocument(title=body.title, body=body.body),
            created_by=principal.id,
            provider=body.provider,
        )
    except docs_store.RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return server.get_documentation_run(run_id)


@app.post("/api/documentation/runs/{run_id}/edits")
def edit_document_draft_http(
    run_id: str, body: DocumentEditBody, request: Request
) -> dict[str, object]:
    from .. import docs_store, document_edits

    _enforce_role(request, "writer", real_role=True)
    principal = _require_principal(request)
    try:
        new_run_id = document_edits.start_draft_edit(
            server._drafts_db(),
            run_id,
            ManualDocument(title=body.title, body=body.body),
            created_by=principal.id,
            provider=body.provider,
        )
    except docs_store.RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return server.get_documentation_run(new_run_id)


class DocumentRevisionBody(BaseModel):
    prompt: str
    expected_revision: int = PydField(ge=1, strict=True)
    provider: Literal["claude", "openai"] | None = None
    start_from_destination: bool = False


class DocumentDeliveryBody(BaseModel):
    destination: str
    expected_revision: int = PydField(ge=1, strict=True)


def _document_preview(document: dict[str, object]) -> dict[str, object]:
    from markdown_it import MarkdownIt

    body = document.get("body")
    return {
        **document,
        "body_html": MarkdownIt("js-default").disable("image").render(body)
        if isinstance(body, str)
        else "",
    }


@app.get("/api/documentation/documents")
def generated_documents_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_generated_documents()


@app.get("/api/documentation/destinations")
def documentation_destinations_http(request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_documentation_destinations()


@app.get("/api/documentation/documents/{document_id}")
def generated_document_http(document_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    try:
        return _document_preview(server.get_generated_document(document_id))
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/documentation/documents/{document_id}/revisions")
def document_revisions_http(document_id: str, request: Request) -> dict[str, object]:
    _require_principal(request)
    return server.list_document_revisions(document_id)


@app.get("/api/documentation/documents/{document_id}/revisions/{revision}")
def document_revision_http(
    document_id: str, revision: int, request: Request
) -> dict[str, object]:
    _require_principal(request)
    try:
        return _document_preview(server.get_document_revision(document_id, revision))
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.exception_handler(BothSidesEdited)
async def _both_sides_edited_handler(
    request: Request, exc: BothSidesEdited
) -> JSONResponse:
    """A conflict the caller resolves by choosing a side, so the client gets a
    code to offer `start_from_destination` on rather than a message to parse."""
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "code": "both_sides_edited"}
    )


@app.post("/api/documentation/documents/{document_id}/revisions")
def revise_document_http(
    document_id: str, body: DocumentRevisionBody, request: Request
) -> dict[str, object]:
    from fastapi import HTTPException

    from ..docs_store import RevisionConflict

    _enforce_role(request, "writer", real_role=True)
    try:
        return server.revise_document(document_id, **body.model_dump())
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/documentation/documents/{document_id}/delivery")
def deliver_document_http(
    document_id: str, body: DocumentDeliveryBody, request: Request
) -> dict[str, object]:
    from fastapi import HTTPException

    from ..docs_store import RevisionConflict

    _enforce_role(request, "writer", real_role=True)
    try:
        return server.deliver_document(document_id, **body.model_dump())
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/drafts")
def list_drafts(request: Request, status: str | None = None) -> dict[str, Any]:
    """List drafts, newest first. `status` filters to one of:
    open / submitted / approved / rejected / withdrawn / all (default).
    """
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    status = status or "all"
    if status not in ("all", "open", "submitted", "approved", "rejected", "withdrawn"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="status must be one of: all, open, submitted, approved, rejected, withdrawn",
        )
    rows = drafts_store.list_drafts(conn, status=status)
    counts = drafts_store.count_ops_by_draft(conn)
    out = []
    for r in rows:
        d = drafts_store.serialize_draft(r)
        d["op_count"] = counts.get(r["id"], 0)
        out.append(d)
    return {"drafts": out}


@app.get("/api/drafts/{draft_id}")
def get_draft_detail(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row, ops = drafts_store.get_draft_snapshot(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    return {"draft": drafts_store.serialize_draft(row, ops=ops)}


class DraftOpEditBody(BaseModel):
    payload: dict[str, Any]
    expected_revision: int | None = None


@app.patch("/api/drafts/{draft_id}/ops/{seq}")
def edit_draft_op(
    draft_id: str, seq: int, body: DraftOpEditBody, request: Request
) -> dict[str, Any]:
    """Replace an op's payload on an open or submitted draft."""
    _enforce_curator(request, action="editing a draft operation")
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="draft not found")
        status = drafts_store.status_for(row)
        if status not in ("open", "submitted"):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"cannot edit ops on a {status} draft",
            )
        try:
            revision = drafts_store.update_op_payload(
                conn,
                draft_id,
                seq,
                body.payload,
                expected_revision=body.expected_revision,
            )
        except (
            drafts_store.StaleDraftRevisionError,
            drafts_store.ActiveApplicationError,
        ) as ex:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(ex)) from ex
    if revision is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True, "revision": revision}


@app.delete("/api/drafts/{draft_id}/ops/{seq}")
def remove_draft_op_http(
    draft_id: str,
    seq: int,
    request: Request,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    _enforce_curator(request, action="removing a draft operation")
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="draft not found")
        status = drafts_store.status_for(row)
        if status not in ("open", "submitted"):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"cannot remove ops from a {status} draft",
            )
        try:
            revision = drafts_store.remove_op(
                conn, draft_id, seq, expected_revision=expected_revision
            )
        except (
            drafts_store.StaleDraftRevisionError,
            drafts_store.ActiveApplicationError,
        ) as ex:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(ex)) from ex
    if revision is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="op seq not found")
    return {"ok": True, "revision": revision}


class DraftDecisionBody(BaseModel):
    # Only meaningful for /approve and /reject — submit takes no body.
    pass


@app.post("/api/drafts/{draft_id}/submit")
def submit_draft_http(draft_id: str, request: Request) -> dict[str, Any]:
    _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    if drafts_store.status_for(row) != "open":
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="only open drafts can be submitted",
        )
    with store.transaction(conn):
        drafts_store.set_submitted(conn, draft_id)
    from .. import draft_review_runs

    draft_review_runs.on_submitted(draft_id)
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, request: Request) -> dict[str, Any]:
    """Replay the draft's ops against the substrate as the curator.

    Requires real writer+ (not drafter — see `_enforce_curator`).
    All-or-nothing: a single op failure halts replay and leaves the
    draft in its prior state so the curator can edit and retry. When a
    tool refuses statements (the phrasing linter), the 422 detail lists
    each one under `rejections` so the curator can fix them.
    """
    p = _enforce_curator(request)
    from .. import drafts_store

    conn = server._drafts_db()
    try:
        with store.write_lock():
            result = server.apply_draft(draft_id)
            with store.transaction(conn):
                drafts_store.set_decision(conn, draft_id, decision="approved", by=p.id)
    except drafts_store.ActiveApplicationError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except server.DraftOpsRejectedError as ex:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail={
                "message": "Nothing was applied: fix or discard the refused "
                "statements, then approve again.",
                "rejections": ex.rejections,
            },
        ) from ex
    except (ValueError, RuntimeError) as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, **result}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _enforce_curator(request)
    from .. import drafts_store

    conn = server._drafts_db()
    with store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="draft not found")
        if drafts_store.status_for(row) not in ("open", "submitted"):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="only open or submitted drafts can be rejected",
            )
        try:
            drafts_store.set_decision(conn, draft_id, decision="rejected", by=p.id)
        except drafts_store.ActiveApplicationError as ex:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(ex)) from ex
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/withdraw")
def withdraw_draft(draft_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    from .. import drafts_store

    conn = server._drafts_db()
    row = drafts_store.get_draft(conn, draft_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="draft not found")
    if drafts_store.status_for(row) not in ("open", "submitted"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="only open or submitted drafts can be withdrawn",
        )
    with store.transaction(conn):
        try:
            drafts_store.set_decision(conn, draft_id, decision="withdrawn", by=p.id)
        except drafts_store.ActiveApplicationError as ex:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail=str(ex)) from ex
    return {"ok": True}


# --- admin: user & invite management --------------------------------------
# All endpoints require `role == admin`. Service accounts (type=service)
# represent third-party agents; they can hold tokens but never log in
# through OIDC.


def _serialize_user_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "oidc_issuer": row["oidc_issuer"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


@app.get("/api/admin/users")
def list_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_users(conn)
    return {"users": [_serialize_user_row(r) for r in rows]}


class CreateUserBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=120)
    role: auth.Role = "writer"
    type: auth.UserType = "service"
    email: str | None = None


@app.post("/api/admin/users")
def create_user(body: CreateUserBody, request: Request) -> dict[str, Any]:
    """Create a service account (the common case) or a pre-provisioned
    human row. Humans created here still need an invite or a matching
    OIDC bootstrap to actually log in — this endpoint is most useful
    for service accounts whose entire identity is their tokens."""
    admin = _require_admin(request)
    if body.type == "human" and not body.email:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="human users require an email")
    conn = runtime._auth_db()
    with store.transaction(conn):
        user_id = auth.create_user(
            conn,
            name=body.name,
            role=body.role,
            type=body.type,
            email=body.email,
            created_by=admin.id,
        )
    row = auth.get_user(conn, user_id)
    return {"user": _serialize_user_row(row)}


class UpdateUserBody(BaseModel):
    role: auth.Role | None = None
    status: str | None = None  # 'active' | 'suspended'
    name: str | None = None


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id: str, body: UpdateUserBody, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            row = auth.update_user(
                conn,
                user_id,
                role=body.role,
                status=body.status,
                name=body.name,
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"user": _serialize_user_row(row)}


@app.get("/api/admin/users/{user_id}/tokens")
def list_user_tokens(user_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_tokens(conn, user_id)
    return {"tokens": [_serialize_token_row(r) for r in rows]}


class MintTokenBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=80)
    scope: auth.Scope = "writer"


@app.post("/api/admin/users/{user_id}/tokens")
def mint_token_for_user(
    user_id: str, body: MintTokenBody, request: Request
) -> dict[str, Any]:
    """Admin path to mint a token for any user — typically used to
    create the initial token for a freshly-created service account.
    The scope is still capped by the target user's role."""
    _require_admin(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            raw, row = auth.mint_token_for_user(
                conn, user_id=user_id, name=body.name, scope=body.scope
            )
    except LookupError as ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(ex))
    return {"token": raw, **_serialize_token_row(row)}


@app.delete("/api/admin/tokens/{token_id}")
def revoke_token_admin(token_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_token(conn, token_id)
    return {"ok": True}


def _serialize_invite_row(row, *, request: Request) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "link": str(request.url_for("accept_invite", token=row["token"])),
    }


@app.get("/api/admin/invites")
def list_invites(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_invites(conn)
    return {"invites": [_serialize_invite_row(r, request=request) for r in rows]}


class CreateInviteBody(BaseModel):
    email: str = PydField(..., min_length=3, max_length=254)
    role: auth.Role = "writer"


@app.post("/api/admin/invites")
def create_invite(body: CreateInviteBody, request: Request) -> dict[str, Any]:
    admin = _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        row = auth.create_invite(
            conn, email=body.email, role=body.role, invited_by=admin.id
        )
    return _serialize_invite_row(row, request=request)


@app.delete("/api/admin/invites/{invite_id}")
def revoke_invite(invite_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_invite(conn, invite_id)
    return {"ok": True}


@app.get("/auth/invite/{token}", name="accept_invite")
def accept_invite(token: str) -> RedirectResponse:
    """Invite landing — bounces to /auth/login, then on to /connect.

    New invitees arrive without knowing anything about Mycelium yet;
    landing them on /connect (with the client-setup steps) is more
    useful than landing them on the substrate graph at /ui/. They can
    still navigate to /ui/ from there once they're authenticated.

    The invite token itself isn't carried through query params — the
    OIDC callback's `find_or_create_user` consumes whichever active
    invite matches the verified email it gets back from the provider.
    Passing the token here was redundant.
    """
    return RedirectResponse(url="/auth/login?next=/connect")


@app.get("/connect", include_in_schema=False)
def _connect_page() -> Any:
    """Standalone setup-guide page. Reachable without loading the main
    UI bundle so users coming straight to this URL (from docs, a chat
    handoff, an admin's email) don't pay for the graph viz they're
    not about to use."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=connect_page.CONNECT_HTML)


@app.get("/", include_in_schema=False)
def _root_redirect() -> RedirectResponse:
    # The substrate viewer at /ui/ is intentionally not the landing
    # page — it's only useful once you're logged in. Visitors land on
    # the connect / setup page instead, which is public and tells them
    # how to authenticate and get a token.
    return RedirectResponse(url="/connect")


# The browser app is built from `frontend/` into `webui/`, which is committed so
# the server runs without Node.
_WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
_UI_DIR = _WEBUI_DIR / "ui"
app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")


# Serve the app at the bare /ui path too. Starlette would normally redirect
# /ui -> /ui/ via redirect_slashes, but the catch-all MCP sub-app mounted at "/"
# below matches /ui first, so that automatic redirect never fires. Register it
# here, ahead of the "/" mount.
@app.get("/ui", include_in_schema=False)
def _ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# /cockpit was a second app, merged into /ui. Old links redirect permanently;
# the browser keeps the #fragment across a redirect, and /ui resolves the
# cockpit's old hash routes.
@app.get("/cockpit", include_in_schema=False)
@app.get("/cockpit/{rest:path}", include_in_schema=False)
def _cockpit_redirect(rest: str = "") -> RedirectResponse:
    return RedirectResponse(url="/ui/", status_code=301)


@app.exception_handler(alias_suggestions.Conflict)
async def alias_suggestion_conflict(
    request: Request, exc: alias_suggestions.Conflict
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/alias-suggestions")
def alias_suggestions_http(
    request: Request, status: str = "pending"
) -> dict[str, object]:
    _enforce_role(request, "reader")
    return {
        "suggestions": [
            entry.model_dump(mode="json")
            for entry in alias_suggestions.list_entries(status)
        ]
    }


@app.post("/api/alias-suggestions/scan")
def scan_alias_suggestions_http(
    request: Request, body: alias_suggestions.ScanRequest
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    return alias_suggestions.scan(body, _require_principal(request)).model_dump(
        mode="json"
    )


@app.post("/api/alias-suggestions/{draft_id}/{operation_ref}/review")
def review_alias_suggestion_http(
    draft_id: str,
    operation_ref: str,
    request: Request,
    body: alias_suggestions.ReviewRequest,
) -> dict[str, object]:
    _enforce_role(request, "writer", real_role=True)
    from .. import drafts_store

    try:
        entry = alias_suggestions.review(
            draft_id, operation_ref, body, _require_principal(request)
        )
    except (
        drafts_store.StaleDraftRevisionError,
        drafts_store.ActiveApplicationError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return entry.model_dump(mode="json")


# --- MCP transport mount --------------------------------------------------
# Remote MCP clients (Claude Desktop, Claude Code) connect to
# `https://host/mcp`. The streamable-HTTP sub-app exposes `/mcp`
# at its root, so mounting that sub-app at `/` makes the public path
# `/mcp` exactly. Mounted last so it can't shadow explicit routes
# above — Starlette matches routes in registration order, and a
# zero-prefix mount matches everything.
#
# Auth: `AuthMiddleware` is installed on the parent app and applies to
# mounted sub-apps. It resolves the bearer header into a `Principal`
# and stashes it in the `current_principal` ContextVar before the
# JSON-RPC dispatcher inside the sub-app runs. The per-tool role gate
# in `server.tool` reads that ContextVar.
app.mount("/", _MCP_SUBAPP)


def main() -> None:
    # Local-dev convenience: read a `.env` from the working dir. A no-op in
    # deploy — ECS/systemd inject env before the process starts, and
    # load_dotenv never overrides an already-set variable.
    load_dotenv()
    host = os.environ.get("MYCELIUM_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("MYCELIUM_HTTP_PORT", "8765"))
    uvicorn.run(app, host=host, port=port)
