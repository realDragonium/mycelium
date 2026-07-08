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

# Ordering used both to clamp a token's scope against its owner's role
# and to compare a principal's role against a tool's required role.
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
    return _ROLE_RANK[principal.role] >= _ROLE_RANK[required]


def is_valid_role(role: str) -> bool:
    """True when `role` is one of the recognized roles. Used to validate
    externally-supplied role names (e.g. the JIT default role from an env
    var) before trusting them to grant a privilege level."""
    return role in _ROLE_RANK


def principal_has_real_role(principal: "Principal", required: str) -> bool:
    """Strict role check that *ignores* the drafter-equivalence shortcut.

    Used by curator-only operations (approve/reject a draft) where the
    redirect-friendly behaviour of `principal_satisfies` would let a
    drafter through and break the replay path. Pure rank comparison —
    a drafter does not pass `required='writer'` here.
    """
    return _ROLE_RANK[principal.role] >= _ROLE_RANK[required]


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


# --- HTTP admin surface: user / token / invite queries --------------------
# Named helpers backing the /api/me and /api/admin endpoints. Each endpoint
# stays translation-only (parse request → call helper → serialize row);
# every query and every business rule (token ownership, the last-admin
# guard) lives here. Reads return raw `sqlite3.Row`s so the HTTP layer keeps
# its own presentation shaping. Not-found conditions raise `LookupError`
# (endpoints map that to 404); rule violations raise `ValueError` (mapped to
# 400 by the app-wide handler). Write helpers follow the same commit
# discipline as `create_user` / `issue_token` above — noted per helper.


def owner_id_for(principal: Principal) -> str:
    """The `users.id` that owns a principal's personal tokens. The synthetic
    local-admin owns its tokens under `LOCAL_ADMIN_ID`, not its in-memory
    placeholder id."""
    return LOCAL_ADMIN_ID if principal.synthetic else principal.id


