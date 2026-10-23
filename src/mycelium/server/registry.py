"""The tool registry: the `@tool` decorator and the MCP server it feeds.

Decorating a function registers it once for every surface: `TOOLS` drives the
REST mirror in `mycelium.http.tool_routes` and the in-process loops, and the
names in `MCP_TOOLS` are also advertised over MCP. The wrapper is where every
call is gated — role check, draft redirect, model-loop admission — so the policy
is the same whichever transport the call arrived on.
"""

from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Callable, Sequence
from typing import Any, ParamSpec, TypeVar, overload

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .. import auth as _auth
from .. import hosts as _hosts
from .. import link_authoring
from .admission import _MODEL_LOOP_TOOLS, _offloaded, _run_tool
from .draft_queue import (
    _LIST_TOOL_KINDS,
    _MUTATION_PREFIXES,
    DraftReceipt,
    QueuedOp,
    _list_from_draft,
    _queue_draft_op,
    _resolve_draft_target,
)

P = ParamSpec("P")
R = TypeVar("R")

# `MYCELIUM_INSTRUCTIONS` lets each deployment tell Claude Desktop / other
# MCP clients *when* to reach for this server — naming the product, the
# trigger phrasing, the fallback when nothing relevant comes back. It's
# the strongest signal for "use this server for X" because it lands in
# the system prompt alongside the tool list.
_INSTRUCTIONS = (os.environ.get("MYCELIUM_INSTRUCTIONS") or "").strip() or None


# The MCP transport checks `Host` and `Origin` itself and answers 421 to a
# host it does not know. Left unconfigured it trusts only loopback, which is
# right for local development. Once hostnames are configured it is given the
# same list `HostAllowlistMiddleware` uses, so both checks agree.
#
# This is transport configuration, so it is passed to `streamable_http_app()`
# where the ASGI app is built (`mycelium.http`), not to `MCPServer` itself.
def _build_transport_security() -> TransportSecuritySettings | None:
    configured = _hosts.configured()
    if not configured:
        return None
    hosts: list[str] = []
    origins: list[str] = []
    for name in sorted(_hosts.LOOPBACK | configured):
        bare = f"[{name}]" if ":" in name else name
        hosts.extend([bare, f"{bare}:*"])
        for scheme in ("https", "http"):
            origins.extend([f"{scheme}://{bare}", f"{scheme}://{bare}:*"])
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


mcp = MCPServer(
    "mycelium",
    instructions=_INSTRUCTIONS,
)


def _satisfies(principal: Any, required: str, real_role: bool) -> bool:
    """Whether `principal` clears a tool's role gate.

    The single answer to "may this caller invoke this tool", asked by both
    the `@tool` wrapper before running one and the listing filter before
    advertising one. Two callers, one rule: a tool that appears in
    `tools/list` is one the gate will let through.
    """
    check = _auth.principal_has_real_role if real_role else _auth.principal_satisfies
    return check(principal, required)


