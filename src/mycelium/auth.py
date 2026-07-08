"""Authentication & authorization for the HTTP / MCP surface.

Three concepts:

- **Toggle.** `MYCELIUM_AUTH` env var. Default `off` so local single-user
  setups keep working unchanged. When off, every request runs as a
  synthetic `local-admin` principal — no login, no token required, all
  permissions granted. When `on`, every request must carry a resolvable
  session cookie or bearer token, or it's rejected by `require_auth`.

- **Principal.** The acting identity for a request. May be a stored
  `users` row (resolved from a session or token) or the synthetic
  local-admin when the toggle is off. Always present on
  `request.state.principal` after the middleware runs — handlers never
  have to None-check it.

- **MCP tokens.** Opaque, format `myc_<prefix>_<secret>`. The prefix is
  stored in plaintext for UI display; the secret part is sha256-hashed
  and never stored raw. The full token is returned to the user exactly
  once at creation. Scopes (`reader` / `writer` / `admin`) are capped at
  the owner's role at issuance time and re-clamped against the live
  user role on every request (so demoting a user immediately narrows
  every token they hold).

The synthetic local-admin has id `local-admin`, role `admin`, and never
appears in the `users` table — it's purely an in-memory placeholder so
the rest of the codebase can treat the principal uniformly regardless
of toggle state.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Role = Literal["asker", "reader", "drafter", "writer", "admin"]
UserType = Literal["human", "service"]
Scope = Literal["asker", "reader", "drafter", "writer", "admin"]

# Ordering used to clamp a token's scope against its owner's role.
# Lower-privilege scopes are always allowed; never widen. Drafter sits
# between reader and writer: a drafter can call every write/delete/merge
# tool, but the call body redirects to a draft instead of mutating the
# substrate (see `server.tool` wrapper). Asker sits below reader: it can
# reach only the single tool that requires the `asker` role (`ask`) and
# none of the broader read primitives — every higher role outranks it
# and so keeps `ask` too.
_ROLE_RANK: dict[str, int] = {
    "asker": 0,
    "reader": 1,
    "drafter": 2,
    "writer": 3,
    "admin": 4,
}

LOCAL_ADMIN_ID = "local-admin"
TOKEN_PREFIX = "myc"


# --- principal -------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The acting identity for a request.

    `synthetic=True` flags the local-admin placeholder used when auth
    is disabled. Handlers that record attribution should still write
    `id` to `created_by` — having `local-admin` show up in audit fields
    is the honest answer when no real user is signed in.
    """

    id: str
    name: str
    role: Role
    type: UserType
    synthetic: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.role in ("writer", "admin")


LOCAL_ADMIN = Principal(
    id=LOCAL_ADMIN_ID,
    name="Local admin",
    role="admin",
    type="human",
    synthetic=True,
)


# Active principal for the current request / task. Set by `AuthMiddleware`
# right after resolving credentials; read by the MCP `@tool` wrapper to
# gate writes (the FastAPI handlers gate via `_enforce_role` directly on
# the request, but MCP tools live inside a Starlette sub-app and don't
# have the parent request object in scope).
#
# ContextVar (not threadlocal) so async tasks under the same request
# inherit the value automatically without manual plumbing.
current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "mycelium_current_principal",
    default=None,
)


# MCP session id for the current request. Populated by `AuthMiddleware`
# from the `mcp-session-id` header that the streamable-HTTP transport
# sets after `initialize`. Read by the drafter-redirect path in
# `server.tool` to find/create a per-session auto-draft. None for
# non-MCP requests (e.g. /api/* calls from the UI) — those never need
# session-scoped drafts.
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mycelium_current_session_id",
    default=None,
)


# --- role classification --------------------------------------------------
# Naming conventions in `server.py` are the source of truth for what a
# tool does. Read tools start with one of `_READ_PREFIXES`; destructive
# operations start with `_ADMIN_PREFIXES`; everything else is a write.
# Used by both the REST mirror (http.py) and the MCP @tool wrapper
# (server.py) so the two surfaces enforce the same policy.

_READ_PREFIXES = ("list_", "get_", "search_", "grep_", "discover_", "find_")
_ADMIN_PREFIXES = ("delete_", "merge_")

_ROLE_RANK_FULL: dict[str, int] = {
    "asker": 0,
    "reader": 1,
    "drafter": 2,
    "writer": 3,
    "admin": 4,
}


def required_role_for(func_name: str) -> Role:
    if func_name.startswith(_ADMIN_PREFIXES):
        return "admin"
    if func_name.startswith(_READ_PREFIXES):
        return "reader"
    return "writer"


def principal_satisfies(principal: "Principal", required: str) -> bool:
    # Drafters can invoke every write/delete/merge tool: the @tool wrapper
    # intercepts and redirects their calls to a draft instead of touching
    # the substrate. So for gate purposes a drafter satisfies writer AND
    # admin requirements. Reads still gate normally (drafter > reader).
    if principal.role == "drafter" and required in ("writer", "admin"):
        return True
    return _ROLE_RANK_FULL[principal.role] >= _ROLE_RANK_FULL[required]


def is_valid_role(role: str) -> bool:
    """True when `role` is one of the recognized roles. Used to validate
    externally-supplied role names (e.g. the JIT default role from an env
    var) before trusting them to grant a privilege level."""
    return role in _ROLE_RANK_FULL


