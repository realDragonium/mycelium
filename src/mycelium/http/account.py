"""The caller's own account: who they are, their MCP tokens, and where to connect.

Used by the bundled UI's settings page. The synthetic local admin may mint
tokens too — handy in single-user local mode for bootstrapping an MCP client
without ever enabling auth.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import auth, quarantine, store
from ..server import runtime
from .access import _require_principal

router = APIRouter()


def _serialize_token_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "scope": row["scope"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


@router.get("/api/server-info")
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
        "quarantine": quarantine.active(),
        # Before startup is ready the startup gate answers this path instead.
        "state": "ready",
    }


@router.get("/api/me")
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


@router.get("/api/me/tokens")
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


@router.post("/api/me/tokens")
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


@router.delete("/api/me/tokens/{token_id}")
def revoke_my_token(token_id: str, request: Request) -> dict[str, Any]:
    p = _require_principal(request)
    conn = runtime._auth_db()
    try:
        with store.transaction(conn):
            auth.revoke_own_token(
                conn, token_id=token_id, owner_id=auth.owner_id_for(p)
            )
    except LookupError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return {"ok": True}