class _RoleFilteredTools:
    """Hide tools the caller doesn't have permission to invoke.

    `tools/list` returns every registered tool to every caller. The `@tool`
    wrapper below still rejects the actual call with PermissionError when a
    reader tries to invoke a writer tool — but exposing those names to the
    LLM is noisy at best and misleading at worst (the model will reach for
    tools it can't use). This trims the listed surface to what the caller's
    role can actually call.

    Registered on the server's middleware chain: it sees every inbound
    message and narrows the result of the one it cares about. No change to
    the wire protocol — just a smaller `tools` array in the response.

    The dispatcher serializes a handler's return to its wire dict *before*
    the middleware chain runs, so what arrives here is that dict, not a
    `ListToolsResult`.

    Skipped when no principal is set (stdio / local-admin mode); the full
    list goes out, which is what local single-user installs want.

    The listed surface is per-role, which is why `cache_hints` must never
    mark `tools/list` `scope="public"`: a shared cache entry would hand one
    role's tool list to another. The SDK's default hint is `private`, so
    leaving `cache_hints` unset is the safe configuration.
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method != "tools/list" or not isinstance(result, dict):
            return result

        principal = _auth.current_principal.get()
        if principal is None:
            return result

        # Resolve each tool's gate through the wrapper registered in
        # `TOOLS`, so `@tool(role=..., real_role=...)` overrides are
        # honored. Fall back to prefix-derivation if a wrapper is missing
        # for some reason (shouldn't happen in practice).
        wrappers_by_name = {w.__name__: w for w in TOOLS}

        def _invocable(name: str) -> bool:
            w = wrappers_by_name.get(name)
            required = getattr(
                w, "_mycelium_required_role", None
            ) or _auth.required_role_for(name)
            return _satisfies(
                principal, required, getattr(w, "_mycelium_real_role", False)
            )

        kept = [t for t in result.get("tools", ()) if _invocable(t["name"])]
        return {**result, "tools": kept}


# Appended, so it runs inside the SDK's own built-in middleware.
mcp.middleware.append(_RoleFilteredTools())

#: Functions registered as tools — read by `mycelium.http.tool_routes` to
#: auto-generate REST endpoints, and by the in-process loops and draft replay.
#: `publish` puts them in their declared order once every tool module has
#: registered.
TOOLS: list[Callable[..., Any]] = []

#: The tools advertised over MCP. Everything else in `TOOLS` keeps its HTTP
#: route and its in-process callers; it is just not sent to MCP clients, which
#: pay for every schema before their first question. `docs/MCP_TOOLS.md` gives
#: the reason for each entry and for each tool left out.
MCP_TOOLS = frozenset(
    {
        # Read
        "search_statements",
        "get_statements",
        "find_statement_connections",
        "grep_statements",
        "list_statements",
        "discover_facts",
        "get_entity",
        "list_entities",
        "search_entities",
        "list_link_types",
        "list_statement_kinds",
        "list_entity_link_types",
        "ask",
        # Author
        "ingest",
        "upsert_entity",
        "upsert_name",
        "upsert_statement",
        "upsert_statements",
        "patch_statement",
        "add_links",
        "remove_links",
        "add_entity_links",
        "remove_entity_links",
        "merge_statements",
        "merge_entities",
        "delete_statement",
        # Drafts
        "submit_draft",
        "get_draft",
        "discard_draft_op",
        "list_my_drafts",
        "list_drafts",
        "set_draft_review_evidence",
        "report_knowledge_gap",
        # Documentation
        "request_documentation",
        "get_documentation_run",
        "get_generated_document",
        "revise_document",
    }
)


def _check_role(name: str, required: str, real_role: bool) -> _auth.Principal | None:
    """Raise unless the current caller clears the tool's role gate; return them."""
    principal = _auth.current_principal.get()
    if principal is not None and not _satisfies(principal, required, real_role):
        raise _auth.RoleRequired(
            f"tool '{name}' requires the "
            f"{'real ' if real_role else ''}{required} role; "
            f"caller has {principal.role}"
        )
    return principal


def _register(
    func: Callable[..., object],
    wrapper: Callable[..., object],
    *,
    required: str,
    real_role: bool,
    draftable: bool,
) -> None:
    """Record `wrapper` in `TOOLS`, with the gate its other surfaces read.

    `draftable` is what the decorator declared, and the name rule in
    `draft_queue` is what the wrapper acts on; refusing a mismatch keeps the
    declared result type honest.
    """
    name = func.__name__
    if name.startswith(_MUTATION_PREFIXES) or name in _LIST_TOOL_KINDS:
        if not draftable:
            raise TypeError(
                f"'{name}' can be routed onto a draft; register it with "
                "@draftable_tool or @draft_listing_tool"
            )
        _add_draft_id_to_signature(func, wrapper)
    elif draftable:
        raise TypeError(f"'{name}' cannot be routed onto a draft; use @tool")
    # Exposed on the wrapper so other layers (e.g. http/tool_routes.py's
    # role-classifier loop and the tools/list filter in this module) can read
    # it without re-deriving.
    wrapper.__dict__.update(
        _mycelium_required_role=required, _mycelium_real_role=real_role
    )
    TOOLS.append(wrapper)