def principal_has_real_role(principal: "Principal", required: str) -> bool:
    """Strict role check that *ignores* the drafter-equivalence shortcut.

    Used by curator-only operations (approve/reject a draft) where the
    redirect-friendly behaviour of `principal_satisfies` would let a
    drafter through and break the replay path. Pure rank comparison —
    a drafter does not pass `required='writer'` here.
    """
    return _ROLE_RANK_FULL[principal.role] >= _ROLE_RANK_FULL[required]


# --- toggle ---------------------------------------------------------------


def is_enabled() -> bool:
    """Read the toggle. Defaults to off — a fresh checkout running
    `mycelium serve` works with no env vars and no Auth0 config."""
    return (os.environ.get("MYCELIUM_AUTH") or "off").lower() == "on"


# --- token helpers --------------------------------------------------------


def generate_token() -> tuple[str, str, str]:
    """Mint a new MCP token. Returns `(raw_token, prefix, hash)`.

    Format: `myc_<6char-prefix>_<43char-secret>` (≈256 bits of entropy
    in the secret). The prefix is also random so users can recognize
    one token among many in the UI without ever re-seeing the secret.
    Only `prefix` and `hash` are persisted; `raw_token` is returned to
    the caller once and never reconstructable afterward.
    """
    prefix = secrets.token_hex(3)  # 6 hex chars
    secret = secrets.token_urlsafe(32)
    raw = f"{TOKEN_PREFIX}_{prefix}_{secret}"
    return raw, prefix, hash_token(raw)


def hash_token(raw: str) -> str:
    """sha256 of the full token string, lowercase hex. Used at both
    issuance (to store) and verification (to look up)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_bearer(header_value: str | None) -> str | None:
    """Extract a `myc_…` token from an `Authorization: Bearer …` header.
    Returns None when the header is missing, not a bearer, or doesn't
    carry a mycelium-formatted token. Defensive: callers can treat any
    None as 'no usable credential present.'"""
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token.startswith(f"{TOKEN_PREFIX}_"):
        return None
    return token


# --- principal resolution -------------------------------------------------


def _clamp_scope(scope: str, role: str) -> Role:
    """A token's effective role is min(scope, current_user_role). Lets
    admins demote themselves at issuance time (a read-only token for a
    sandbox agent) AND lets a later user demotion narrow every existing
    token transparently."""
    if _ROLE_RANK[scope] <= _ROLE_RANK[role]:
        return scope  # type: ignore[return-value]
    return role  # type: ignore[return-value]


def resolve_token(conn: sqlite3.Connection, raw_token: str) -> Principal | None:
    """Look up a bearer token and return the authenticated principal.
    Returns None when the token is unknown, revoked, or its owner is
    suspended/missing. Bumps `last_used_at` on a hit.
    """
    row = conn.execute(
        """
        SELECT t.id AS token_id, t.scope, t.revoked_at,
               u.id AS user_id, u.name, u.role, u.type, u.status
        FROM mcp_tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.hash = ?
        """,
        (hash_token(raw_token),),
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["status"] != "active":
        return None
    conn.execute(
        "UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["token_id"]),
    )
    conn.commit()
    return Principal(
        id=row["user_id"],
        name=row["name"],
        role=_clamp_scope(row["scope"], row["role"]),
        type=row["type"],
    )


def resolve_session_user(
    conn: sqlite3.Connection, user_id: str | None
) -> Principal | None:
    """Look up a session-cookie-derived user id. Returns None when the
    id no longer maps to an active user (account deleted or suspended
    mid-session)."""
    if not user_id:
        return None
    row = conn.execute(
        "SELECT id, name, role, type, status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        return None
    return Principal(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        type=row["type"],
    )


# --- user / token writes --------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_user(
    conn: sqlite3.Connection,
    *,
    name: str,
    role: Role,
    type: UserType,
    email: str | None = None,
    oidc_issuer: str | None = None,
    oidc_subject: str | None = None,
    created_by: str | None = None,
) -> str:
    """Insert a `users` row and return its id. Caller is responsible
    for committing — kept transaction-neutral so callers can batch
    user creation with related writes (e.g. consuming an invite)."""
    user_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO users
            (id, type, email, name, role, status, oidc_issuer, oidc_subject,
             created_at, created_by)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            user_id,
            type,
            email,
            name,
            role,
            oidc_issuer,
            oidc_subject,
            _now(),
            created_by,
        ),
    )
    return user_id


def issue_token(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    name: str,
    scope: Scope,
) -> tuple[str, str]:
    """Mint and persist a new MCP token. Returns `(raw_token, token_id)`.
    The raw token is the one-time secret to show the user; the token_id
    is the row id for later management.

    Caller is expected to have already validated that `scope` is ≤ the
    issuing user's role — `resolve_token` re-clamps at lookup time, but
    accepting a scope > role at issuance would be a UI bug, not a
    security one (the clamp would silently demote it).
    """
    raw, prefix, h = generate_token()
    token_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO mcp_tokens
            (id, user_id, name, prefix, hash, scope, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (token_id, user_id, name, prefix, h, scope, _now()),
    )
    conn.commit()
    return raw, token_id


def revoke_token(conn: sqlite3.Connection, token_id: str) -> None:
    """Mark a token revoked. Idempotent: a second revoke is a no-op."""
    conn.execute(
        "UPDATE mcp_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
        (_now(), token_id),
    )
    conn.commit()
