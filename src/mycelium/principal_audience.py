"""The audience boundary around an audience-scoped principal's reads.

A user or token scoped to an audience (`auth.Principal.audience_id`) reads
the knowledge base exactly as a documentation run for that audience does:
through `audience_scope`, whose views shadow the substrate on the calling
thread's connection. Its role is clamped to reader when it is resolved, so it
never writes.

What it may reach is an allowlist, and everything else is refused:

* the tools in `TOOLS`, each run inside the boundary by the `@tool` wrapper;
* the HTTP routes in `ROUTES`, each applying the boundary itself;
* the web app shell, sign-in and the MCP transport, whose tool calls go
  through the same `@tool` wrapper.

A route or tool added later is closed to scoped principals until someone
adds it here, and `tests/test_principal_audience.py` pins both lists.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from . import audience_scope, audiences, auth, document_freshness, store

#: Tools a scoped principal may call. Ask's own read primitives, which a
#: documentation run already reads through the same boundary, plus Ask
#: itself and the documents written for the audience.
TOOLS = frozenset(
    {
        "ask",
        "search_statements",
        "find_statement_connections",
        "get_statements",
        "retrieve_context",
        "get_entity",
        "list_entities",
        "search_entities",
        "list_statements",
        "grep_statements",
        "discover_facts",
        "find_duplicates",
        "find_entity_duplicates",
        "get_mention_candidates",
        "list_link_types",
        "list_statement_kinds",
        "list_entity_link_types",
        "list_link_type_aliases",
        "list_generated_documents",
        "get_generated_document",
        "list_media",
    }
)

#: Tools in `TOOLS` that apply the boundary themselves rather than inside the
#: `@tool` wrapper: Ask scopes each read of its loop, and the document tools
#: filter the drafts store against a snapshot taken outside the views.
SELF_SCOPED = frozenset({"ask", "list_generated_documents", "get_generated_document"})

#: Non-tool HTTP routes a scoped principal may call, as (method, path).
ROUTES = frozenset(
    {
        ("GET", "/api/me"),
        ("GET", "/api/me/tokens"),
        ("POST", "/api/me/tokens"),
        ("DELETE", "/api/me/tokens/{token_id}"),
        ("GET", "/api/data"),
        ("GET", "/api/substrate-counts"),
        ("GET", "/api/entity-positions"),
        ("GET", "/api/history"),
        ("GET", "/api/documentation/documents"),
        ("GET", "/api/documentation/documents/{document_id}"),
        ("GET", "/api/media/{media_id}/content"),
    }
)

#: Paths outside the API that carry no knowledge of their own: the web app
#: shell and its assets, sign-in, and the MCP transport.
_SHELL_PREFIXES = ("/ui/", "/cockpit/", "/auth/", "/mcp/")
_SHELL_PATHS = frozenset({"/", "/ui", "/cockpit", "/connect", "/mcp"})


def _pattern(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(path)) + "$")


def _tool_path(name: str) -> str:
    return "/" + name.replace("_", "-")


_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, _pattern(path)) for method, path in sorted(ROUTES)
)
_TOOL_PATHS = frozenset(_tool_path(name) for name in TOOLS)


def may_reach(method: str, path: str, *, exempt: bool) -> bool:
    """Whether a scoped principal may send this request at all. `exempt` is
    whether the path is open without signing in; such paths hold nothing a
    signed-in scoped principal could not already see."""
    if exempt or path in _SHELL_PATHS or path.startswith(_SHELL_PREFIXES):
        return True
    if path in _TOOL_PATHS:
        return True
    if method == "HEAD":
        method = "GET"
    return any(
        method == allowed and pattern.match(path) for allowed, pattern in _ALLOWED
    )


class Unavailable(auth.RoleRequired):
    """Refused because the caller is scoped to an audience."""


def audience_of(principal: auth.Principal | None) -> audiences.Audience | None:
    """The live audience a principal is scoped to, or None for full access
    by role. A retired or unknown audience refuses rather than widening, as
    a documentation profile's does."""
    if principal is None or principal.audience_id is None:
        return None
    audience = next(
        (item for item in audiences.live() if item.id == principal.audience_id),
        None,
    )
    if audience is None:
        raise Unavailable(
            f"this credential is scoped to the audience {principal.audience_id!r}, "
            "which is no longer live; ask an administrator to rescope it"
        )
    return audience


def require_live(audience_id: str | None) -> None:
    """Refuse to scope a principal to an audience that is not live."""
    if audience_id is not None and audience_id not in {
        item.id for item in audiences.live()
    }:
        raise ValueError(f"unknown or retired audience: {audience_id!r}")


def check_tool(principal: auth.Principal | None, name: str) -> None:
    if principal is not None and principal.audience_id is not None:
        if name not in TOOLS:
            raise Unavailable(
                f"tool '{name}' is not available to a credential scoped to an audience"
            )


@contextmanager
def reads(principal: auth.Principal | None) -> Iterator[None]:
    """Run the block inside the principal's audience boundary on this
    thread's substrate connection. A no-op for an unscoped principal, and
    inside a boundary already applied (a tool another tool calls)."""
    audience = audience_of(principal)
    if audience is None or audience_scope.active() is not None:
        yield
        return
    conn = store.substrate_connection()
    with audience_scope.applied(conn, audience_scope.capture(conn, audience)):
        yield


def current_scope() -> audience_scope.Scope | None:
    """A snapshot of what the current principal may see, for reads that span
    more than one call (Ask) or filter another store against it
    (documents). None for full access by role."""
    audience = audience_of(auth.current_principal.get())
    if audience is None:
        return None
    # Captured inside a boundary, the snapshot would only see the views.
    return audience_scope.active() or audience_scope.capture(
        store.substrate_connection(), audience
    )


def readable_documents(
    drafts: sqlite3.Connection,
    document_ids: Sequence[str],
    scope: audience_scope.Scope,
) -> frozenset[str]:
    """The documents whose current revision the scoped audience may read.

    A document qualifies when it was written for this audience, or for one
    at least as restricted: an external reader never gets a document written
    for an internal audience, and every statement the writing audience may
    see now is one this audience may see too. Every statement it cites must
    also still be visible, so a document resting on a statement relabelled
    away does not keep showing it. A document whose run recorded no
    audience or no citations fails closed.
    """
    conn = store.substrate_connection()
    visible: dict[tuple[str, bool], frozenset[str]] = {}
    readable: set[str] = set()
    for document_id, cited in document_freshness.cited_snapshots(
        drafts, document_ids
    ).items():
        if cited.audience is None or cited.statements is None:
            continue
        if not cited.statements.keys() <= scope.statement_ids:
            continue
        audience_id, internal = cited.audience
        if audience_id != scope.audience.id:
            if internal and not scope.audience.internal:
                continue
            if cited.audience not in visible:
                visible[cited.audience] = store.visible_statement_ids(
                    conn, audiences.sees_of(audience_id), internal
                )
            if not visible[cited.audience] <= scope.statement_ids:
                continue
        readable.add(document_id)
    return frozenset(readable)