def _pop_draft_id(kwargs: dict[str, object]) -> str | None:
    """Take the `draft_id` the published signature added out of a call's kwargs."""
    draft_id = kwargs.pop("draft_id", None)
    if draft_id is not None and not isinstance(draft_id, str):
        raise TypeError(f"draft_id must be a string, not {type(draft_id).__name__}")
    return draft_id


@overload
def tool(func: Callable[P, R], /) -> Callable[P, R]: ...


@overload
def tool(
    *, role: str | None = None, real_role: bool = False
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def tool(
    func: Callable[P, R] | None = None,
    *,
    role: str | None = None,
    real_role: bool = False,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Register `func` as an HTTP endpoint, and as an MCP tool when its name
    is in `MCP_TOOLS`.

    Also enforces the per-tool role gate when invoked through the MCP
    transport. The REST mirror in `http/tool_routes.py` performs its own pre-call
    check inside the FastAPI handler; we re-check here so the SAME
    policy applies to MCP-over-stdio and MCP-over-HTTP. The check
    short-circuits when no principal is in the contextvar (the stdio
    process is single-user-local — there's no remote caller to authorize)
    so existing local stdio usage stays unchanged.

    The required role is derived from the function name by default
    (read prefixes → reader, delete/merge → admin, otherwise writer).
    Pass `role=` to override for tools that don't fit the naming
    convention, e.g. `@tool(role="reader")` for a write-that-anyone-can-do
    like reporting a knowledge gap.

    `real_role=True` drops the drafter equivalence: a drafter normally
    clears writer and admin gates because the wrapper redirects their
    writes onto a draft, which is wrong for a tool that sits outside that
    machinery and lands live. Declaring it here rather than re-checking in
    the body is what keeps `tools/list` honest — the listing filter reads
    the same declaration, so a tool can't be advertised to a caller the
    gate will then reject.

    A tool a draft can stand in for is registered with `draftable_tool` or
    `draft_listing_tool` instead, whose results say so.
    """

    def _decorate(func: Callable[P, R]) -> Callable[P, R]:
        name = func.__name__
        required = role or _auth.required_role_for(name)
        budgeted = name in _MODEL_LOOP_TOOLS

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            _check_role(name, required, real_role)
            return _run_tool(lambda: func(*args, **kwargs), budgeted=budgeted)

        _register(
            func, wrapper, required=required, real_role=real_role, draftable=False
        )
        return wrapper

    # Allow both `@tool` and `@tool(role="reader")` forms.
    if func is not None:
        return _decorate(func)
    return _decorate


def draftable_tool(func: Callable[P, R]) -> Callable[P, R | DraftReceipt]:
    """Register a substrate write, which a draft can take in its place.

    A drafter's call, or any call naming a `draft_id`, is queued onto that
    draft and answers with its `DraftReceipt` rather than the tool's result.
    The published signature gains the optional `draft_id`.
    """
    name = func.__name__
    required = _auth.required_role_for(name)

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | DraftReceipt:
        principal = _check_role(name, required, False)
        draft_id = _pop_draft_id(kwargs)
        if name == "add_links":
            bound = _ORIG_SIGNATURES[name].bind_partial(*args, **kwargs)
            link_authoring.reject_entity_statement_additions(
                bound.arguments.get("links")
            )
        redirect = _resolve_draft_target(principal, draft_id)
        if redirect is not None:
            # Bind the remaining kwargs against func's original signature so
            # positional args become named — keeps the stored payload uniform
            # regardless of how the caller invoked the tool.
            bound = _ORIG_SIGNATURES[name].bind_partial(*args, **kwargs)
            return _queue_draft_op(redirect, name, dict(bound.arguments), principal)
        return _run_tool(lambda: func(*args, **kwargs), budgeted=False)

    _register(func, wrapper, required=required, real_role=False, draftable=True)
    return wrapper


def draft_listing_tool(func: Callable[P, R]) -> Callable[P, R | list[QueuedOp]]:
    """Register a list read that can show a draft's queued ops instead.

    Called with a `draft_id`, it answers with that draft's ops of the kinds
    `_LIST_TOOL_KINDS` maps it to rather than reading the substrate. The
    published signature gains the optional `draft_id`.
    """
    name = func.__name__
    required = _auth.required_role_for(name)

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | list[QueuedOp]:
        _check_role(name, required, False)
        draft_id = _pop_draft_id(kwargs)
        if draft_id is not None:
            return _list_from_draft(draft_id, _LIST_TOOL_KINDS[name])
        return _run_tool(lambda: func(*args, **kwargs), budgeted=False)

    _register(func, wrapper, required=required, real_role=False, draftable=True)
    return wrapper


#: Cached unmodified signatures of mutation tools, so the wrapper can
#: bind incoming kwargs against the function's *real* parameters when
#: building the draft op payload (after we've already popped draft_id).
_ORIG_SIGNATURES: dict[str, inspect.Signature] = {}


def _add_draft_id_to_signature(
    func: Callable[..., object], wrapper: Callable[..., object]
) -> None:
    """Splice an optional `draft_id: str | None = None` onto the wrapper's
    public signature. The MCP server's tool-schema introspection and tool_routes.py's
    body-model generation both read `inspect.signature(wrapper)`, so
    overriding `__signature__` + `__annotations__` is enough to make the
    new param appear in both surfaces.

    The module has `from __future__ import annotations`, so each
    parameter's `.annotation` arrives here as a string forward ref.
    Pydantic (used by the MCP server for arg-model generation) can no longer
    resolve those once we replace the signature object — `inspect`
    short-circuits and returns ours without walking back to `__wrapped__`
    for globals. So we resolve them eagerly here using the function's
    own globalns before building the new Parameter list.
    """
    sig = inspect.signature(func)
    _ORIG_SIGNATURES[func.__name__] = sig

    resolved = inspect.get_annotations(func, eval_str=True)
    params: list[inspect.Parameter] = []
    for name, p in sig.parameters.items():
        ann = resolved.get(name, p.annotation)
        params.append(p.replace(annotation=ann))
    params.append(
        inspect.Parameter(
            "draft_id",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=str | None,
        )
    )
    # The published return type is too narrow once draft_id is in play:
    # a mutation tool whose substrate result is `dict[str, str]` may
    # instead return a `DraftReceipt`, and a list tool whose substrate
    # result is `dict[str, Any]` may instead return `list[QueuedOp]`. The MCP server validates
    # outputs against the schema, so use `Any` to subsume every branch.
    return_ann: Any = Any
    new_sig = sig.replace(parameters=params, return_annotation=return_ann)
    wrapper.__dict__["__signature__"] = new_sig
    wrapper.__annotations__ = {**resolved, "draft_id": str | None, "return": return_ann}


def publish(order: Sequence[str]) -> None:
    """Put `TOOLS` in `order` and advertise the `MCP_TOOLS` among them over MCP.

    Called once, by `mycelium.server`, after every tool module has registered.
    Registration follows module import order, so the published order is
    declared rather than inherited from where a tool happens to be defined: it
    is the order MCP clients list, the REST routes and OpenAPI document follow,
    and the in-process loops offer their model.
    """
    position = {name: index for index, name in enumerate(order)}
    unlisted = sorted(w.__name__ for w in TOOLS if w.__name__ not in position)
    if unlisted:
        raise RuntimeError(f"tools missing from the published order: {unlisted}")
    TOOLS.sort(key=lambda wrapper: position[wrapper.__name__])
    # http/tool_routes.py builds its sync FastAPI handlers from TOOLS (FastAPI does its
    # own thread dispatch), so only the MCP side gets the offloading shim.
    for wrapper in TOOLS:
        if wrapper.__name__ in MCP_TOOLS:
            mcp.tool()(_offloaded(wrapper))
