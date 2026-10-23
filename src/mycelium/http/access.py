"""Who may call an HTTP endpoint: the guards every route module shares.

`AuthMiddleware` has already resolved the caller onto
`request.state.principal`; these only read it. Role classification itself
lives in `auth` and `server.registry`, so the REST mirror and the MCP `@tool`
wrapper cannot disagree about who may call a tool.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .. import auth
from ..server import registry


def _enforce_role(request: Request, required: str, real_role: bool = False) -> None:
    p: auth.Principal | None = getattr(request.state, "principal", None)
    if p is None:
        raise HTTPException(status_code=401, detail="authentication required")
    # `registry._satisfies` is the one rule the MCP wrapper and the tools/list
    # filter also ask, so a tool cannot be reachable over one transport and
    # gated on another.
    if not registry._satisfies(p, required, real_role):
        raise HTTPException(
            status_code=403,
            detail=(
                f"this operation requires "
                f"{'a real' if real_role else 'the'} {required} role"
            ),
        )


def _require_principal(request: Request) -> auth.Principal:
    p: auth.Principal | None = getattr(request.state, "principal", None)
    if p is None:
        # Should be unreachable: middleware either sets a principal or
        # returns 401 itself. Defensive in case of future middleware
        # reordering.
        raise HTTPException(status_code=401, detail="authentication required")
    return p


def _require_admin(request: Request) -> auth.Principal:
    p = _require_principal(request)
    if not p.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    return p


def _enforce_curator(
    request: Request, action: str = "approving or rejecting a draft"
) -> auth.Principal:
    """Approve/reject require a *real* writer or admin — `_enforce_role`
    routes drafters through too (because the @tool wrapper's drafter
    equivalence makes them satisfy writer), which would let a drafter
    approve their own draft and re-queue every op into a brand new
    auto-draft at replay time. Use the strict rank check instead.
    """
    p = _require_principal(request)
    if not auth.principal_has_real_role(p, "writer"):
        raise HTTPException(
            status_code=403,
            detail=f"{action} requires the writer or admin role",
        )
    return p
