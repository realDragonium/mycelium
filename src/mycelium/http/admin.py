"""Admin user, token and invite management, plus the invite landing page.

Every `/api/admin/*` endpoint requires the admin role. Service accounts
(type=service) represent third-party agents; they can hold tokens but never
log in through OIDC.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import auth, store
from ..server import runtime
from .access import _require_admin
from .account import _serialize_token_row

router = APIRouter()


def _serialize_user_row(row: sqlite3.Row) -> dict[str, Any]:
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


@router.get("/api/admin/users")
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


@router.post("/api/admin/users")
def create_user(body: CreateUserBody, request: Request) -> dict[str, Any]:
    """Create a service account (the common case) or a pre-provisioned
    human row. Humans created here still need an invite or a matching
    OIDC bootstrap to actually log in — this endpoint is most useful
    for service accounts whose entire identity is their tokens."""
    admin = _require_admin(request)
    if body.type == "human" and not body.email:
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
    assert row is not None
    return {"user": _serialize_user_row(row)}


class UpdateUserBody(BaseModel):
    role: auth.Role | None = None
    status: str | None = None  # 'active' | 'suspended'
    name: str | None = None


@router.patch("/api/admin/users/{user_id}")
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
        raise HTTPException(status_code=404, detail=str(ex))
    return {"user": _serialize_user_row(row)}


@router.get("/api/admin/users/{user_id}/tokens")
def list_user_tokens(user_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_tokens(conn, user_id)
    return {"tokens": [_serialize_token_row(r) for r in rows]}


class MintTokenBody(BaseModel):
    name: str = PydField(..., min_length=1, max_length=80)
    scope: auth.Scope = "writer"


@router.post("/api/admin/users/{user_id}/tokens")
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
        raise HTTPException(status_code=404, detail=str(ex))
    return {"token": raw, **_serialize_token_row(row)}


@router.delete("/api/admin/tokens/{token_id}")
def revoke_token_admin(token_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_token(conn, token_id)
    return {"ok": True}


def _serialize_invite_row(row: sqlite3.Row, *, request: Request) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "link": str(request.url_for("accept_invite", token=row["token"])),
    }


@router.get("/api/admin/invites")
def list_invites(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    rows = auth.list_invites(conn)
    return {"invites": [_serialize_invite_row(r, request=request) for r in rows]}


class CreateInviteBody(BaseModel):
    email: str = PydField(..., min_length=3, max_length=254)
    role: auth.Role = "writer"


@router.post("/api/admin/invites")
def create_invite(body: CreateInviteBody, request: Request) -> dict[str, Any]:
    admin = _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        row = auth.create_invite(
            conn, email=body.email, role=body.role, invited_by=admin.id
        )
    return _serialize_invite_row(row, request=request)


@router.delete("/api/admin/invites/{invite_id}")
def revoke_invite(invite_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = runtime._auth_db()
    with store.transaction(conn):
        auth.revoke_invite(conn, invite_id)
    return {"ok": True}


@router.get("/auth/invite/{token}", name="accept_invite")
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