def list_tokens(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    """Every MCP token owned by `user_id`, newest first. Revoked tokens are
    included (the UI greys them out rather than hiding them)."""
    return conn.execute(
        "SELECT id, name, prefix, scope, created_at, last_used_at, revoked_at "
        "FROM mcp_tokens WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()


def get_token(conn: sqlite3.Connection, token_id: str) -> sqlite3.Row | None:
    """A single token row by id, or None. Used to read back a freshly minted
    token for serialization."""
    return conn.execute(
        "SELECT id, name, prefix, scope, created_at, last_used_at, revoked_at "
        "FROM mcp_tokens WHERE id = ?",
        (token_id,),
    ).fetchone()


def _ensure_local_admin_row(conn: sqlite3.Connection) -> str:
    """Lazily materialize a real `users` row for the synthetic local-admin so
    it can own tokens, and return its id (`LOCAL_ADMIN_ID`). The row stays
    invisible until auth is switched on. Commits on first creation."""
    existing = conn.execute(
        "SELECT id FROM users WHERE id = ?", (LOCAL_ADMIN_ID,)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO users (id, type, name, role, status, created_at) "
            "VALUES (?, 'human', 'Local admin', 'admin', 'active', ?)",
            (LOCAL_ADMIN_ID, _now()),
        )
        conn.commit()
    return LOCAL_ADMIN_ID


def mint_own_token(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    name: str,
    scope: Scope,
) -> tuple[str, sqlite3.Row]:
    """Mint a token owned by the calling principal, capping `scope` at the
    principal's current role. Returns `(raw_token, token_row)` — the raw
    secret to show once plus the persisted row for serialization. Commits
    (via `_ensure_local_admin_row` / `issue_token`)."""
    capped = _clamp_scope(scope, principal.role)
    owner_id = _ensure_local_admin_row(conn) if principal.synthetic else principal.id
    raw, token_id = issue_token(conn, user_id=owner_id, name=name, scope=capped)
    row = get_token(conn, token_id)
    assert row is not None  # just inserted
    return raw, row


def revoke_own_token(conn: sqlite3.Connection, *, token_id: str, owner_id: str) -> None:
    """Revoke a token the caller owns. Raises `LookupError` when the token is
    unknown *or* owned by someone else — the endpoint maps both to 404 so a
    caller can't probe other users' token ids. Commits (via `revoke_token`)."""
    row = conn.execute(
        "SELECT id, user_id FROM mcp_tokens WHERE id = ?", (token_id,)
    ).fetchone()
    if row is None or row["user_id"] != owner_id:
        raise LookupError("token not found")
    revoke_token(conn, token_id)


def mint_token_for_user(
    conn: sqlite3.Connection, *, user_id: str, name: str, scope: Scope
) -> tuple[str, sqlite3.Row]:
    """Admin path: mint a token for any user, capping `scope` at that user's
    role. Raises `LookupError` (→ 404) when the user is unknown. Returns
    `(raw_token, token_row)`. Commits (via `issue_token`)."""
    user = get_user(conn, user_id)
    if user is None:
        raise LookupError("user not found")
    capped = _clamp_scope(scope, user["role"])
    raw, token_id = issue_token(conn, user_id=user_id, name=name, scope=capped)
    row = get_token(conn, token_id)
    assert row is not None
    return raw, row


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All users, oldest first."""
    return conn.execute(
        "SELECT id, type, email, name, role, status, oidc_issuer, created_at, "
        "last_login_at FROM users ORDER BY created_at ASC"
    ).fetchall()


def get_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    """A single user row by id, or None."""
    return conn.execute(
        "SELECT id, type, email, name, role, status, oidc_issuer, created_at, "
        "last_login_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def update_user(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    role: Role | None = None,
    status: str | None = None,
    name: str | None = None,
) -> sqlite3.Row:
    """Apply an admin edit to a user and return the updated row. Only the
    supplied fields change. Enforced rules, in order:

    - unknown user → `LookupError` (endpoint maps to 404);
    - **last-admin guard**: demoting the sole remaining active admin off the
      admin role is refused with `ValueError("cannot demote the last admin")`
      (→ 400), so the surface can't lock itself out;
    - an out-of-range `status` → `ValueError("invalid status")` (→ 400).

    Commits once all requested updates are applied."""
    row = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise LookupError("user not found")
    # Guard against the only admin demoting themselves and locking the
    # surface — at least one active admin must remain.
    if role and role != "admin" and row["role"] == "admin":
        n_admins = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()["n"]
        if n_admins <= 1:
            raise ValueError("cannot demote the last admin")
    if role is not None:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if status is not None:
        if status not in ("active", "suspended"):
            raise ValueError("invalid status")
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    if name is not None:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    conn.commit()
    updated = get_user(conn, user_id)
    assert updated is not None
    return updated


def list_invites(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Pending (unaccepted) invites, newest first."""
    return conn.execute(
        "SELECT id, email, role, token, created_at, expires_at "
        "FROM invites WHERE accepted_at IS NULL ORDER BY created_at DESC"
    ).fetchall()


def create_invite(
    conn: sqlite3.Connection, *, email: str, role: Role, invited_by: str
) -> sqlite3.Row:
    """Create an invite binding a normalized email to a role and return its
    row. The email is stripped and lowercased; the opaque token is generated
    here. Commits."""
    invite_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO invites (id, email, role, token, invited_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (invite_id, email.strip().lower(), role, token, invited_by, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, email, role, token, created_at, expires_at FROM invites WHERE id = ?",
        (invite_id,),
    ).fetchone()
    assert row is not None
    return row


def revoke_invite(conn: sqlite3.Connection, invite_id: str) -> None:
    """Delete a pending invite. No-op when the invite is already accepted or
    absent (matches the endpoint's idempotent DELETE). Commits."""
    conn.execute(
        "DELETE FROM invites WHERE id = ? AND accepted_at IS NULL", (invite_id,)
    )
    conn.commit()
