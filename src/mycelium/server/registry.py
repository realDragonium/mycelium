"""The tool registry: the `@tool` decorator and the MCP server it feeds.

Decorating a function registers it once for every surface: `TOOLS` drives the
REST mirror in `mycelium.http` and the in-process loops, and the names in
`MCP_TOOLS` are also advertised over MCP. The wrapper is where every call is
gated — role check, draft redirect, model-loop admission — so the policy is the
same whichever transport the call arrived on.
"""

from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer

from .. import link_authoring
from .admission import _MODEL_LOOP_TOOLS, _offloaded, _run_tool
from .draft_queue import (
    _LIST_TOOL_KINDS,
    _MUTATION_PREFIXES,
    _list_from_draft,
    _queue_draft_op,
    _resolve_draft_target,
)

# `MYCELIUM_INSTRUCTIONS` lets each deployment tell Claude Desktop / other
# MCP clients *when* to reach for this server — naming the product, the
# trigger phrasing, the fallback when nothing relevant comes back. It's
# the strongest signal for "use this server for X" because it lands in
# the system prompt alongside the tool list.
_INSTRUCTIONS = (os.environ.get("MYCELIUM_INSTRUCTIONS") or "").strip() or None


# When Mycelium is fronted by a reverse proxy (nginx, Cloudflare),
# requests reach the MCP transport with the public Host header — not
# 127.0.0.1. Its DNS-rebinding protection rejects unrecognised hosts with
# 421 unless we tell it which to trust. MYCELIUM_ALLOWED_HOSTS is a
# comma-separated list of `host[:port]` patterns (e.g.
# `mycelium.example.com,mycelium.example.com:443`). When unset, the
# default localhost protection stays in place — fine for local dev.
#
# This is transport configuration, so it is passed to `streamable_http_app()`
# where the ASGI app is built (`mycelium.http`), not to `MCPServer` itself.
def _build_transport_security() -> Any:
    raw = (os.environ.get("MYCELIUM_ALLOWED_HOSTS") or "").strip()
    if not raw:
        return None
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    # Allow https origins for each host. Wildcard ports keep dev-tool
    # quirks from rejecting traffic.
    origins: list[str] = []
    for h in hosts:
        bare = h.split(":", 1)[0]
        origins.extend(
            [
                f"https://{bare}",
                f"https://{bare}:*",
                f"http://{bare}",
                f"http://{bare}:*",
            ]
        )
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
    from .. import auth as _auth

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

        from .. import auth as _auth

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

#: Functions registered as tools — read by `mycelium.http` to auto-generate
#: REST endpoints, and by the in-process loops and draft replay. `publish` puts
#: them in their declared order once every tool module has registered.
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


def tool(
    func: Callable[..., Any] | None = None,
    *,
    role: str | None = None,
    real_role: bool = False,
) -> Callable[..., Any]:
    """Register `func` as an HTTP endpoint, and as an MCP tool when its name
    is in `MCP_TOOLS`.

    Also enforces the per-tool role gate when invoked through the MCP
    transport. The REST mirror in `http.py` performs its own pre-call
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
    """
    from .. import auth as _auth  # local import: auth is loaded lazily so
    # server.py stays importable in environments that don't have the auth
    # tables yet (notably some test fixtures).

    def _register(func: Callable[..., Any]) -> Callable[..., Any]:
        required = role or _auth.required_role_for(func.__name__)
        # Tools whose name matches one of these prefixes are substrate
        # writes — they can be queued onto a draft instead of executing
        # against the live store. We extend their public signature with
        # an optional `draft_id` arg and intercept the call below.
        is_mutation = func.__name__.startswith(_MUTATION_PREFIXES)
        # List tools with a registered "show draft contents" mapping
        # also accept `draft_id`, but route to a read against the draft
        # ops table instead of redirecting a write.
        is_draftable_read = func.__name__ in _LIST_TOOL_KINDS
        has_draft_id = is_mutation or is_draftable_read
        # Claimed around the call itself, not around the whole wrapper: a
        # drafter whose call is redirected onto a draft never runs the model
        # loop, so it must not hold a slot the real work is waiting for.
        is_model_loop = func.__name__ in _MODEL_LOOP_TOOLS

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = _auth.current_principal.get()
            if principal is not None and not _satisfies(principal, required, real_role):
                raise _auth.RoleRequired(
                    f"tool '{func.__name__}' requires the "
                    f"{'real ' if real_role else ''}{required} role; "
                    f"caller has {principal.role}"
                )

            if has_draft_id:
                draft_id = kwargs.pop("draft_id", None)
            else:
                draft_id = None

            if func.__name__ == "add_links":
                bound = _ORIG_SIGNATURES[func.__name__].bind_partial(*args, **kwargs)
                link_authoring.reject_entity_statement_additions(
                    bound.arguments.get("links")
                )

            if is_mutation:
                redirect = _resolve_draft_target(principal, draft_id)
                if redirect is not None:
                    # Bind the remaining kwargs against func's original
                    # signature so positional args become named — keeps
                    # the stored payload uniform regardless of how the
                    # caller invoked the tool.
                    bound = _ORIG_SIGNATURES[func.__name__].bind_partial(
                        *args, **kwargs
                    )
                    payload = dict(bound.arguments)
                    return _queue_draft_op(redirect, func.__name__, payload, principal)

            if is_draftable_read and draft_id is not None:
                return _list_from_draft(draft_id, _LIST_TOOL_KINDS[func.__name__])

            return _run_tool(func, args, kwargs, budgeted=is_model_loop)

        # Expose the required role on the wrapper so other layers
        # (e.g. http.py's role-classifier loop and the tools/list
        # filter in this module) can read it without re-deriving.
        wrapper._mycelium_required_role = required  # type: ignore[attr-defined]
        wrapper._mycelium_real_role = real_role  # type: ignore[attr-defined]

        if has_draft_id:
            _add_draft_id_to_signature(func, wrapper)

        TOOLS.append(wrapper)
        return wrapper

    # Allow both `@tool` and `@tool(role="reader")` forms.
    if func is not None:
        return _register(func)
    return _register


#: Cached unmodified signatures of mutation tools, so the wrapper can
#: bind incoming kwargs against the function's *real* parameters when
#: building the draft op payload (after we've already popped draft_id).
_ORIG_SIGNATURES: dict[str, inspect.Signature] = {}


def _add_draft_id_to_signature(
    func: Callable[..., Any], wrapper: Callable[..., Any]
) -> None:
    """Splice an optional `draft_id: str | None = None` onto the wrapper's
    public signature. The MCP server's tool-schema introspection and http.py's
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
    # instead return a queue receipt `{draft_id, seq: int, queued}`,
    # and a list tool whose substrate result is `dict[str, Any]` may
    # instead return `list[dict[...]]` of queued ops. The MCP server validates
    # outputs against the schema, so use `Any` to subsume every branch.
    return_ann: Any = Any
    new_sig = sig.replace(parameters=params, return_annotation=return_ann)
    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
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
    # http.py builds its sync FastAPI handlers from TOOLS (FastAPI does its
    # own thread dispatch), so only the MCP side gets the offloading shim.
    for wrapper in TOOLS:
        if wrapper.__name__ in MCP_TOOLS:
            mcp.tool()(_offloaded(wrapper))
