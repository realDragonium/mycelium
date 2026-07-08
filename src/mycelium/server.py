"""MCP server exposing the Mycelium substrate over stdio.

Tools are registered with the local `@tool` decorator (not the bare
`mcp.tool()`) so they show up in both the MCP transport AND the HTTP
transport in `mycelium/http.py` — adding a new tool here gives you both
interfaces for free.
"""

from __future__ import annotations

import cProfile
import datetime as _dt
import functools
import inspect
import json as _json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Literal, NotRequired, TypedDict

from mcp.server.fastmcp import FastMCP

from . import (
    embed,
    layout_baker,
    link_rules,
    phrasing,
    plurals,
    store,
    survey,
    tracing,
    vector,
    when_expression,
)
from .tracing import trace_span

logger = logging.getLogger(__name__)

# --- Profiling ---------------------------------------------------------------
# Toggled with `MYCELIUM_PROFILE=1` (off by default). When on, every tool
# call is wrapped in a cProfile run; we log wall-clock duration to stderr
# and write a per-call `.prof` file to MYCELIUM_PROFILE_DIR (default
# `./.mycelium/profiles`).
#
# Convert any `.prof` file to a flame graph from your shell — pstats is
# the standard input format for these tools:
#   uvx flameprof <file.prof> > out.svg          # SVG flame graph
#   uvx snakeviz <file.prof>                     # interactive in browser
#   uvx --from speedscope-py speedscope <file>   # speedscope JSON
#
# Profiling adds noticeable overhead (cProfile traces every Python call),
# so leave it off in normal operation and flip it on when investigating
# a specific slow tool.

_PROFILE_LOG = logging.getLogger("mycelium.profile")
if not _PROFILE_LOG.handlers:
    _PROFILE_LOG.addHandler(logging.StreamHandler(sys.stderr))
    _PROFILE_LOG.setLevel(logging.INFO)


def _profile_enabled() -> bool:
    """Re-read each call so toggling mid-run via os.environ works in tests."""
    val = (os.environ.get("MYCELIUM_PROFILE") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _profile_dir() -> Path:
    return Path(
        os.environ.get("MYCELIUM_PROFILE_DIR") or "./.mycelium/profiles"
    ).expanduser()


def _profile_filename(tool_name: str) -> Path:
    # ISO-ish timestamp + microseconds + tool name keeps filenames sortable
    # and unique even under bursty concurrent calls.
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    return _profile_dir() / f"{stamp}_{tool_name}.prof"


def _run_with_profile(func: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    profiler = cProfile.Profile()
    started = time.perf_counter()
    try:
        return profiler.runcall(func, *args, **kwargs)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        out_dir = _profile_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = _profile_filename(func.__name__)
        try:
            profiler.dump_stats(str(path))
            _PROFILE_LOG.info(
                "tool=%s duration_ms=%.2f profile=%s",
                func.__name__,
                elapsed_ms,
                path,
            )
        except OSError as ex:
            # Don't let a profile-dump failure mask the tool's own result.
            _PROFILE_LOG.warning(
                "tool=%s duration_ms=%.2f profile_write_failed=%s",
                func.__name__,
                elapsed_ms,
                ex,
            )


# `MYCELIUM_INSTRUCTIONS` lets each deployment tell Claude Desktop / other
# MCP clients *when* to reach for this server — naming the product, the
# trigger phrasing, the fallback when nothing relevant comes back. It's
# the strongest signal for "use this server for X" because it lands in
# the system prompt alongside the tool list.
_INSTRUCTIONS = (os.environ.get("MYCELIUM_INSTRUCTIONS") or "").strip() or None


# When Mycelium is fronted by a reverse proxy (nginx, Cloudflare),
# requests reach FastMCP with the public Host header — not 127.0.0.1.
# FastMCP's DNS-rebinding protection rejects unrecognised hosts with
# 421 unless we tell it which to trust. MYCELIUM_ALLOWED_HOSTS is a
# comma-separated list of `host[:port]` patterns (e.g.
# `mycelium.example.com,mycelium.example.com:443`). When unset, the
# default localhost protection stays in place — fine for local dev.
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


mcp = FastMCP(
    "mycelium",
    instructions=_INSTRUCTIONS,
    transport_security=_build_transport_security(),
)


def _install_role_based_tool_filter() -> None:
    """Hide tools the caller doesn't have permission to invoke.

    By default FastMCP's `tools/list` returns every registered tool to
    every caller. The `@tool` wrapper below still rejects the actual
    call with PermissionError when a reader tries to invoke a writer
    tool — but exposing those names to the LLM is noisy at best and
    misleading at worst (the model will reach for tools it can't use).
    This filter trims the listed surface to what the caller's role
    can actually call.

    Hooks the existing ListToolsRequest handler that FastMCP registers
    under the hood, awaits it, then strips the tools that fail the
    role gate. No change to the wire protocol — just a smaller `tools`
    array in the response.

    Skipped when no principal is set (stdio / local-admin mode); the
    handler returns the full list. That preserves the unchanged-from-
    before behaviour for local single-user installs.
    """
    import mcp.types as mcp_types

    underlying = mcp._mcp_server.request_handlers.get(mcp_types.ListToolsRequest)
    if underlying is None:  # pragma: no cover — FastMCP always registers it
        return

    async def filtered(req: mcp_types.ListToolsRequest):
        from . import auth as _auth

        result = await underlying(req)
        principal = _auth.current_principal.get()
        if principal is None:
            return result

        # FastMCP wraps the result in a `ServerResult` whose `.root`
        # is the `ListToolsResult`. Mutate in place so caching layers
        # downstream (FastMCP's own _tool_cache) stay consistent with
        # what we returned.
        # Resolve each tool's required role through the wrapper
        # registered in `TOOLS`, so `@tool(role="reader")` overrides
        # are honored. Fall back to prefix-derivation if a wrapper
        # is missing for some reason (shouldn't happen in practice).
        wrappers_by_name = {w.__name__: w for w in TOOLS}

        def _role_for(name: str) -> str:
            w = wrappers_by_name.get(name)
            return getattr(
                w, "_mycelium_required_role", None
            ) or _auth.required_role_for(name)

        tools = result.root.tools
        kept = [
            t for t in tools if _auth.principal_satisfies(principal, _role_for(t.name))
        ]
        result.root.tools = kept
        return result

    mcp._mcp_server.request_handlers[mcp_types.ListToolsRequest] = filtered


_install_role_based_tool_filter()

#: Functions registered as tools — read by `mycelium.http` to auto-generate
#: REST endpoints. Order is preserved.
TOOLS: list[Callable[..., Any]] = []


def tool(
    func: Callable[..., Any] | None = None,
    *,
    role: str | None = None,
) -> Callable[..., Any]:
    """Register `func` as both an MCP tool and an HTTP endpoint.

    The wrapper consults MYCELIUM_PROFILE on every call so the env var
    can be flipped at runtime — useful for tests and for switching
    profiling on without restarting the server.

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
    """
    from . import auth as _auth  # local import: auth is loaded lazily so
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

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = _auth.current_principal.get()
            if principal is not None and not _auth.principal_satisfies(
                principal, required
            ):
                raise PermissionError(
                    f"tool '{func.__name__}' requires the {required} role; "
                    f"caller has {principal.role}"
                )

            if has_draft_id:
                draft_id = kwargs.pop("draft_id", None)
            else:
                draft_id = None

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

            if _profile_enabled():
                return _run_with_profile(func, args, kwargs)
            return func(*args, **kwargs)

        # Expose the required role on the wrapper so other layers
        # (e.g. http.py's role-classifier loop and the tools/list
        # filter in this module) can read it without re-deriving.
        wrapper._mycelium_required_role = required  # type: ignore[attr-defined]

        if has_draft_id:
            _add_draft_id_to_signature(func, wrapper)

        TOOLS.append(wrapper)
        mcp.tool()(wrapper)
        return wrapper

    # Allow both `@tool` and `@tool(role="reader")` forms.
    if func is not None:
        return _register(func)
    return _register


# Prefixes that mark a tool as a substrate mutation. Tools whose name
# starts with one of these become "draftable": they accept an optional
# `draft_id` kwarg, and a drafter principal automatically routes them
# to a session-scoped draft instead of touching the substrate.
_MUTATION_PREFIXES = (
    "upsert_",
    "add_",
    "delete_",
    "remove_",
    "replace_",
    "patch_",
    "rename_",
    "move_",
    "merge_",
)


# List tools that have a natural "what's queued in this draft" view: when
# they're called with an explicit `draft_id`, the wrapper returns the
# draft's ops of matching kinds instead of hitting the substrate. The
# return shape is `list[dict]` either way; with draft_id, each dict is
# the op payload plus `_seq` and `_kind` markers so callers can tell
# which queued op produced it.
#
# Get / search / discover tools aren't here on purpose — most have a
# single-item return shape, and matching by name/id against arbitrary
# op payloads gets fragile fast. Use `get_draft(draft_id)` if you need
# the full op list for one draft.
_LIST_TOOL_KINDS: dict[str, tuple[str, ...]] = {
    "list_statements": ("upsert_statement",),
    "list_entities": ("upsert_entity",),
    "list_link_types": ("upsert_link_type",),
    "list_entity_link_types": ("upsert_entity_link_type",),
    "list_statement_kinds": ("upsert_statement_kind",),
    "list_annotations": ("upsert_annotation",),
}

#: Cached unmodified signatures of mutation tools, so the wrapper can
#: bind incoming kwargs against the function's *real* parameters when
#: building the draft op payload (after we've already popped draft_id).
_ORIG_SIGNATURES: dict[str, inspect.Signature] = {}


def _add_draft_id_to_signature(
    func: Callable[..., Any], wrapper: Callable[..., Any]
) -> None:
    """Splice an optional `draft_id: str | None = None` onto the wrapper's
    public signature. FastMCP's tool-schema introspection and http.py's
    body-model generation both read `inspect.signature(wrapper)`, so
    overriding `__signature__` + `__annotations__` is enough to make the
    new param appear in both surfaces.

    The module has `from __future__ import annotations`, so each
    parameter's `.annotation` arrives here as a string forward ref.
    Pydantic (used by FastMCP for arg-model generation) can no longer
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
    # instead return `list[dict[...]]` of queued ops. FastMCP validates
    # outputs against the schema, so use `Any` to subsume every branch.
    return_ann: Any = Any
    new_sig = sig.replace(parameters=params, return_annotation=return_ann)
    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    wrapper.__annotations__ = {**resolved, "draft_id": str | None, "return": return_ann}


def _resolve_draft_target(principal, draft_id: str | None) -> str | None:
    """Decide whether this tool call should be redirected to a draft.

    Returns the target draft_id, or None to mean 'execute against the
    substrate normally'. Three cases:

      1. Explicit `draft_id` from the caller — must reference an open
         draft. Raises if missing/non-open.
      2. Drafter principal, no explicit draft_id — find or create the
         session-scoped open draft. Requires a session id.
      3. Anything else — return None.
    """
    from . import auth as _auth, drafts_store

    if draft_id is not None:
        assert _drafts_conn is not None
        row = drafts_store.get_draft(_drafts_conn, draft_id)
        if row is None:
            raise ValueError(f"draft_id '{draft_id}' not found")
        if drafts_store.status_for(row) != "open":
            raise ValueError(
                f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
                f"only open drafts accept new ops"
            )
        return draft_id

    if principal is not None and principal.role == "drafter":
        assert _drafts_conn is not None
        # Prefer the MCP session id when the client propagates it
        # (one auto-draft per active conversation). Many clients don't
        # echo `Mcp-Session-Id` back on tool calls, and reverse proxies
        # sometimes strip non-standard headers — so fall back to a
        # principal-scoped key. Net effect of the fallback: a drafter
        # has at most one open auto-draft at a time across all their
        # clients; they must submit it before another auto-draft opens.
        # Explicit `draft_id` always wins over auto-targeting.
        session_id = _auth.current_session_id.get() or f"actor:{principal.id}"
        row = drafts_store.find_open_session_draft(_drafts_conn, session_id)
        if row is not None:
            return row["id"]
        return drafts_store.create_draft(
            _drafts_conn,
            created_by=principal.id,
            session_id=session_id,
        )

    return None


def _list_from_draft(draft_id: str, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return queued ops in a draft whose kind is in `kinds`, each shaped
    as the op payload plus `_seq`/`_kind` markers so the caller can map
    items back to specific ops. Raises if the draft id doesn't resolve."""
    from . import drafts_store

    assert _drafts_conn is not None
    row = drafts_store.get_draft(_drafts_conn, draft_id)
    if row is None:
        raise ValueError(f"draft_id '{draft_id}' not found")
    ops = drafts_store.list_ops(_drafts_conn, draft_id)
    out: list[dict[str, Any]] = []
    for op in ops:
        if op["kind"] not in kinds:
            continue
        item = {"_seq": op["seq"], "_kind": op["kind"]}
        item.update(_json.loads(op["payload_json"]))
        out.append(item)
    return out


def _queue_draft_op(
    draft_id: str, kind: str, payload: dict, principal
) -> dict[str, Any]:
    """Append a queued op to the draft and return a JSON-friendly
    receipt. Used as the return value of the redirected tool call so the
    agent sees what happened instead of a normal substrate response."""
    from . import drafts_store

    assert _drafts_conn is not None
    actor = principal.id if principal is not None else None
    # Drop None defaults so the stored payload only carries the args the
    # caller actually supplied — replay re-applies defaults at apply time.
    clean = {k: v for k, v in payload.items() if v is not None}
    seq = drafts_store.add_op(
        _drafts_conn,
        draft_id=draft_id,
        kind=kind,
        payload=clean,
        created_by=actor,
    )
    return {"draft_id": draft_id, "seq": seq, "queued": kind}


class LinkSpec(TypedDict):
    """An outgoing typed edge from this statement to an existing target.

    Used inside `upsert_statement` for the `links` parameter, where "this
    statement" is implicit (the one being created or updated).

    `when` is an optional condition expression — a tree of AND/OR/NOT
    over statement_id leaves:

        {"statement_id": "stm_X"}                            # leaf
        {"op": "and", "of": [<expr>, <expr>, ...]}          # AND (>=1 child)
        {"op": "or",  "of": [<expr>, <expr>, ...]}          # OR  (>=1 child)
        {"op": "not", "of": [<expr>]}                       # NOT (exactly 1 child)

    Reads "this — link_type → target when <expression>". Two edges with
    the same `(from, to, link_type)` but different `when` are distinct
    conditional pathways. The substrate canonicalizes every when-tree
    on write (sorts AND/OR children, dedupes, flattens same-op nesting,
    collapses single-child AND/OR, folds NOT(NOT(X)) → X) and identifies
    links by `(from, to, link_type, hash(canonical_when))` — so `(A AND
    B)` and `(B AND A)` are the same link, but `(A AND B)` and `(A OR
    B)` are distinct. NOT lets you express "this edge fires when
    condition C is absent" — e.g. `{"op": "and", "of": [{"statement_id":
    "stm_X"}, {"op": "not", "of": [{"statement_id": "stm_Y"}]}]}`.
    """

    to_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class IncomingLinkSpec(TypedDict):
    """An incoming typed edge from an existing source to this statement.

    Used inside `upsert_statement` for the `incoming_links` parameter so a
    new child statement can be wired in under existing parents in a single
    call. The `to` side of the edge is implicit (the statement being
    created or updated).

    `when` is an optional condition expression; see `LinkSpec`.
    """

    from_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class EdgeSpec(TypedDict):
    """A typed edge with both endpoints addressed.

    Used by `add_links` and `remove_links`. Endpoints may be statements
    (`stm_…`) or entities (`ent_…`) in any combination — the substrate
    routes statement↔statement edges to `statement_links` and any edge
    touching an entity to `entity_statement_links` (which also accepts a
    `when` condition with the same grammar). Externally, callers see a
    single uniform link API; the distinction is internal storage only.

    Entity↔entity edges are **not** handled here — those live in their
    own vocabulary and are managed by `add_entity_links` /
    `remove_entity_links`.

    `when` is an optional condition expression; see `LinkSpec`. Identity
    on read/delete is by canonicalized hash, so the literal shape sent
    to `remove_links` doesn't have to match what was originally sent to
    `add_links` — only the canonical form must match.

    Direction note: source is the bigger/earlier/wrapping/primary side;
    target is the smaller/later/contained/dependent side. Before
    committing an edge, read it aloud as "FROM <link_type> TO" and check
    it against the link type's description. For constrained statement
    link types, provably flipped edges detected by statement kind are
    rejected; e.g. `teaches` is `procedure -> capability`, so
    `capability -> procedure` fails and should be swapped.
    """

    from_id: str
    to_id: str
    link_type: str
    when: NotRequired[dict[str, Any]]


class BatchStatementSpec(TypedDict):
    """One statement in a batch upsert.

    Same shape as the parameters of single-record `upsert_statement`, with
    one extension: any `to_id` (in `links`) or `from_id`
    (in `incoming_links`) can be either an existing statement id like
    `"stm_abc..."` or the literal string `"@N"` (where N is a 0-based
    integer) to refer to the Nth statement in the same batch. This lets
    callers wire siblings together in one call without round-tripping for
    ids first.
    """

    kind: str
    text: str
    links: NotRequired[list[LinkSpec]]
    incoming_links: NotRequired[list[IncomingLinkSpec]]
    allow_phrasing_violations: NotRequired[bool]


_conn: sqlite3.Connection | None = None
_auth_conn: sqlite3.Connection | None = None
_drafts_conn: sqlite3.Connection | None = None
_index: vector.Index | None = None
_index_path: Path | None = None
_ann_index: vector.Index | None = None
_ann_index_path: Path | None = None
_name_index: vector.Index | None = None
_name_index_path: Path | None = None
#: Data dir the substrate was opened from — used to site per-feature artifacts
#: (e.g. the `ask` eval-harness trace log) alongside the substrate files.
_data_dir: Path | None = None


def init(data_dir: Path) -> None:
    """Open the substrate + auth DBs and load (or create) the three
    vector indexes (statements, annotations, entity names).

    Auth lives in its own SQLite file (`mycelium-auth.db`) so the
    substrate file can be replaced without disturbing identity or
    tokens — drop `mycelium.db` and restart, every existing user
    session and bearer token keeps working.
    """
    global _conn, _auth_conn, _drafts_conn, _index, _index_path
    global _ann_index, _ann_index_path, _name_index, _name_index_path, _data_dir

    from . import auth_store, drafts_store, research_store

    _data_dir = data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    _conn = store.connect(
        data_dir / "mycelium.db",
        history_path=data_dir / "mycelium-history.db",
    )
    layout_baker.configure(data_dir / "mycelium.db")
    store.migrate(_conn)
    layout_baker.ensure_initial()

    _auth_conn = auth_store.connect(data_dir / "mycelium-auth.db")
    auth_store.migrate(_auth_conn)

    _drafts_conn = drafts_store.connect(data_dir / "mycelium-drafts.db")
    drafts_store.migrate(_drafts_conn)
    research_store.migrate(_drafts_conn)
    orphaned = research_store.mark_orphaned(_drafts_conn)
    if orphaned:
        logger.warning(
            "marked %d research run(s) failed: orphaned by restart", orphaned
        )

    _index_path = data_dir / "mycelium.vec"
    _index = vector.Index()
    if _index_path.exists():
        _index.load(_index_path)
    else:
        _index.init_empty()

    _ann_index_path = data_dir / "mycelium-annotations.vec"
    _ann_index = vector.Index()
    if _ann_index_path.exists():
        _ann_index.load(_ann_index_path)
    else:
        _ann_index.init_empty()

    _name_index_path = data_dir / "mycelium-names.vec"
    _name_index = vector.Index()
    if _name_index_path.exists():
        _name_index.load(_name_index_path)
    else:
        _name_index.init_empty()
        # Backfill: if the DB has names but no on-disk name index
        # (first run after this feature lands, or a fresh restore),
        # embed every existing name so the index isn't silently empty.
        _backfill_name_index()
        _persist_name_index()

    # Start the async mention-recompute worker on its own thread+connection
    # (transport-agnostic: both stdio and HTTP funnel through init). Guarded
    # by an env flag so the test suite — which would otherwise spawn a thread
    # per TestClient lifecycle and race the assertions — can drain the queue
    # synchronously via `mention_worker.drain` instead.
    if os.environ.get("MYCELIUM_DISABLE_MENTION_WORKER") != "1":
        from . import mention_worker

        mention_worker.start(data_dir)


def _backfill_name_index() -> None:
    assert _conn is not None and _name_index is not None
    for row in store.list_all_names(_conn):
        if store.get_name_vector_id(_conn, row["id"]) is not None:
            continue
        vid = store.next_name_vector_id(_conn)
        vec = embed.embed(row["text"])
        _name_index.add(vid, vec)
        store.set_name_vector_id(_conn, row["id"], vid)


def _persist_index() -> None:
    assert _index is not None and _index_path is not None
    _index.save(_index_path)


def _persist_ann_index() -> None:
    assert _ann_index is not None and _ann_index_path is not None
    _ann_index.save(_ann_index_path)


def _persist_name_index() -> None:
    assert _name_index is not None and _name_index_path is not None
    _name_index.save(_name_index_path)


def _index_name(name_id: str, text: str) -> None:
    """Embed `text` and register the vector under `name_id`. Used on
    name creation."""
    assert _conn is not None and _name_index is not None
    vid = store.next_name_vector_id(_conn)
    vec = embed.embed(text)
    _name_index.add(vid, vec)
    store.set_name_vector_id(_conn, name_id, vid)
    _persist_name_index()


def _reindex_name(name_id: str, new_text: str) -> None:
    """Replace the vector for an existing indexed name (rename)."""
    assert _conn is not None and _name_index is not None
    vid = store.get_name_vector_id(_conn, name_id)
    vec = embed.embed(new_text)
    if vid is None:
        # Name exists in SQL but never got an index entry (e.g. created
        # before this feature existed and backfill missed it). Add fresh.
        vid = store.next_name_vector_id(_conn)
        _name_index.add(vid, vec)
        store.set_name_vector_id(_conn, name_id, vid)
    else:
        _name_index.replace(vid, vec)
    _persist_name_index()


def _drop_name_from_index(name_id: str) -> None:
    """Remove a name's vector. Idempotent."""
    assert _conn is not None and _name_index is not None
    vid = store.get_name_vector_id(_conn, name_id)
    if vid is not None:
        _name_index.delete(vid)
        store.delete_name_vector_mapping(_conn, name_id)
        _persist_name_index()


def _resolve_or_create_names(name_texts: list[str], strict: bool = False) -> list[str]:
    """Resolve name texts to name_ids, auto-creating a fresh entity + name
    for unknown text (or raising when `strict`).

    Used ONLY by `upsert_annotation`: annotation→entity mentions remain
    author-asserted (out of scope for derived statement mentions), so they
    keep the original resolve-or-create behavior. Statement mentions are
    derived from text and never flow through here."""
    assert _conn is not None
    name_ids: list[str] = []
    for text in name_texts:
        existing = store.get_name_by_text(_conn, text)
        if existing is not None:
            name_ids.append(existing["id"])
            continue
        if strict:
            raise ValueError(
                f"name {text!r} does not exist; pass strict_mentions=False "
                "to auto-create or upsert_entity / upsert_name first"
            )
        new_entity_id = store.create_entity(_conn, None)
        new_name_id = _create_name_with_plural(text, new_entity_id)
        name_ids.append(new_name_id)
        layout_baker.schedule_rebake()
    return name_ids


def _derive_statement_mentions(statement_id: str, text: str) -> None:
    """Synchronously derive and store one statement's mentions from its
    text (auto-links + suspect review rows). Called on the hot path
    whenever a statement's text is created or changed, so its mentions are
    always consistent with its text the moment the write returns."""
    assert _conn is not None
    store.derive_mentions(_conn, statement_id, text, store.build_name_index(_conn))


def _create_name_with_plural(text: str, entity_id: str) -> str:
    """Create a name, vector-index it, enqueue a recompute scan so existing
    statements containing it pick up the mention, and — per the auto-plural
    decision — also create its regular plural as a generated child (unless
    there's no confident plural or the text is already taken). Returns the
    primary name_id."""
    assert _conn is not None
    name_id = store.create_name(_conn, text, entity_id)
    _index_name(name_id, text)
    store.enqueue_recompute_scan(_conn, text)
    _generate_plural(name_id, text, entity_id)
    return name_id


def _generate_plural(source_name_id: str, text: str, entity_id: str) -> None:
    """Auto-create the regular plural of `text` as a generated child of
    `source_name_id`. No-op when there is no confident regular plural, or
    when the plural text is already taken (global UNIQUE — never steal
    another entity's name)."""
    assert _conn is not None
    plural = plurals.regular_plural(text)
    if plural is None or store.get_name_by_text(_conn, plural) is not None:
        return
    child_id = store.create_name(
        _conn, plural, entity_id, generated_from_name_id=source_name_id
    )
    _index_name(child_id, plural)
    store.enqueue_recompute_scan(_conn, plural)


def _delete_name_cascade(name_id: str) -> tuple[int, list[str]]:
    """Delete a name and any generated plurals it spawned: clear their
    mention / pending / annotation-mention rows, drop their vectors, delete
    the rows. Children are deleted before the parent (the
    `generated_from_name_id` self-reference is RESTRICT). Returns
    `(mentions_removed, affected_statement_ids)` — the statements that
    mentioned a removed name must be recomputed, since the removed name may
    have been the representative for an entity another of whose names still
    matches."""
    assert _conn is not None and _name_index is not None
    children = store.get_generated_children(_conn, name_id)
    ids = [c["id"] for c in children] + [name_id]
    affected: list[str] = []
    mentions_removed = 0
    for nid in ids:
        affected.extend(store.statements_mentioning_name(_conn, nid))
        mentions_removed += _conn.execute(
            "DELETE FROM statement_mentions WHERE name_id = ?", (nid,)
        ).rowcount
        _conn.execute("DELETE FROM pending_mentions WHERE name_id = ?", (nid,))
        _conn.execute("DELETE FROM annotation_mentions WHERE name_id = ?", (nid,))
        _drop_name_from_index(nid)
        _conn.execute("DELETE FROM names WHERE id = ?", (nid,))
    _conn.commit()
    return mentions_removed, affected


def _regenerate_plurals(source_name_id: str, new_text: str) -> list[str]:
    """A renamed name's old generated plurals are stale — delete them and
    generate a fresh plural from `new_text`. Returns statement ids affected
    by the removed children, for recompute."""
    assert _conn is not None and _name_index is not None
    affected: list[str] = []
    for child in store.get_generated_children(_conn, source_name_id):
        affected.extend(store.statements_mentioning_name(_conn, child["id"]))
        _conn.execute(
            "DELETE FROM statement_mentions WHERE name_id = ?", (child["id"],)
        )
        _conn.execute("DELETE FROM pending_mentions WHERE name_id = ?", (child["id"],))
        _conn.execute(
            "DELETE FROM annotation_mentions WHERE name_id = ?", (child["id"],)
        )
        _drop_name_from_index(child["id"])
        _conn.execute("DELETE FROM names WHERE id = ?", (child["id"],))
    _conn.commit()
    src = store.get_name_by_id(_conn, source_name_id)
    if src is not None:
        _generate_plural(source_name_id, new_text, src["entity_id"])
    return affected


def _entity_ids_for_names(name_texts: list[str]) -> set[str]:
    """Resolve a list of name texts to entity_ids. Raises on any unknown."""
    assert _conn is not None
    entity_ids: set[str] = set()
    for text in name_texts:
        row = store.get_name_by_text(_conn, text)
        if row is None:
            raise ValueError(f"name {text!r} does not exist")
        entity_ids.add(row["entity_id"])
    return entity_ids


#: Cosine threshold for the write-time near-duplicate warning. Anything
#: at or above this is surfaced in `near_duplicates` on the upsert
#: response — soft signal, never blocks the write.
NEAR_DUPLICATE_THRESHOLD = 0.85

#: Truncation cap for `text` snippets returned in `near_duplicates` and
#: `discover_facts.matches`. Long enough to recognise the fact, short
#: enough to keep batch responses lean. Callers wanting the full text
#: should follow up with `get_statements(ids)`.
SNIPPET_CHARS = 100


def _snippet(text: str) -> str:
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1] + "…"


def _near_duplicates(
    vec: list[float],
    *,
    exclude_id: str | None = None,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Return existing statements whose vector is at or above `threshold`
    cosine similarity to `vec`. The statement matching `exclude_id` is
    dropped (used to skip the upsert's own freshly-inserted vector).
    `text` is truncated to a snippet to keep batch responses lean.
    """
    assert _index is not None and _conn is not None
    # +1 to allow excluding the self-hit without dropping under k results.
    hits = _index.search(vec, k=k + (1 if exclude_id else 0))
    out: list[dict[str, Any]] = []
    for vid, distance in hits:
        bid = store.get_statement_id_by_vector_id(_conn, vid)
        if bid is None or bid == exclude_id:
            continue
        score = 1.0 - distance
        if score < threshold:
            continue
        row = store.get_statement(_conn, bid)
        if row is None:
            continue
        out.append({"id": bid, "text": _snippet(row["text"]), "score": score})
        if len(out) >= k:
            break
    return out


def _link_dict(
    *,
    to_id: str | None = None,
    from_id: str | None = None,
    link_type: str,
    when: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the response dict for an edge, omitting `when` when None so
    unconditional edges keep the simpler shape callers expect.

    The endpoint field is the generic `from_id` / `to_id` — values may
    be statement ids (`stm_…`) or entity ids (`ent_…`); the caller
    distinguishes by the id prefix. This is the uniform link shape used
    on hydration output."""
    out: dict[str, Any] = {"link_type": link_type}
    if to_id is not None:
        out["to_id"] = to_id
    if from_id is not None:
        out["from_id"] = from_id
    if when is not None:
        out["when"] = when
    return out


def _statement_kind(
    statement_rows: dict[str, sqlite3.Row],
    statement_id: str,
    *,
    self_id: str | None = None,
    self_kind: str | None = None,
) -> str:
    if self_id is not None and statement_id == self_id:
        assert self_kind is not None
        return self_kind
    return statement_rows[statement_id]["kind"]


def _direction_entry(link_type: str) -> dict[str, list[str] | None] | None:
    direction = link_rules.LINK_DIRECTION.get(link_type)
    if direction is None:
        return None
    source_kinds, target_kinds = direction
    return {
        "source_kinds": None if source_kinds is None else sorted(source_kinds),
        "target_kinds": None if target_kinds is None else sorted(target_kinds),
    }


def _format_flip_error(
    *,
    position: str,
    from_id: str,
    to_id: str,
    link_type: str,
    from_kind: str,
    to_kind: str,
) -> str | None:
    err = link_rules.flip_error(link_type, from_kind, to_kind)
    if err is None:
        return None
    return f"{position}: {from_id} ({from_kind}) -> {to_id} ({to_kind}): {err}"


def _at_refs_in_when(when: dict[str, Any] | None) -> list[int]:
    """Return every `@N` index referenced anywhere in a when-tree.
    Used by the batch upsert's cascade detection."""
    if when is None:
        return []
    out: list[int] = []
    for leaf_id in when_expression.leaves(when):
        if isinstance(leaf_id, str) and leaf_id.startswith("@"):
            try:
                out.append(int(leaf_id[1:]))
            except ValueError:
                continue
    return out


def _resolve_when_tree(
    when: dict[str, Any] | None,
    resolve_id: Callable[[str, str], object],
    position: str,
) -> dict[str, Any] | None:
    """Walk a when-tree and resolve every leaf's `statement_id` via
    `resolve_id(ref, position)`. Returns a new tree (input unchanged).

    Used by both the single-record path (where `resolve_id` checks the
    id exists in the store) and the batch path (where `resolve_id`
    additionally accepts `@N` refs and returns int indexes).
    """
    if when is None:
        return None
    when_expression.validate(when)

    def _walk(expr: dict[str, Any], pos: str) -> dict[str, Any]:
        if "statement_id" in expr:
            return {"statement_id": resolve_id(expr["statement_id"], pos)}
        return {
            "op": expr["op"],
            "of": [_walk(c, f"{pos}.of[{i}]") for i, c in enumerate(expr["of"])],
        }

    return _walk(when, position)


def _hydrate_statement(statement_id: str, score: float | None) -> dict[str, Any]:
    assert _conn is not None
    row = store.get_statement(_conn, statement_id)
    assert row is not None
    mentions = [
        {"name_id": m["name_id"], "name": m["name"], "entity_id": m["entity_id"]}
        for m in store.get_mentions(_conn, statement_id)
    ]
    links = [
        _link_dict(to_id=to_id, link_type=lt, when=when)
        for to_id, lt, when in store.get_links(_conn, statement_id)
    ]
    # Mix in entity-endpoint edges where the statement is the source
    # (direction='se'). Externally indistinguishable from statement→statement
    # edges — caller reads the id prefix on `to_id` to know the kind.
    es_outgoing, _ = store.get_entity_statement_links_for_statement(_conn, statement_id)
    links.extend(
        _link_dict(to_id=ent_id, link_type=lt, when=when)
        for ent_id, lt, when in es_outgoing
    )
    out: dict[str, Any] = {
        "id": row["id"],
        "kind": row["kind"],
        "text": row["text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "mentions": mentions,
        "links": links,
    }
    if score is not None:
        out["score"] = score
    return out


#: Per-hit cap on reverse-graph edges (incoming_links + when_references) when a
#: statement is hydrated by the *wide* surfaces (search / survey). Bounds the
#: convergence-hub blowup `search_statements` warns about: a hub with hundreds
#: of incoming `configures` / `governed-by` edges would otherwise dominate the
#: result. When capped, a `*_truncated` count tells the caller to
#: `get_statements([id])` for the complete set. `get_statements` is uncapped —
#: it is an explicit, targeted fetch.
_REVERSE_EDGE_CAP = 25


def _hydrate_statement_full(
    statement_id: str, score: float | None, *, reverse_cap: int | None = None
) -> dict[str, Any]:
    """`_hydrate_statement` plus the reverse-graph edges (`incoming_links` and
    `when_references`) — the full shape `get_statements` returns.

    The single hydration path shared by `get_statements`, `search_statements`,
    and `survey_statements`, so a search/survey hit arrives fully hydrated and
    no longer needs a follow-up `get_statements` on the same id just to learn
    what points at it. `reverse_cap` bounds each reverse-edge list (the wide
    search/survey surfaces pass it; `get_statements` passes None)."""
    assert _conn is not None
    out = _hydrate_statement(statement_id, score=score)

    incoming = [
        _link_dict(from_id=from_id, link_type=lt, when=when)
        for from_id, lt, when in store.get_incoming_links(_conn, statement_id)
    ]
    # Entity→statement edges pointing at this statement (direction='es').
    _, es_incoming = store.get_entity_statement_links_for_statement(_conn, statement_id)
    incoming.extend(
        _link_dict(from_id=ent_id, link_type=lt, when=when)
        for ent_id, lt, when in es_incoming
    )

    when_refs: list[dict[str, Any]] = [
        {"from_id": from_id, "to_id": to_id, "link_type": lt, "when": when_tree}
        for from_id, to_id, lt, when_tree in store.get_when_references(
            _conn, statement_id
        )
    ]
    # Entity↔statement edges that condition on this statement.
    for (
        ent_id,
        stmt_id,
        direction,
        lt,
        when_tree,
    ) in store.get_entity_statement_when_references(_conn, statement_id):
        if direction == "es":
            when_refs.append(
                {
                    "from_id": ent_id,
                    "to_id": stmt_id,
                    "link_type": lt,
                    "when": when_tree,
                }
            )
        else:
            when_refs.append(
                {
                    "from_id": stmt_id,
                    "to_id": ent_id,
                    "link_type": lt,
                    "when": when_tree,
                }
            )

    if reverse_cap is not None and len(incoming) > reverse_cap:
        out["incoming_links_truncated"] = len(incoming)
        incoming = incoming[:reverse_cap]
    if reverse_cap is not None and len(when_refs) > reverse_cap:
        out["when_references_truncated"] = len(when_refs)
        when_refs = when_refs[:reverse_cap]
    out["incoming_links"] = incoming
    out["when_references"] = when_refs
    return out


@tool
def search_statements(
    query: str,
    limit: int = 10,
    min_score: float = -1.0,
    depth: int = 0,
    direction: Literal["both", "children", "parents"] = "both",
    mentions: list[str] = [],
    kind: str | None = None,
    name_boost: float = 0.3,
    name_top_k: int = 5,
    name_min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """Vector-search statements by semantic similarity to `query`.

    Returns up to `limit` direct hits with score >= `min_score`,
    sorted by score descending. Practical floors are usually 0.5–0.8.

    Scoring is cosine similarity + an alias-aware boost: the query is
    also searched against the entity-name index, and statements that
    mention entities whose names score high pick up additional weight.
    This means a query phrased with an alias ("tree", "node") still
    surfaces statements that only contain the canonical name
    ("selection flow", "step") in their text. Set `name_boost=0` to
    fall back to pure cosine ranking.

    Each hit is FULLY HYDRATED — the same shape `get_statements` returns:
    `{id, kind, text, mentions, links, incoming_links, when_references}`,
    plus a `score` on direct hits. So you do NOT need a follow-up
    `get_statements` on a hit's own id just to see what points at it — only
    to follow a link to a DIFFERENT id. The reverse-edge lists
    (`incoming_links` / `when_references`) are capped per hit; an
    `incoming_links_truncated` / `when_references_truncated` count appears
    when a convergence hub has more, in which case `get_statements([id])`
    returns the complete set.

    `mentions` is an optional entity filter — a list of name texts. When
    non-empty, hits must mention every entity referenced by those names
    (AND semantics — a hit matches only if it mentions all of them, not
    any of them). Each name is resolved to an entity_id; the call raises
    ValueError if any name does not exist. Useful for "find statements
    about X specifically" without relying on the query string to surface
    the right entity.

    If `depth > 0`, also walks the link graph from each direct hit up to
    `depth` hops. `direction` controls which way: `children` follows
    outgoing links only, `parents` follows incoming links only, `both`
    (default) follows both. Expanded statements are appended after the
    direct hits and carry no `score` field — direct hits do. The mentions
    and kind filters apply only to direct hits; expansions ignore them.

    Depth pitfall: convergence hubs (statements with many `configures` or
    `governed-by` parents — e.g. an "edge conditions are evaluated" node)
    leak unrelated subgraphs into the result when expanded. If you're
    chasing a specific causal chain, prefer `depth=1` from a well-targeted
    hit and use `get_statements(ids)` to step further. Reserve `depth=2+`
    for breadth scans where noise is acceptable.

    Each hit's `mentions` is `[{name_id, name, entity_id}]` so callers can
    address the underlying name and entity directly (e.g., for `merge_entities`
    or `move_name`).

    Optional `kind` ("event" / "state" / "capability") restricts direct
    hits to that kind.

    Boost tunables (defaults usually fine):
      `name_boost`     — weight applied to the best matching entity-name
                         score. 0 disables alias-aware retrieval.
      `name_top_k`     — how many top names to consider from the name index.
      `name_min_score` — drop name matches below this cosine. Keeps
                         canonical queries unaffected when no name is
                         clearly relevant.
    """
    assert _index is not None and _conn is not None and _name_index is not None

    required_entity_ids = _entity_ids_for_names(mentions) if mentions else set()

    with trace_span("embed"):
        vec = embed.embed(query)

    # Alias-aware recall: search the name index too. Top-K names above
    # `name_min_score` are resolved to their entity_ids; each entity gets
    # the max-scoring name. Statements mentioning a boosted entity get
    # final_score = cosine + name_boost * entity_score, lifting them
    # against alias-using queries without harming canonical ones.
    entity_boost: dict[str, float] = {}
    if name_boost > 0.0 and name_top_k > 0:
        for vid, dist in _name_index.search(vec, k=name_top_k):
            sc = 1.0 - dist
            if sc < name_min_score:
                continue
            nid = store.get_name_id_by_vector_id(_conn, vid)
            if nid is None:
                continue
            name_row = store.get_name_by_id(_conn, nid)
            if name_row is None:
                continue
            eid = name_row["entity_id"]
            if sc > entity_boost.get(eid, 0.0):
                entity_boost[eid] = sc

    # Widen the candidate set so boost-driven re-ranking has material
    # to lift. Without boost, we keep the historical narrow fetch.
    if entity_boost or required_entity_ids or kind:
        fetch_k = max(limit * 4, 40)
    else:
        fetch_k = limit
    with trace_span("vector_search"):
        raw_hits = _index.search(vec, k=fetch_k)

    scored: list[tuple[str, float, float]] = []  # (statement_id, final, cosine)
    seen: set[str] = set()
    for vector_id, distance in raw_hits:
        cosine = 1.0 - distance
        statement_id = store.get_statement_id_by_vector_id(_conn, vector_id)
        if statement_id is None or statement_id in seen:
            continue
        mention_entity_ids = {
            m["entity_id"] for m in store.get_mentions(_conn, statement_id)
        }
        if required_entity_ids and not required_entity_ids.issubset(mention_entity_ids):
            continue
        if kind is not None:
            row = store.get_statement(_conn, statement_id)
            if row is None or row["kind"] != kind:
                continue
        boost = 0.0
        for eid in mention_entity_ids:
            if eid in entity_boost and entity_boost[eid] > boost:
                boost = entity_boost[eid]
        final = cosine + name_boost * boost
        if final < min_score:
            continue
        seen.add(statement_id)
        scored.append((statement_id, final, cosine))

    scored.sort(key=lambda x: x[1], reverse=True)
    direct: list[dict[str, Any]] = []
    for statement_id, final, _cos in scored[:limit]:
        direct.append(
            _hydrate_statement_full(
                statement_id, score=final, reverse_cap=_REVERSE_EDGE_CAP
            )
        )
    seen = {item[0] for item in scored[:limit]}

    if depth <= 0:
        return direct

    follow_children = direction in ("both", "children")
    follow_parents = direction in ("both", "parents")

    expanded: list[dict[str, Any]] = []
    frontier: set[str] = set(seen)
    for _ in range(depth):
        next_frontier: set[str] = set()
        for bid in frontier:
            if follow_children:
                for to_id, _lt, _when in store.get_links(_conn, bid):
                    if to_id not in seen:
                        seen.add(to_id)
                        next_frontier.add(to_id)
            if follow_parents:
                for from_id, _lt, _when in store.get_incoming_links(_conn, bid):
                    if from_id not in seen:
                        seen.add(from_id)
                        next_frontier.add(from_id)
        for bid in next_frontier:
            expanded.append(
                _hydrate_statement_full(bid, score=None, reverse_cap=_REVERSE_EDGE_CAP)
            )
        if not next_frontier:
            break
        frontier = next_frontier

    return direct + expanded


_SURVEY_LOG = logging.getLogger("mycelium.survey")


def _embed_with_retry(text: str) -> list[float]:
    """Embed `text`, retrying once on a transient Ollama failure. Raises if
    both attempts fail — the caller decides whether that is fatal."""
    with trace_span("embed"):
        try:
            return embed.embed(text)
        except Exception:  # noqa: BLE001 — transient Ollama failure; retry once
            return embed.embed(text)


def _search_index_with_retry(vec: list[float], k: int) -> list[tuple[int, float]]:
    """Search the statement index, retrying once on a transient failure.
    Returns an empty list if both attempts fail — an empty result for one
    sub-query is valid (it contributes nothing), not an error."""
    assert _index is not None
    with trace_span("vector_search"):
        try:
            return _index.search(vec, k)
        except Exception:  # noqa: BLE001 — transient index failure; retry once
            try:
                return _index.search(vec, k)
            except Exception:  # noqa: BLE001
                return []


@tool(role="reader")
def survey_statements(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Decomposes a multi-part query and searches each part, returning the
    combined nearest statements. Prefer over `search_statements` when the
    question covers several distinct things and you want broad coverage
    before narrowing.

    A multi-part question embedded as one whole-question vector blurs its
    parts together; searching each part separately gives broader, sharper
    coverage. This splits `query` into sub-queries, runs an independent
    semantic search per part (top-`k` each), then unions and ranks the
    results into one flat, deduped list.

    Returns the same per-hit shape as `search_statements` — each hit is
    FULLY HYDRATED (`{id, kind, text, mentions, links, incoming_links,
    when_references}` plus a `score`, reverse edges capped per hit), so a
    hit needs no follow-up `get_statements` to see what points at it. The
    two tools are interchangeable to a consumer — the internal
    decomposition is invisible.
    A statement surfaced by several sub-queries ranks above one surfaced by
    a single sub-query, and appears once.

    `score` is pure cosine similarity (1 − distance). Unlike
    `search_statements` it carries no alias name-boost, so scores are not
    directly comparable across the two tools.

    This is a wide net, not a filter: there is no score floor, so every
    sub-query contributes its top-`k` even when its nearest match is weak.
    Relevance and sufficiency judgements belong to the consumer. Output is
    deterministic given a fixed index and embedder.
    """
    assert _index is not None and _conn is not None

    if not query.strip():
        return []

    raw_subqueries = survey.decompose(query)
    candidates = [s for s in raw_subqueries if survey.usable(s)]
    dropped = len(raw_subqueries) - len(candidates)

    # Embed once per candidate; the vector is reused for both dedup and the
    # search below, so each sub-query is embedded exactly once. A persistent
    # embed failure for one candidate drops it (it contributes nothing).
    embedded: list[tuple[str, list[float]]] = []
    for sub in candidates:
        try:
            embedded.append((sub, _embed_with_retry(sub)))
        except Exception as exc:  # noqa: BLE001
            _SURVEY_LOG.warning(
                "survey: dropping sub-query %r (embed failed: %s)", sub, exc
            )

    embedded = survey.dedup_subqueries(embedded)

    fallback = not embedded
    if fallback:
        # Decomposition yielded nothing usable (all stopword/single-char, all
        # failed to embed, or all collapsed by dedup). Never return empty-
        # handed for that reason — search the whole query as one. A persistent
        # embed failure HERE is a real outage, not dry decomposition, so let
        # it raise rather than masquerade as "no matches".
        embedded = [(query, _embed_with_retry(query))]

    # Union by statement_id: (count of distinct sub-queries that surfaced it,
    # best cosine across them).
    union: dict[str, tuple[int, float]] = {}
    for sub, vec in embedded:
        surfaced: set[str] = set()
        for vector_id, distance in _search_index_with_retry(vec, k):
            statement_id = store.get_statement_id_by_vector_id(_conn, vector_id)
            # Skip vid→sid drift, and count each statement at most once per
            # sub-query so duplicate vectors can't inflate the count-rank.
            if statement_id is None or statement_id in surfaced:
                continue
            surfaced.add(statement_id)
            cosine = 1.0 - distance
            count, best = union.get(statement_id, (0, float("-inf")))
            union[statement_id] = (count + 1, max(best, cosine))
        _SURVEY_LOG.debug(
            "survey: sub-query %r surfaced %d statements", sub, len(surfaced)
        )

    ranked = survey.rank_statements(union)
    _SURVEY_LOG.info(
        "survey: produced=%d hygiene_dropped=%d searched=%d fallback=%s results=%d",
        len(raw_subqueries),
        dropped,
        len(embedded),
        fallback,
        len(ranked),
    )
    return [
        _hydrate_statement_full(sid, score=score, reverse_cap=_REVERSE_EDGE_CAP)
        for sid, score in ranked
    ]


@tool(role="asker")
def ask(
    question: str, depth: Literal["standard", "quick"] = "standard"
) -> dict[str, Any]:
    """Resolve a natural-language question against the substrate, honestly.

    The higher-level entry point for callers who don't want to compose the read
    primitives by hand (docs generation, internal support). Under the hood it
    runs an in-process Sonnet reasoning loop that drives the same read
    primitives, follows typed links, re-searches for semantically-adjacent
    statements, and synthesises a structured answer that is explicit about gaps
    and provenance.

    Returns one of two shapes (discriminated by `outcome`):
      * `answered` — `answer`, `confidence` (high/medium/low, derived from
        gaps), `interpretation`, `gaps`, `provenance` (statement ids), `trace`.
      * `needs_clarification` — a clarifying `question`, ≥2 candidate
        interpretations (each naming what it would pull), `known_so_far`,
        `trace`. Terminal: re-ask with the disambiguated question.

    `depth` trades thoroughness for latency:
      * `standard` (default) — the full loop: recon, targeted retrieval, and a
        concept-seeded adjacency re-search before concluding. Most thorough;
        can run tens of seconds.
      * `quick` — a latency-boxed fast path for callers with a hard timeout
        (e.g. an MCP client that drops the call at ~30s). Drops the adjacency
        floor and tightens the caps so it collapses to recon -> a targeted read
        or two -> answer, returning a real answer well inside the window. It can
        miss unlinked-but-relevant statements the adjacency re-search would find,
        so gaps/confidence are your guide.

    The call runs a multi-second reasoning loop bounded by an operation cap and
    a wall-clock budget; on exhaustion it degrades to a low-confidence partial
    answer rather than raising.
    """
    from .ask import AskConfig, run_ask
    from .ask.config import for_depth

    config = for_depth(AskConfig.from_env(), depth)
    if config.trace_log_path is None and _data_dir is not None:
        config = replace(config, trace_log_path=str(_data_dir / "ask_trace.jsonl"))
    return run_ask(question, config=config).model_dump()


@tool
def ingest(text: str) -> dict[str, Any]:
    """Extract knowledge from free text and emit a reviewable DRAFT of proposed
    substrate changes. Never writes to the substrate live.

    The higher-level write-side counterpart to `ask`: hand it a block of text
    (release notes, a spec excerpt, support transcript) and it runs an
    in-process Sonnet loop that extracts atomic statements, reconciles each one
    against existing knowledge with the read primitives, classifies it
    (new/duplicate/refinement/contradiction), and proposes links — then queues
    the result as a DRAFT for a human to review and apply. The inner model is
    given only read tools plus one terminal emit tool; it has no write path. The
    draft is created in deterministic code, so nothing is ever written live.

    Returns one of two shapes (discriminated by `outcome`):
      * `draft_created` — `draft_id` ("drf_…"), the queued `ops`, `flagged`
        contradictions, `skipped_duplicates`, and `trace`.
      * `nothing_to_ingest` — a `reason` (all duplicates / nothing extractable /
        degraded) and `trace`.

    The call runs a multi-second reasoning loop bounded by an operation cap and
    a wall-clock budget; on exhaustion it degrades to a forced emit (or
    `nothing_to_ingest`) rather than raising.
    """
    from .ingest import IngestConfig, run_ingest

    config = IngestConfig.from_env()
    if config.trace_log_path is None and _data_dir is not None:
        config = replace(config, trace_log_path=str(_data_dir / "ingest_trace.jsonl"))
    return run_ingest(text, config=config).model_dump()


def _resolve_research_source(name: str | None) -> str:
    from .research import sources as research_sources

    try:
        configured = research_sources.load_sources()
    except research_sources.SourceError as exc:
        raise ValueError(str(exc)) from exc

    if name is not None:
        if name not in configured:
            raise ValueError(
                f"unknown source '{name}'; configured: {sorted(configured)}"
            )
        return name

    if not configured:
        raise ValueError("no research sources configured (set MYCELIUM_SOURCES)")
    if len(configured) == 1:
        return next(iter(configured))
    raise ValueError(
        "source must be specified when multiple research sources are configured: "
        f"{sorted(configured)}"
    )


@tool(role="drafter")
def start_research(topic: str, source: str | None = None) -> dict[str, Any]:
    """Start a background research run: explore a configured source codebase
    on `topic` and, if anything substantiated is found, emit a reviewable
    DRAFT (never a live write).

    Returns immediately with the serialized run row (its `status` will be
    "running"); poll `get_research_run(run_id)` for the outcome. `source` may
    be omitted when exactly one source is configured. Raises when the
    active-run cap is reached (MYCELIUM_RESEARCH_MAX_ACTIVE, default 2), when
    `source` is unknown, or when it is omitted with several sources
    configured. Returns {run row: id, topic, source, created_at, created_by,
    started_at, finished_at, outcome, draft_id, error, trace_ref, status}."""
    assert _drafts_conn is not None and _data_dir is not None
    from . import auth as _auth, research_runs, research_store

    source_name = _resolve_research_source(source)
    principal = _auth.current_principal.get()
    created_by = principal.id if principal is not None else None
    run_id = research_runs.start_run(
        topic=topic,
        source=source_name,
        created_by=created_by,
        data_dir=_data_dir,
        conn=_drafts_conn,
    )
    row = research_store.get_run(_drafts_conn, run_id)
    assert row is not None
    return research_store.serialize_run(row)


@tool
def list_research_runs() -> dict[str, Any]:
    """List research runs, newest first, each with a derived `status`
    (queued/running/draft_created/nothing_found/failed).

    Returns {"runs": [run rows]}."""
    assert _drafts_conn is not None
    from . import research_store

    return {
        "runs": [
            research_store.serialize_run(row)
            for row in research_store.list_runs(_drafts_conn)
        ]
    }


@tool
def get_research_run(run_id: str) -> dict[str, Any]:
    """Fetch one research run by id, including outcome, draft_id (when a
    draft was created), error, and trace_ref.

    Returns the serialized run row. Raises for an unknown run_id."""
    assert _drafts_conn is not None
    from . import research_store

    row = research_store.get_run(_drafts_conn, run_id)
    if row is None:
        raise ValueError(f"research run not found: {run_id}")
    return research_store.serialize_run(row)


@tool
def list_research_sources() -> dict[str, Any]:
    """List the configured research sources a run can target (names and repo
    coordinates only - never credentials).

    Returns {"sources": [{name, owner, repo, ref}]}."""
    from .research import sources

    try:
        configured = sources.load_sources()
    except sources.SourceError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "sources": [
            {
                "name": source.name,
                "owner": source.owner,
                "repo": source.repo,
                "ref": source.ref,
            }
            for source in configured.values()
        ]
    }


@tool
def upsert_entity(name: str, description: str) -> dict[str, str]:
    """Create or update an entity by name.

    If a name with this text already exists, updates that entity's description
    and returns its id. Otherwise creates a new entity AND a name pointing
    at it.
    """
    assert _conn is not None
    existing = store.get_name_by_text(_conn, name)
    if existing is not None:
        store.update_entity_description(_conn, existing["entity_id"], description)
        return {"entity_id": existing["entity_id"]}
    entity_id = store.create_entity(_conn, description)
    _create_name_with_plural(name, entity_id)
    layout_baker.schedule_rebake()
    return {"entity_id": entity_id}


@tool
def upsert_statement(
    kind: str,
    text: str,
    links: list[LinkSpec],
    id: str | None = None,
    incoming_links: list[IncomingLinkSpec] = [],
    allow_phrasing_violations: bool = False,
) -> dict[str, Any]:
    """Create a new statement or update an existing one.

    `kind` discriminates by the shape of claim the text makes. Required
    on every call. Starting vocabulary (open — grow as needed, same
    posture as link types):
      - `event`      — something happening (present-tense action verbs).
      - `state`      — a condition holding (verbs like "is", "has",
                       "remains").
      - `capability` — a modal claim ("can", "may", "is able to").
    The substrate does not lock the vocabulary and does not enforce
    kind-edge compatibility (e.g., that `triggers` only joins events) —
    trust the writer. Phrasing rules dispatch by kind for the starting
    vocabulary above; other kinds run the generic catalog.

    Without `id`: always creates a brand-new statement with a fresh
    statement_id. There is NO text-based dedup — calling twice with the
    same text creates two statements. To update an existing statement, you
    must pass its `id` (capture it from a previous call's return value
    or from a `search_statements` hit).

    With `id`: replaces the statement at that id wholesale — re-embeds the
    new `text` and overwrites outgoing `links` with the exact list you pass
    (they are NOT appended). To add a single outgoing link, pass the full
    updated list, not just the addition. Raises if `id` does not exist.

    Mentions (which entities this statement refers to) are NOT passed in —
    they are derived automatically from the text and kept up to date. The
    statement simply mentions whatever named entities its words contain.

    `links` are the OUTGOING typed edges from this statement to existing
    targets — `{to_id, link_type}`. `incoming_links` are the
    INCOMING typed edges from existing sources to this statement —
    `{from_id, link_type}` — useful when wiring a new child
    statement under existing parents in one call instead of two. Both
    sides validate that referenced statement ids exist before any mutation.

    Asymmetric semantics: `links` is wholesale-replaced on update because
    it's the outgoing set this statement owns. `incoming_links` is
    idempotent-insert only (never deletes) because incoming edges live on
    OTHER statements and shouldn't be removed by an update to this one.

    `text` is checked against the phrasing catalog (compound, rule-shaped,
    property-shaped, hedge) before any mutation. By default, any match
    rejects the call: returns `{"rejected": True, "violations": [...]}`
    without writing. Pass `allow_phrasing_violations=True` to proceed
    anyway — the success response then carries the same violations under
    a `phrasing_violations` key as a warning.
    """
    assert _conn is not None and _index is not None

    violations = phrasing.check(text, kind=kind)
    if violations and not allow_phrasing_violations:
        return {"rejected": True, "violations": violations}

    # Validate every referenced statement id BEFORE mutating, so a typo can't
    # half-apply. Outgoing `links` targets, `incoming_links` sources, and
    # every `statement_id` leaf inside any `when` tree are all checked here.
    statement_rows: dict[str, sqlite3.Row] = {}

    def _check_existing(ref: str, position: str) -> str:
        row = store.get_statement(_conn, ref)
        if row is None:
            raise ValueError(f"{position}: statement {ref!r} does not exist")
        statement_rows[ref] = row
        return ref

    if id is not None:
        _check_existing(id, "id")
    for i, spec in enumerate(links):
        _check_existing(spec["to_id"], f"links[{i}].to_id")
        if "when" in spec:
            _resolve_when_tree(spec["when"], _check_existing, f"links[{i}].when")
    for i, il in enumerate(incoming_links):
        _check_existing(il["from_id"], f"incoming_links[{i}].from_id")
        if "when" in il:
            _resolve_when_tree(il["when"], _check_existing, f"incoming_links[{i}].when")

    flip_errors: list[str] = []
    for i, spec in enumerate(links):
        to_id = spec["to_id"]
        to_kind = _statement_kind(statement_rows, to_id, self_id=id, self_kind=kind)
        err = _format_flip_error(
            position=f"links[{i}]",
            from_id=id or "<new statement>",
            to_id=to_id,
            link_type=spec["link_type"],
            from_kind=kind,
            to_kind=to_kind,
        )
        if err is not None:
            flip_errors.append(err)
    for i, il in enumerate(incoming_links):
        from_id = il["from_id"]
        from_kind = _statement_kind(statement_rows, from_id, self_id=id, self_kind=kind)
        err = _format_flip_error(
            position=f"incoming_links[{i}]",
            from_id=from_id,
            to_id=id or "<new statement>",
            link_type=il["link_type"],
            from_kind=from_kind,
            to_kind=kind,
        )
        if err is not None:
            flip_errors.append(err)
    if flip_errors:
        raise ValueError("flipped link direction:\n" + "\n".join(flip_errors))

    vec = embed.embed(text)
    link_pairs = [
        (item["to_id"], item["link_type"], item.get("when")) for item in links
    ]

    if id is not None:
        store.update_statement(_conn, id, kind, text)
        vector_id = store.get_vector_id(_conn, id)
        assert vector_id is not None
        _index.replace(vector_id, vec)
        store.replace_links(_conn, id, link_pairs)
        statement_id = id
    else:
        statement_id = store.create_statement(_conn, kind, text)
        vector_id = store.next_vector_id(_conn)
        store.set_vector_id(_conn, statement_id, vector_id)
        _index.add(vector_id, vec)
        store.replace_links(_conn, statement_id, link_pairs)

    # Mentions are derived from the text, not asserted by the caller.
    _derive_statement_mentions(statement_id, text)

    if incoming_links:
        edges = [
            (il["from_id"], statement_id, il["link_type"], il.get("when"))
            for il in incoming_links
        ]
        store.insert_links(_conn, edges)

    _persist_index()
    response: dict[str, Any] = {
        "statement_id": statement_id,
        "near_duplicates": _near_duplicates(vec, exclude_id=statement_id),
    }
    if violations:
        response["phrasing_violations"] = violations
    return response


@tool
def upsert_statements(
    statements: list[BatchStatementSpec],
) -> dict[str, Any]:
    """Insert several statements in one call, with cross-references between
    siblings resolved server-side.

    For "I'm writing N atomic facts that are all part of one umbrella"
    or "umbrella + children + the contains edges between them", this is
    the right primitive — collapses what would be N+1+N tool calls into
    one and validates the cross-references atomically before mutating.

    Each item is the same shape as a single-record `upsert_statement`
    call, with one addition: any `to_statement_id` or `from_id`
    can be the literal string `"@N"` (N is a 0-based integer) to refer
    to the Nth statement in the same batch. Otherwise it must be an
    existing statement id. References are validated up front; an unknown
    id or out-of-range index raises before any write.

    Mentions are derived from each item's text automatically (see
    `upsert_statement`); there is no mentions field to pass.

    Phrasing validation runs per item before any mutation. Items whose
    text trips the phrasing catalog are rejected unless that item carries
    `allow_phrasing_violations: True`. Cascade rule: an item whose
    `links`, `incoming_links`, or any `when` tree references an `@N`
    that points to a rejected item is itself rejected (reason
    `"depends_on_rejected"`) — this avoids creating half-broken edges
    while keeping clean items in the batch passing.

    Returns:
        ```
        {
          "results": [
            {"statement_id": "stm_..."},                                # clean
            {"rejected": True, "violations": [...]},                   # phrasing-rejected
            {"statement_id": "stm_...", "phrasing_violations": [...]},  # bypassed
            {"rejected": True, "reason": "depends_on_rejected",
             "depends_on": [<int indexes>]}                            # cascaded
          ],
          "near_duplicates": {"stm_...": [...], ...}
        }
        ```
    """
    assert _conn is not None and _index is not None

    n = len(statements)
    if n == 0:
        return {"results": [], "near_duplicates": {}}

    # Phase 0: phrasing check per item. Items whose text trips the catalog
    # without bypass are marked directly rejected.
    item_violations: list[list[phrasing.Violation]] = []
    direct_rejected: set[int] = set()
    item_errors: list[list[str]] = [[] for _ in range(n)]
    for i, spec in enumerate(statements):
        viols = phrasing.check(spec["text"], kind=spec["kind"])
        item_violations.append(viols)
        if viols and not spec.get("allow_phrasing_violations", False):
            direct_rejected.add(i)

    # Phase 0b: cascade rejection — transitive closure on @-refs. Any
    # surviving item that references a rejected sibling via @N joins the
    # rejected set. Iterates to a fixed point so a chain @0→@1→@2 of
    # rejections cascades all the way.
    rejected: set[int] = set(direct_rejected)
    cascade_reasons: dict[int, list[int]] = {}

    def _spec_at_refs(spec: BatchStatementSpec) -> list[int]:
        refs: list[int] = []
        for link in spec.get("links", []) or []:
            ref = link.get("to_id")
            if ref and ref.startswith("@"):
                try:
                    refs.append(int(ref[1:]))
                except ValueError:
                    pass
            refs.extend(_at_refs_in_when(link.get("when")))
        for il in spec.get("incoming_links", []) or []:
            ref = il.get("from_id")
            if ref and ref.startswith("@"):
                try:
                    refs.append(int(ref[1:]))
                except ValueError:
                    pass
            refs.extend(_at_refs_in_when(il.get("when")))
        return refs

    changed = True
    while changed:
        changed = False
        for i, spec in enumerate(statements):
            if i in rejected:
                continue
            deps = sorted({r for r in _spec_at_refs(spec) if r in rejected})
            if deps:
                rejected.add(i)
                cascade_reasons[i] = deps
                changed = True

    # Phase 1: validate every cross-reference for SURVIVING items only.
    # Rejected items aren't created, so their refs don't need checking.
    statement_rows: dict[str, sqlite3.Row] = {}

    def _resolve_ref(ref: str, position: str) -> int | str:
        if ref.startswith("@"):
            try:
                idx = int(ref[1:])
            except ValueError:
                raise ValueError(f"{position}: malformed batch ref {ref!r}")
            if not (0 <= idx < n):
                raise ValueError(
                    f"{position}: batch index @{idx} out of range [0, {n})"
                )
            return idx
        row = store.get_statement(_conn, ref)
        if row is None:
            raise ValueError(f"{position}: statement {ref!r} does not exist")
        statement_rows[ref] = row
        return ref

    def _ref_kind(ref: int | str) -> str:
        if isinstance(ref, int):
            return statements[ref]["kind"]
        return statement_rows[ref]["kind"]

    def _ref_label(ref: int | str) -> str:
        return f"@{ref}" if isinstance(ref, int) else ref

    # Each resolved entry is (endpoint_ref, link_type, when_raw_tree).
    # `endpoint_ref` is int (sibling index) or str (existing id).
    # `when_raw_tree` is None or a tree whose leaves carry statement_ids
    # that are still in raw form ("@N" or existing ids); siblings get
    # remapped to real ids in Phase 5 once they're created.
    resolved_outgoing: list[list[tuple[int | str, str, dict[str, Any] | None]]] = [
        [] for _ in range(n)
    ]
    resolved_incoming: list[list[tuple[int | str, str, dict[str, Any] | None]]] = [
        [] for _ in range(n)
    ]
    for i, spec in enumerate(statements):
        if i in rejected:
            continue
        for j, link in enumerate(spec.get("links", []) or []):
            target = _resolve_ref(link["to_id"], f"statements[{i}].links[{j}]")
            when_raw = link.get("when")
            if when_raw is not None:
                # Validate shape + every leaf @N is in range / every existing id exists.
                _resolve_when_tree(
                    when_raw, _resolve_ref, f"statements[{i}].links[{j}].when"
                )
            resolved_outgoing[i].append((target, link["link_type"], when_raw))
        for j, il in enumerate(spec.get("incoming_links", []) or []):
            source = _resolve_ref(il["from_id"], f"statements[{i}].incoming_links[{j}]")
            when_raw = il.get("when")
            if when_raw is not None:
                _resolve_when_tree(
                    when_raw, _resolve_ref, f"statements[{i}].incoming_links[{j}].when"
                )
            resolved_incoming[i].append((source, il["link_type"], when_raw))

    for i, spec in enumerate(statements):
        if i in rejected:
            continue
        for j, (target, link_type, _when) in enumerate(resolved_outgoing[i]):
            err = _format_flip_error(
                position=f"statements[{i}].links[{j}]",
                from_id=f"@{i}",
                to_id=_ref_label(target),
                link_type=link_type,
                from_kind=spec["kind"],
                to_kind=_ref_kind(target),
            )
            if err is not None:
                item_errors[i].append(err)
        for j, (source, link_type, _when) in enumerate(resolved_incoming[i]):
            err = _format_flip_error(
                position=f"statements[{i}].incoming_links[{j}]",
                from_id=_ref_label(source),
                to_id=f"@{i}",
                link_type=link_type,
                from_kind=_ref_kind(source),
                to_kind=spec["kind"],
            )
            if err is not None:
                item_errors[i].append(err)

    flip_rejected = {i for i, errors in enumerate(item_errors) if errors}
    if flip_rejected:
        direct_rejected.update(flip_rejected)
        rejected.update(flip_rejected)
        changed = True
        while changed:
            changed = False
            for i, spec in enumerate(statements):
                if i in rejected:
                    continue
                deps = sorted({r for r in _spec_at_refs(spec) if r in rejected})
                if deps:
                    rejected.add(i)
                    cascade_reasons[i] = deps
                    changed = True

    # Phase 3: embed surviving items only. Slow path runs first so an
    # Ollama failure aborts cleanly without leaving partial state.
    vecs: dict[int, Any] = {}
    for i, spec in enumerate(statements):
        if i not in rejected:
            vecs[i] = embed.embed(spec["text"])

    # Phase 4: create surviving statements with their derived mentions, no
    # links yet. The name index is stable across the batch (statements
    # don't create names), so build it once.
    name_index = store.build_name_index(_conn)
    statement_ids: dict[int, str] = {}
    for i, spec in enumerate(statements):
        if i in rejected:
            continue
        bid = store.create_statement(_conn, spec["kind"], spec["text"])
        vid = store.next_vector_id(_conn)
        store.set_vector_id(_conn, bid, vid)
        _index.add(vid, vecs[i])
        store.derive_mentions(_conn, bid, spec["text"], name_index)
        statement_ids[i] = bid

    # Phase 5: insert edges between surviving items. Cascade guarantees no
    # @-ref endpoint is in `rejected`, so every edge has a real id at both
    # ends — but the when-trees still carry "@N" leaves that need final
    # substitution to real ids.
    def _resolve_endpoint(ref: int | str) -> str:
        return statement_ids[ref] if isinstance(ref, int) else ref

    def _materialize_when(when: dict[str, Any] | None) -> dict[str, Any] | None:
        if when is None:
            return None
        return when_expression.substitute_leaves(
            when,
            lambda leaf: statement_ids[int(leaf[1:])] if leaf.startswith("@") else leaf,
        )

    edges: list[tuple[str, str, str, dict[str, Any] | None]] = []
    for i in range(n):
        if i in rejected:
            continue
        for target, link_type, when in resolved_outgoing[i]:
            edges.append(
                (
                    statement_ids[i],
                    _resolve_endpoint(target),
                    link_type,
                    _materialize_when(when),
                )
            )
        for source, link_type, when in resolved_incoming[i]:
            edges.append(
                (
                    _resolve_endpoint(source),
                    statement_ids[i],
                    link_type,
                    _materialize_when(when),
                )
            )
    if edges:
        store.insert_links(_conn, edges)

    _persist_index()

    # Near-duplicate warnings per newly-inserted statement.
    near_dups: dict[str, list[dict[str, Any]]] = {}
    for i, bid in statement_ids.items():
        hits = _near_duplicates(vecs[i], exclude_id=bid)
        if hits:
            near_dups[bid] = hits

    # Build per-item results.
    results: list[dict[str, Any]] = []
    for i in range(n):
        if item_errors[i]:
            results.append({"rejected": True, "errors": item_errors[i]})
        elif i in direct_rejected:
            results.append({"rejected": True, "violations": item_violations[i]})
        elif i in rejected:
            results.append(
                {
                    "rejected": True,
                    "reason": "depends_on_rejected",
                    "depends_on": cascade_reasons[i],
                }
            )
        else:
            entry: dict[str, Any] = {"statement_id": statement_ids[i]}
            if item_violations[i]:
                entry["phrasing_violations"] = item_violations[i]
            results.append(entry)

    return {"results": results, "near_duplicates": near_dups}


@tool
def replace_text(
    id: str, text: str, allow_phrasing_violations: bool = False
) -> dict[str, Any]:
    """Update a statement's text without touching its mentions or links.

    Re-embeds the new text and replaces the vector at the same numeric
    label in hnswlib. Faster and safer than `upsert_statement(id=…)` when
    you only want to fix wording or extend the description: avoids the
    risk of dropping existing mentions or outgoing links by forgetting
    to enumerate them in the wholesale-replace path.

    Raises ValueError if `id` does not exist.

    `text` is checked against the phrasing catalog before mutating; on
    rejection returns `{"rejected": True, "violations": [...]}` and the
    statement is unchanged. `allow_phrasing_violations=True` proceeds
    anyway and surfaces the violations as a `phrasing_violations`
    warning on the success response.
    """
    assert _conn is not None and _index is not None
    row = store.get_statement(_conn, id)
    if row is None:
        raise ValueError(f"statement {id!r} does not exist")

    violations = phrasing.check(text, kind=row["kind"])
    if violations and not allow_phrasing_violations:
        return {"rejected": True, "violations": violations}

    vec = embed.embed(text)
    store.update_statement_text(_conn, id, text)
    vector_id = store.get_vector_id(_conn, id)
    assert vector_id is not None
    _index.replace(vector_id, vec)
    _persist_index()
    # Text changed → re-derive mentions.
    _derive_statement_mentions(id, text)
    response: dict[str, Any] = {"statement_id": id}
    if violations:
        response["phrasing_violations"] = violations
    return response


@tool
def patch_statement(
    id: str,
    kind: str | None = None,
    text: str | None = None,
    allow_phrasing_violations: bool = False,
) -> dict[str, Any]:
    """Partial update of an existing statement.

    Unlike `upsert_statement(id=…)` which replaces the whole record (and
    silently drops fields you forget to pass), `patch_statement` only
    modifies the fields you explicitly provide. Omit a field to leave
    it untouched.

    Patchable fields:
      - `kind` — re-classify without re-embedding.
      - `text` — replace the text and re-embed; phrasing-checked under
        the *effective* kind (the new kind if you also pass `kind`,
        otherwise the existing one). Mentions are re-derived from the new
        text automatically.

    Out of scope by design:
      - Mentions are derived from text, never set directly.
      - Outgoing links and incoming links live on a separate join table
        and are NEVER touched by this tool. Use `add_links` /
        `remove_links` for surgical link edits, or `upsert_statement`
        if you really want to replace the whole edge set.

    Embedding cost: we re-embed only when `text` is provided. Patching
    `kind` alone does not call the embedder and does not update the vector
    index or mentions — it's a single SQL update.

    Phrasing validation behaves identically to `replace_text`: returns
    `{"rejected": True, "violations": [...]}` without writing on
    rejection; `allow_phrasing_violations=True` proceeds and surfaces
    the violations as a `phrasing_violations` warning on success.

    Raises ValueError if `id` does not exist.
    """
    assert _conn is not None and _index is not None
    row = store.get_statement(_conn, id)
    if row is None:
        raise ValueError(f"statement {id!r} does not exist")

    if kind is None and text is None:
        return {"statement_id": id, "no_change": True}

    effective_kind = kind if kind is not None else row["kind"]

    # Phrasing check + embedding only when text is being patched. The
    # check runs under the *effective* kind so a same-call kind+text
    # patch sees the new kind's catalog, not the old one.
    violations: list[dict[str, Any]] = []
    vec = None
    if text is not None:
        violations = phrasing.check(text, kind=effective_kind)
        if violations and not allow_phrasing_violations:
            return {"rejected": True, "violations": violations}
        vec = embed.embed(text)

    # Mutate field-by-field so omitted fields stay untouched.
    if text is not None and kind is not None:
        store.update_statement(_conn, id, kind, text)
    elif text is not None:
        store.update_statement_text(_conn, id, text)
    elif kind is not None:
        store.update_statement_kind(_conn, id, kind)

    if vec is not None:
        vector_id = store.get_vector_id(_conn, id)
        assert vector_id is not None
        _index.replace(vector_id, vec)
        _persist_index()

    # Re-derive mentions only when the text changed (kind-only patches
    # don't affect what entities the text mentions).
    if text is not None:
        _derive_statement_mentions(id, text)

    response: dict[str, Any] = {"statement_id": id}
    if violations:
        response["phrasing_violations"] = violations
    if vec is not None:
        response["near_duplicates"] = _near_duplicates(vec, exclude_id=id)
    return response


@tool
def upsert_name(text: str, entity_id: str) -> dict[str, str]:
    """Attach an alias `text` to an existing entity.

    Idempotent if the name already points at `entity_id`. Fails if
    `entity_id` is unknown, or if the text is already taken by a different
    entity (use `move_name` or `merge_entities` to resolve those cases).
    """
    assert _conn is not None
    if store.get_entity_by_id(_conn, entity_id) is None:
        raise ValueError(f"entity {entity_id!r} does not exist")
    existing = store.get_name_by_text(_conn, text)
    if existing is not None:
        if existing["entity_id"] == entity_id:
            return {"name_id": existing["id"]}
        raise ValueError(
            f"name {text!r} already belongs to entity {existing['entity_id']!r}; "
            "use move_name or merge_entities"
        )
    name_id = _create_name_with_plural(text, entity_id)
    return {"name_id": name_id}


@tool
def merge_entities(from_entity_id: str, into_entity_id: str) -> dict[str, Any]:
    """Move every name from `from_entity_id` to `into_entity_id` and delete
    the source entity. Statements that mentioned the moved names continue
    to point at the same names (now under the new entity)."""
    assert _conn is not None
    if from_entity_id == into_entity_id:
        return {"into_entity_id": into_entity_id, "names_moved": 0}
    if store.get_entity_by_id(_conn, from_entity_id) is None:
        raise ValueError(f"entity {from_entity_id!r} does not exist")
    if store.get_entity_by_id(_conn, into_entity_id) is None:
        raise ValueError(f"entity {into_entity_id!r} does not exist")
    # Names move from source to target, so the entity-grouping of every
    # statement mentioning them changes — recompute those statements.
    moved_name_ids = [r["id"] for r in store.get_names_by_entity(_conn, from_entity_id)]
    moved = store.reassign_names(_conn, from_entity_id, into_entity_id)
    # Rewrite any entity_links referencing the source — outgoing rows
    # become outgoing on the target, incoming rows become incoming on
    # the target, and self-loops the merge would create are dropped.
    # Required before deleting the source: FK enforcement otherwise
    # blocks the delete.
    store.rewrite_entity_link_endpoints(_conn, from_entity_id, into_entity_id)
    # Mixed entity↔statement edges anchored on the source entity move
    # onto the target; UNIQUE collisions drop the rewriting row.
    store.rewrite_entity_statement_endpoints(_conn, from_entity_id, into_entity_id)
    store.merge_entity_annotation_attachments(_conn, from_entity_id, into_entity_id)
    store.delete_entity(_conn, from_entity_id)
    affected: list[str] = []
    for nid in moved_name_ids:
        affected.extend(store.statements_mentioning_name(_conn, nid))
    store.enqueue_recompute_statements(_conn, affected)
    return {
        "into_entity_id": into_entity_id,
        "names_moved": moved,
    }


@tool
def move_name(name_id: str, to_entity_id: str) -> dict[str, str]:
    """Reassign a single name to a different entity.

    The name's `text` is unchanged — only its `entity_id` binding moves.
    Because `statement_mentions` are keyed on `name_id` (not `entity_id`),
    every statement that mentioned this name continues to point at it,
    and now reports the new `entity_id` in its hydrated mentions.

    Combine with `upsert_entity` to split a name out into its own
    entity: create a fresh target entity first, then move the name onto
    it. Names left behind on the source entity are untouched.

    Raises ValueError if `name_id` or `to_entity_id` does not exist.
    """
    assert _conn is not None
    if store.get_name_by_id(_conn, name_id) is None:
        raise ValueError(f"name {name_id!r} does not exist")
    if store.get_entity_by_id(_conn, to_entity_id) is None:
        raise ValueError(f"entity {to_entity_id!r} does not exist")
    # The name's entity binding changes, so the entity-grouping of every
    # statement mentioning it (or its generated plurals) may change —
    # recompute them. Generated children follow the name onto the new
    # entity so the plural stays attached to the same concept.
    children = store.get_generated_children(_conn, name_id)
    store.set_name_entity(_conn, name_id, to_entity_id)
    affected = list(store.statements_mentioning_name(_conn, name_id))
    for child in children:
        store.set_name_entity(_conn, child["id"], to_entity_id)
        affected.extend(store.statements_mentioning_name(_conn, child["id"]))
    store.enqueue_recompute_statements(_conn, affected)
    return {"name_id": name_id, "entity_id": to_entity_id}


@tool
def rename_name(name_id: str, new_text: str) -> dict[str, str]:
    """Change a name's text in place — same name_id, same entity, new label.

    Use when an entity has been renamed in the product (e.g. "Recruiter"
    → "Hiring Manager") and you want every statement that mentions this
    entity to render under the new label without losing mention links.
    `statement_mentions` is keyed on name_id, so it keeps pointing at the
    same name and immediately starts showing the new text.

    Statement *text* is NOT rewritten — references in free-form text
    still read the old name. Use `replace_text` per record to update
    those (see mycelium-maintenance §1c on stale text after entity
    rename).

    Raises ValueError if `name_id` does not exist or if `new_text` is
    already used by a different name (resolve with `merge_entities` or
    `move_name` first).
    """
    assert _conn is not None
    # Statements mentioning this name may now match differently (their text
    # still contains the OLD label, which is no longer a name) — recompute
    # them. Regenerate the name's plural from the new text. Scan for the new
    # text so statements containing it pick up the mention.
    affected = list(store.statements_mentioning_name(_conn, name_id))
    store.rename_name(_conn, name_id, new_text)
    _reindex_name(name_id, new_text)
    affected.extend(_regenerate_plurals(name_id, new_text))
    store.enqueue_recompute_statements(_conn, affected)
    store.enqueue_recompute_scan(_conn, new_text)
    return {"name_id": name_id, "text": new_text}


@tool
def delete_name(name_id: str) -> dict[str, Any]:
    """Delete a single name (alias) from its entity.

    Cascade: every `statement_mentions` row that referenced this name is
    removed — those mentions disappear (the statements themselves stay,
    but lose this particular alias-mention). The owning entity is
    unaffected and may end up with zero remaining names; that's allowed.

    Use case: an alias was wrong (typo, slang the team stopped using,
    accidentally attached) and should not survive. To move a name onto a
    different entity instead, use `move_name`. To collapse two entities
    into one, use `merge_entities`.

    Returns `{deleted, mentions_removed}`.
    Raises ValueError on unknown id.
    """
    assert _conn is not None
    if store.get_name_by_id(_conn, name_id) is None:
        raise ValueError(f"name {name_id!r} does not exist")
    # Cascade through the name and any generated plurals, then recompute the
    # statements that mentioned them — a removed name may have been the
    # representative for an entity another of whose names still matches.
    mentions_removed, affected = _delete_name_cascade(name_id)
    store.enqueue_recompute_statements(_conn, affected)
    return {
        "deleted": True,
        "mentions_removed": mentions_removed,
    }


@tool
def delete_entity(id: str) -> dict[str, Any]:
    """Permanently delete an entity along with all its names.

    Use case: the entity no longer exists in the product (component
    removed, concept retired) and there's no successor to merge into.
    For "this entity is the same as that one", use `merge_entities`
    instead so statements migrate.

    Cascade statement:
    - Every `name` attached to this entity is deleted.
    - `statement_mentions` referencing any of those names are removed.
    - `entity_links` from or to this entity are removed.
    - The entity record is dropped.

    Returns counts of cascaded rows so the caller can sanity-check the
    blast radius. Permanent. Raises ValueError on unknown id.
    """
    assert _conn is not None
    if store.get_entity_by_id(_conn, id) is None:
        raise ValueError(f"entity {id!r} does not exist")

    name_rows = store.get_names_by_entity(_conn, id)
    name_ids = [r["id"] for r in name_rows]
    affected: list[str] = []
    mentions_removed = 0
    for nid in name_ids:
        # Statements that mentioned this entity may now match a name they
        # were shadowing (e.g. "data" surfacing once "data science" is gone).
        affected.extend(store.statements_mentioning_name(_conn, nid))
        mentions_removed += _conn.execute(
            "DELETE FROM statement_mentions WHERE name_id = ?", (nid,)
        ).rowcount
        _conn.execute("DELETE FROM pending_mentions WHERE name_id = ?", (nid,))
        _conn.execute("DELETE FROM annotation_mentions WHERE name_id = ?", (nid,))
        _drop_name_from_index(nid)
    if name_ids:
        # Break generated-plural self-references within this entity before
        # the bulk delete (generated_from_name_id REFERENCES names(id)).
        _conn.executemany(
            "UPDATE names SET generated_from_name_id = NULL WHERE id = ?",
            [(nid,) for nid in name_ids],
        )
        _conn.executemany(
            "DELETE FROM names WHERE id = ?", [(nid,) for nid in name_ids]
        )
    outgoing_entity_links_removed = _conn.execute(
        "DELETE FROM entity_links WHERE from_entity_id = ?", (id,)
    ).rowcount
    incoming_entity_links_removed = _conn.execute(
        "DELETE FROM entity_links WHERE to_entity_id = ?", (id,)
    ).rowcount
    # Mixed entity↔statement edges touching this entity must also go;
    # the cascade trigger on entity_statement_links cleans up their
    # when_nodes rows.
    entity_statement_links_removed = _conn.execute(
        "DELETE FROM entity_statement_links WHERE entity_id = ?", (id,)
    ).rowcount
    store.clear_entity_annotations(_conn, id)
    store.delete_entity(_conn, id)
    store.enqueue_recompute_statements(_conn, affected)
    layout_baker.schedule_rebake()
    return {
        "deleted": True,
        "names_removed": len(name_ids),
        "mentions_removed": mentions_removed,
        "outgoing_entity_links_removed": outgoing_entity_links_removed,
        "incoming_entity_links_removed": incoming_entity_links_removed,
        "entity_statement_links_removed": entity_statement_links_removed,
    }


@tool
def merge_statements(from_id: str, into_id: str) -> dict[str, Any]:
    """Merge one Statement into another and delete the source.

    Use case: you discover two statements are saying the same fact under
    different wordings (or via parallel drafts) and want a single
    canonical record. After the merge, every link or mention that
    pointed at the source now points at the target instead, and the
    source is gone.

    Specifically:
    - `mentions` are derived from text, so the target keeps its own
      (its text is unchanged) and the source's are discarded with the
      source — `mentions_moved` is always 0.
    - Outgoing `links` (the source's own outgoing edges) are unioned
      onto the target, deduped on `(to_statement_id, link_type)`.
      Self-loops created by the merge — e.g. an edge `from → into`
      that would become `into → into` — are silently dropped.
    - Incoming links (other statements that pointed at `from`) are
      rewritten to point at `into`, with the same dedup and self-loop
      drop logic.
    - The source's vector is marked deleted in hnswlib so it stops
      surfacing in `search_statements`.
    - The source's record and vector_id mapping are deleted.

    The target's `text` is unchanged. If the surviving wording should
    be synthesised across both, call `upsert_statement(id=into, text=…)`
    afterwards.

    Use `merge_statements` when the source's meaning lives on through the
    target — duplicate facts under different wording, parallel drafts,
    "this was wrong, replaced by X." For statements that should simply
    cease to exist (feature removed, fact obsolete, no replacement), use
    `delete_statement(id)` instead.

    Returns counts: `{into_id, mentions_moved,
    outgoing_links_moved, incoming_links_moved}`. The "moved" counts
    reflect rows actually inserted onto the target — duplicates and
    self-loops are excluded.

    No-op when `from_id == into_id`. Raises
    ValueError if either id does not exist.
    """
    assert _conn is not None and _index is not None

    if from_id == into_id:
        return {
            "into_id": into_id,
            "mentions_moved": 0,
            "outgoing_links_moved": 0,
            "incoming_links_moved": 0,
        }

    if store.get_statement(_conn, from_id) is None:
        raise ValueError(f"statement {from_id!r} does not exist")
    if store.get_statement(_conn, into_id) is None:
        raise ValueError(f"statement {into_id!r} does not exist")

    # Mentions are derived from text: the target keeps its own (text
    # unchanged) and the source's derived rows are cleared so the source
    # can be deleted under FK enforcement. Nothing is moved.
    mentions_moved = 0
    store.clear_derived_for_statement(_conn, from_id)
    outgoing_moved = store.merge_outgoing_links_into(_conn, from_id, into_id)
    incoming_moved = store.merge_incoming_links_into(_conn, from_id, into_id)
    # Any remaining links that referenced the source as a `when` condition
    # need their reference rewritten to the target before deleting the
    # source, otherwise FK enforcement blocks the delete. Both link kinds
    # are handled — statement_links and entity_statement_links.
    store.rewrite_when_references(_conn, from_id, into_id)
    store.rewrite_entity_statement_when_references(_conn, from_id, into_id)
    # Entity↔statement edges whose endpoint is the source statement
    # need to move onto the target. Use INSERT OR IGNORE through delete
    # + re-insert via the existing store helpers — but cheaper to UPDATE
    # in place with collision detection.
    _conn.execute(
        "UPDATE OR IGNORE entity_statement_links SET statement_id = ? "
        "WHERE statement_id = ?",
        (into_id, from_id),
    )
    # Any rows that hit a UNIQUE collision under OR IGNORE remain
    # pointing at the source; drop them so the source can be deleted.
    _conn.execute(
        "DELETE FROM entity_statement_links WHERE statement_id = ?",
        (from_id,),
    )
    store.merge_statement_annotation_attachments(_conn, from_id, into_id)

    vector_id = store.get_vector_id(_conn, from_id)
    if vector_id is not None:
        _index.delete(vector_id)
    store.delete_statement(_conn, from_id)
    _persist_index()

    return {
        "into_id": into_id,
        "mentions_moved": mentions_moved,
        "outgoing_links_moved": outgoing_moved,
        "incoming_links_moved": incoming_moved,
    }


@tool
def delete_statement(id: str) -> dict[str, Any]:
    """Permanently delete a statement with no replacement.

    Use case: the fact no longer applies — feature removed from the
    product, claim obsolete, statement was authored against a flow that
    has since been deleted — and there is no other statement the meaning
    should flow into. For "this is a duplicate of X" or "this was
    wrong, replaced by Y", use `merge_statements` instead so the
    relationships survive on the target.

    Cascade statement. The substrate cleans up dependent rows so
    deletion can't leave dangling references:

    - `mentions` of this statement are removed.
    - Incoming links (other statements → this) are removed — they no
      longer have a target and aren't meaningful in isolation.
    - Outgoing links (this → other statements) are removed.
    - Any edge anywhere in the graph whose `when` tree referenced this
      statement as a leaf is removed — the conditional relationship
      can't hold once one of its leaves is gone. If you intend the
      condition to live on under a different identity, `merge_statements`
      first to rewrite the references onto the target, then delete (or
      just merge — that already removes the source).
    - The vector slot is marked deleted in hnswlib; subsequent inserts
      reuse it.
    - The statement record and its `vector_id` mapping are dropped.

    Returns `{deleted: True, mentions_removed,
    incoming_links_removed, outgoing_links_removed,
    when_references_removed}` — counts of cascaded rows so the caller
    can sanity-check the blast radius.

    Permanent. Raises ValueError on unknown id.
    """
    assert _conn is not None and _index is not None

    if store.get_statement(_conn, id) is None:
        raise ValueError(f"statement {id!r} does not exist")

    # Order matters under FK enforcement: drop everything that points
    # AT this statement before dropping the statement itself. Outgoing
    # before incoming so a self-loop is counted exactly once.
    outgoing_removed = _conn.execute(
        "DELETE FROM statement_links WHERE from_statement_id = ?", (id,)
    ).rowcount
    incoming_removed = _conn.execute(
        "DELETE FROM statement_links WHERE to_statement_id = ?", (id,)
    ).rowcount
    # Conditional links whose when-tree references this statement become
    # orphaned conditions on deletion — drop them. Indexed lookup via
    # when_nodes(statement_id), then delete each link by id (when_nodes
    # cascades via trigger).
    referencing = store.links_referencing_statement(_conn, id)
    when_removed = 0
    for lid in referencing:
        when_removed += _conn.execute(
            "DELETE FROM statement_links WHERE link_id = ?", (lid,)
        ).rowcount
    # Entity↔statement edges that touch this statement, as endpoint or
    # as `when` leaf, must also go before the row can be deleted (FK to
    # statements(id) blocks otherwise).
    es_endpoint_removed = _conn.execute(
        "DELETE FROM entity_statement_links WHERE statement_id = ?", (id,)
    ).rowcount
    es_referencing = store.links_referencing_statement(
        _conn, id, link_kind="entity_statement"
    )
    es_when_removed = 0
    for lid in es_referencing:
        es_when_removed += _conn.execute(
            "DELETE FROM entity_statement_links WHERE link_id = ?", (lid,)
        ).rowcount
    mentions_removed = store.clear_derived_for_statement(_conn, id, commit=False)
    store.clear_statement_annotations(_conn, id)
    _conn.commit()

    vector_id = store.get_vector_id(_conn, id)
    if vector_id is not None:
        _index.delete(vector_id)
    store.delete_statement(_conn, id)
    _persist_index()

    return {
        "deleted": True,
        "mentions_removed": mentions_removed,
        "incoming_links_removed": incoming_removed,
        "outgoing_links_removed": outgoing_removed,
        "when_references_removed": when_removed,
        "entity_statement_links_removed": (es_endpoint_removed + es_when_removed),
    }


def _id_kind(id: str) -> str:
    """Classify an endpoint id by its prefix. Used by `add_links` /
    `remove_links` to route to the right link table."""
    if id.startswith("stm_"):
        return "statement"
    if id.startswith("ent_"):
        return "entity"
    raise ValueError(
        f"id {id!r} is not recognized as a statement (stm_…) or entity (ent_…)"
    )


def _split_edges(
    links: list[EdgeSpec],
) -> tuple[
    list[tuple[str, str, str, dict[str, Any] | None]],
    list[tuple[str, str, str, str, dict[str, Any] | None]],
]:
    """Partition `links` into statement↔statement and entity↔statement
    tuples. Raises ValueError on entity↔entity edges (those belong on
    `add_entity_links`) and on unknown id prefixes."""
    stmt_edges: list[tuple[str, str, str, dict[str, Any] | None]] = []
    es_edges: list[tuple[str, str, str, str, dict[str, Any] | None]] = []
    for l in links:
        fk = _id_kind(l["from_id"])
        tk = _id_kind(l["to_id"])
        when = l.get("when")
        if fk == "statement" and tk == "statement":
            stmt_edges.append((l["from_id"], l["to_id"], l["link_type"], when))
        elif fk == "entity" and tk == "statement":
            es_edges.append((l["from_id"], l["to_id"], "es", l["link_type"], when))
        elif fk == "statement" and tk == "entity":
            es_edges.append((l["to_id"], l["from_id"], "se", l["link_type"], when))
        else:  # entity → entity
            raise ValueError(
                f"entity↔entity edge {l['from_id']!r} → {l['to_id']!r} is not "
                "supported by add_links/remove_links; use add_entity_links instead"
            )
    return stmt_edges, es_edges


@tool
def add_links(links: list[EdgeSpec]) -> dict[str, int]:
    """Insert one or more typed edges. Endpoints may be statements
    (`stm_…`) or entities (`ent_…`) in any combination except
    entity↔entity (use `add_entity_links` for those).

    Direction note: source is the bigger/earlier/wrapping/primary side;
    target is the smaller/later/contained/dependent side. Before
    committing an edge, read it aloud as "FROM <link_type> TO" and check
    it against the link type's description. For constrained statement
    link types, provably flipped edges detected by statement kind are
    rejected; e.g. `teaches` is `procedure -> capability`, so
    `capability -> procedure` fails and should be swapped.

    Idempotent — pre-existing edges (matched on the canonical
    `(from, to, link_type, when_hash)`) are silently skipped, so the
    count returned can be smaller than the number of `links` you
    passed. Validates that every `from_id`, `to_id`, and every
    `statement_id` leaf inside any `when` tree exists before mutating;
    raises ValueError on any unknown id. `when` leaves are always
    statement ids (an entity has no notion of "holding") — same grammar
    as statement-link `when` expressions.

    No re-embedding is performed — this is the cheap path for adding
    relationships between existing nodes. To add a single edge, pass a
    one-element list.
    """
    assert _conn is not None
    if not links:
        return {"inserted": 0}

    stmt_edges, es_edges = _split_edges(links)

    # Validate every referenced id exists across both kinds.
    needed_statements: set[str] = set()
    needed_entities: set[str] = set()
    for l in links:
        for endpoint in (l["from_id"], l["to_id"]):
            if _id_kind(endpoint) == "statement":
                needed_statements.add(endpoint)
            else:
                needed_entities.add(endpoint)
        if "when" in l:
            when_expression.validate(l["when"])
            needed_statements.update(when_expression.leaves(l["when"]))
    statement_rows: dict[str, sqlite3.Row] = {}
    for sid in needed_statements:
        row = store.get_statement(_conn, sid)
        if row is None:
            raise ValueError(f"statement {sid!r} does not exist")
        statement_rows[sid] = row
    for eid in needed_entities:
        if store.get_entity_by_id(_conn, eid) is None:
            raise ValueError(f"entity {eid!r} does not exist")

    flip_errors: list[str] = []
    for i, l in enumerate(links):
        if _id_kind(l["from_id"]) != "statement" or _id_kind(l["to_id"]) != "statement":
            continue
        from_kind = statement_rows[l["from_id"]]["kind"]
        to_kind = statement_rows[l["to_id"]]["kind"]
        err = _format_flip_error(
            position=f"links[{i}]",
            from_id=l["from_id"],
            to_id=l["to_id"],
            link_type=l["link_type"],
            from_kind=from_kind,
            to_kind=to_kind,
        )
        if err is not None:
            flip_errors.append(err)
    if flip_errors:
        raise ValueError("flipped link direction:\n" + "\n".join(flip_errors))

    inserted = 0
    if stmt_edges:
        inserted += store.insert_links(_conn, stmt_edges)
    if es_edges:
        inserted += store.insert_entity_statement_links(_conn, es_edges)
    if es_edges:
        layout_baker.schedule_rebake()
    return {"inserted": inserted}


@tool
def remove_links(links: list[EdgeSpec]) -> dict[str, int]:
    """Remove one or more typed edges. Endpoints may be statements
    (`stm_…`) or entities (`ent_…`) in any combination except
    entity↔entity (use `remove_entity_links` for those).

    Match is by canonicalized when expression — the literal shape sent
    here doesn't have to match what was originally sent to `add_links`,
    only the canonical form does (e.g. `(A AND B)` and `(B AND A)` are
    the same edge). Returns the count of rows actually deleted; missing
    edges are silently skipped (so this is idempotent — calling it
    twice with the same input is fine). Does not validate that the
    endpoints exist; deleting an edge that references a non-existent
    node is just a no-op.
    """
    assert _conn is not None
    if not links:
        return {"removed": 0}

    stmt_edges, es_edges = _split_edges(links)

    removed = 0
    if stmt_edges:
        removed += store.delete_links(_conn, stmt_edges)
    if es_edges:
        removed += store.delete_entity_statement_links(_conn, es_edges)
    if es_edges:
        layout_baker.schedule_rebake()
    return {"removed": removed}


@tool
def get_statements(ids: list[str]) -> dict[str, Any]:
    """Fetch one or more statements by id, each hydrated with mentions,
    both link directions, and reverse `when` references.

    `ids` is a list — pass `[id]` for a single lookup, or batch many ids
    in one call when walking a graph. Order is preserved. Duplicates in
    `ids` produce duplicate entries in the result.

    Returns `{statements: [{id, kind, text, mentions, links,
    incoming_links, when_references}, ...]}`. `mentions` is `[{name_id,
    name, entity_id}]`. `links` is the outgoing edges this statement
    owns; `incoming_links` is `[{from_id, link_type}]` listing every
    node that points at this one. Endpoint values (`to_id` on `links`,
    `from_id` on `incoming_links`) may be statement ids (`stm_…`) or
    entity ids (`ent_…`) — the substrate doesn't surface a separate
    flavor for entity-endpoint edges.

    `when_references` is `[{from_id, to_id, link_type, when}]` —
    every edge in the graph (statement↔statement or entity↔statement)
    whose `when` condition mentions THIS statement as a leaf. Use it
    to answer "what does this state gate?" Condition states often
    have no outgoing links of their own (intentionally — see authoring
    §9); `when_references` is how you trace forward from them anyway.

    The natural follow-up to a `search_statements` hit (or any opaque
    ids you got from links — `links[].to_id`,
    `incoming_links[].from_id`, or a `when` reference).
    **Batch the hop**: if a hit has multiple outgoing links you want to
    follow, hydrate them all in one `get_statements` call rather than
    looping. To trace a causal chain, alternate: search once, then
    `get_statements` each frontier. This is cleaner than
    `search_statements(depth=2+)`, which mixes direct hits with a flat
    blob of expanded nodes and pulls in noise through convergence hubs.

    `link_type` strings on `links` / `incoming_links` (e.g. `configures`,
    `varies-by`, `establishes`, `proceeds`) have specific semantics — call
    `list_link_types()` for the glossary if unsure. Links may also carry
    a `when` condition (a tree of `{op: "and"/"or"/"not", of: [...]}`
    and `{statement_id: ...}` leaves) that gates when the edge fires;
    `list_link_types()` also documents that grammar.

    Raises ValueError if `ids` is empty or if any id does not exist (no
    partial results — fix the input and retry).
    """
    assert _conn is not None
    if not ids:
        raise ValueError("ids must be a non-empty list")
    missing = [i for i in ids if store.get_statement(_conn, i) is None]
    if missing:
        raise ValueError(f"statement(s) not found: {missing!r}")
    # Uncapped reverse edges: get_statements is an explicit, targeted fetch, so
    # it returns the complete neighborhood (search/survey cap it — see
    # `_hydrate_statement_full`).
    statements = [_hydrate_statement_full(sid, score=None) for sid in ids]
    return {"statements": statements}


@tool
def get_entity(id: str) -> dict[str, Any]:
    """Fetch one entity by its id, hydrated with names and every kind
    of link this entity participates in.

    Returns `{id, description, names, links, incoming_links,
    statement_links, incoming_statement_links}`:

    - `names` is `[{id, text}]` sorted alphabetically.
    - `links` / `incoming_links` are the entity↔entity edges
      (`[{to_entity_id|from_entity_id, link_type}]`). Separate
      vocabulary from statement links; see `list_entity_link_types`.
    - `statement_links` / `incoming_statement_links` are mixed
      entity↔statement edges (`[{to_id|from_id, link_type, when?}]`).
      They share the statement link-type vocabulary and `when` grammar
      with `add_links` / `remove_links`.

    Use `search_statements` with the `mentions` filter to find
    statements that mention this entity by name.

    Raises ValueError if `id` does not exist.
    """
    assert _conn is not None
    row = store.get_entity_by_id(_conn, id)
    if row is None:
        raise ValueError(f"entity {id!r} does not exist")
    outgoing = store.get_entity_links_outgoing(_conn, id)
    incoming = store.get_entity_links_incoming(_conn, id)
    es_outgoing, es_incoming = store.get_entity_statement_links_for_entity(_conn, id)
    return {
        "id": row["id"],
        "description": row["description"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "names": [
            {"id": n["id"], "text": n["text"]}
            for n in store.get_names_by_entity(_conn, id)
        ],
        "links": [{"to_entity_id": to_id, "link_type": lt} for (to_id, lt) in outgoing],
        "incoming_links": [
            {"from_entity_id": from_id, "link_type": lt} for (from_id, lt) in incoming
        ],
        # Mixed entity↔statement edges. Separate from `links` /
        # `incoming_links` (which carry the entity↔entity vocabulary
        # and lack `when` semantics) because the systems are distinct.
        "statement_links": [
            _link_dict(to_id=stmt_id, link_type=lt, when=when)
            for stmt_id, lt, when in es_outgoing
        ],
        "incoming_statement_links": [
            _link_dict(from_id=stmt_id, link_type=lt, when=when)
            for stmt_id, lt, when in es_incoming
        ],
    }


@tool
def list_entities(
    prefix: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Page through entities, sorted by their alphabetically-first name.

    Optional `prefix` does a case-insensitive prefix match on the
    entity's primary name (alphabetically first attached name); pass
    empty string for no filter. Returns `{total, entities: [{id, name,
    description}]}` where `total` is the total count (unfiltered) so a
    caller can drive pagination.

    `name` is the entity's alphabetically-first attached name, or the
    entity_id as a fallback if it has no names. To enumerate all aliases
    of one entity, use `get_entity(id)`.
    """
    assert _conn is not None
    rows = store.list_entities(_conn, prefix=prefix or None, limit=limit, offset=offset)
    return {
        "total": store.count_entities(_conn),
        "entities": [
            {
                "id": r["id"],
                "name": r["primary_name"] or r["id"],
                "description": r["description"] or "",
            }
            for r in rows
        ],
    }


@tool
def list_statements(
    limit: int = 50,
    offset: int = 0,
    entity_id: str | None = None,
    name: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Page through statements in insertion order.

    Without filters, returns every statement. With `entity_id` or `name`,
    restricts to statements that mention that entity. A `name` is
    resolved to whichever entity it points at, so all aliases of the
    same entity collapse into one filter — passing `"Login"` and
    passing `"sign-in"` (an alias of the same entity) yield the same
    set. Pass at most one of `entity_id` / `name`; both raises
    ValueError. Unknown name or unknown entity_id also raises.

    `kind` ("event" / "state" / "capability") restricts to statements
    of that kind. Combines with the entity filter under AND.

    Returns `{total, statements: [{id, kind, text}]}` — text only, with
    no mentions or links to keep the response light. To inspect a
    single statement's full structure use `get_statements([id])`.
    """
    assert _conn is not None
    if entity_id is not None and name is not None:
        raise ValueError("pass at most one of entity_id / name, not both")
    if name is not None:
        row = store.get_name_by_text(_conn, name)
        if row is None:
            raise ValueError(f"name not found: {name!r}")
        entity_id = row["entity_id"]
    if entity_id is not None and store.get_entity_by_id(_conn, entity_id) is None:
        raise ValueError(f"entity not found: {entity_id!r}")
    rows = store.list_statements(
        _conn, limit=limit, offset=offset, entity_id=entity_id, kind=kind
    )
    return {
        "total": store.count_statements(_conn, entity_id=entity_id, kind=kind),
        "statements": [
            {"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows
        ],
    }


@tool
def find_duplicates(
    threshold: float = 0.92,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Audit the whole substrate for near-duplicate statement pairs.

    Walks every statement, queries the vector index for its closest
    neighbours, and returns pairs with cosine similarity at or above
    `threshold`. Sorted by score descending, capped at `limit`. Pairs
    are reported once (not as both `(A,B)` and `(B,A)`).

    The default `0.92` is the high-confidence band — paired statements
    are almost certainly the same fact in different wording. Drop to
    `0.85` to also surface "related, possibly worth linking instead of
    keeping separate" pairs at the cost of more noise. The write-time
    `near_duplicates` field on `upsert_statement` uses 0.85 as a soft
    write-time signal; this tool is the periodic backfill audit.

    Each pair: `{a_id, a_text, b_id, b_text, score}`. Use
    `merge_statements(from, into)` to consolidate, or `replace_text` /
    `add_links` if the duplication is structural rather than textual.
    """
    assert _conn is not None and _index is not None

    seen_pairs: set[tuple[str, str]] = set()
    pairs: list[dict[str, Any]] = []

    for row in _conn.execute("SELECT id FROM statements").fetchall():
        bid = row["id"]
        vid = store.get_vector_id(_conn, bid)
        if vid is None:
            continue
        vec = _index.get_vector(vid)
        if vec is None:
            # Slot is stranded — SQLite mapping points at an id the
            # hnsw file doesn't have. Skip rather than crash the audit.
            continue
        # k=20 is a balance between catching all candidates and per-call
        # cost. At MVP scales this comfortably covers any cluster of
        # near-duplicates.
        hits = _index.search(vec, k=20)
        for other_vid, distance in hits:
            if other_vid == vid:
                continue
            score = 1.0 - distance
            if score < threshold:
                continue
            other_bid = store.get_statement_id_by_vector_id(_conn, other_vid)
            if other_bid is None:
                continue
            key = (bid, other_bid) if bid < other_bid else (other_bid, bid)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            a_row = store.get_statement(_conn, key[0])
            b_row = store.get_statement(_conn, key[1])
            if a_row is None or b_row is None:
                continue
            pairs.append(
                {
                    "a_id": key[0],
                    "a_text": a_row["text"],
                    "b_id": key[1],
                    "b_text": b_row["text"],
                    "score": score,
                }
            )

    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs[:limit]


@tool
def discover_facts(
    texts: list[str],
    exists_threshold: float = 0.85,
    near_threshold: float = 0.6,
    matches_per_text: int = 5,
) -> list[dict[str, Any]]:
    """Bulk discovery for many candidate facts at once.

    Two uses, same call:
    - Pre-write: before authoring new statements, check which already
      exist under different wording.
    - Audit / coverage check: given a list of claims (e.g. extracted from
      a doc), find out which the substrate confirms, which are near-misses
      worth a closer look, and which are absent. Faster and more honest
      than running `search_statements` per claim — one call, structured
      verdicts.

    For each input text, embeds it, queries the vector index, and
    classifies the closest existing statement into one of three buckets:

    - `"exists"`: top match score >= `exists_threshold` (default 0.85).
      The substrate already has this fact under different wording. Don't
      write a new statement; either link to it, refine it via
      `upsert_statement(id=…)`, or merge afterwards if you wrote
      anyway.
    - `"near"`: top match score is between `near_threshold` and
      `exists_threshold`. Related facts exist; the new statement is
      likely distinct but probably should `link` to one or more of the
      matches instead of standing alone.
    - `"new"`: nothing within `near_threshold`. Safe to write fresh.

    Replaces the per-fact loop of sequential `search_statements` calls
    that the discovery phase otherwise prescribes. Pass every text you
    intend to write in one go; the response gives you a per-text
    decision plus the supporting matches.

    Each result: `{text, status, matches: [{id, text, score}]}`.
    `matches` is capped at `matches_per_text` (default 5) and includes
    every hit at or above `near_threshold`, sorted by score descending
    — so `"new"` results carry an empty `matches` list. `text` snippets
    are truncated to keep batch responses lean; follow up with
    `get_statements(ids)` for full text.

    Cheap-ish: one embed + one vector search per input text. No SQL
    writes.
    """
    assert _index is not None and _conn is not None

    if exists_threshold < near_threshold:
        raise ValueError(
            "exists_threshold must be >= near_threshold "
            f"(got {exists_threshold} < {near_threshold})"
        )

    out: list[dict[str, Any]] = []
    for text in texts:
        vec = embed.embed(text)
        hits = _index.search(vec, k=matches_per_text)

        matches: list[dict[str, Any]] = []
        for vid, distance in hits:
            score = 1.0 - distance
            if score < near_threshold:
                continue
            bid = store.get_statement_id_by_vector_id(_conn, vid)
            if bid is None:
                continue
            row = store.get_statement(_conn, bid)
            if row is None:
                continue
            matches.append({"id": bid, "text": _snippet(row["text"]), "score": score})

        if matches and matches[0]["score"] >= exists_threshold:
            status = "exists"
        elif matches:
            status = "near"
        else:
            status = "new"

        out.append({"text": text, "status": status, "matches": matches})

    return out


@tool
def list_link_types() -> list[dict[str, Any]]:
    """List the statement→statement link types known to the substrate.

    Returns `[{link_type, description, usage_count, direction?}]` sorted
    alphabetically. `description` comes from the
    `statement_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_link_type`); empty string for any type that's
    in the database but has no glossary entry. `usage_count` is the
    number of statement_links rows currently carrying this type — 0
    means the type is defined but not yet used anywhere.

    Reach for this whenever a `get_statements` or `search_statements`
    response shows a `link_type` you're not sure about. Vocabulary is
    open — new types may appear in `in_use` results without a glossary
    entry. Reuse before inventing.

    ─── `when` expressions on edges ──────────────────────────────────
    A link may carry a `when` field that conditions whether the edge
    fires. The grammar is a small tree:

      leaf      = {"statement_id": "stm_…"}
      internal  = {"op": "and", "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "or",  "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "not", "of": [<expr>]}               # exactly 1 child

    A leaf is satisfied when the referenced statement (a `state`-kind
    statement, by convention) currently holds. `and`/`or` combine
    children boolean-fashion; `not` inverts its single child — the edge
    fires when that child does NOT hold. Absence of a `when` field means
    the edge is unconditional — it fires whenever the source fires.

    Example — a rejection trigger that only fires when both a template
    is configured AND the outgoing edge conditions failed:

      {"op": "and", "of": [
        {"statement_id": "stm_template_configured"},
        {"statement_id": "stm_edge_conditions_failed"}
      ]}

    Example — a sharing guard that fires only when the result has NOT
    already been shared:

      {"op": "not", "of": [{"statement_id": "stm_result_already_shared"}]}

    To follow what a `when` leaf refers to, call `get_statements([id])` on
    the leaf's `statement_id` — same pattern as chasing a link target.
    """
    assert _conn is not None
    counts = store.count_statement_links_by_type(_conn)
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_statement_link_type_glossary(_conn)
    }
    all_types = sorted(set(counts) | set(glossary))
    rows: list[dict[str, Any]] = []
    for t in all_types:
        row: dict[str, Any] = {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        direction = _direction_entry(t)
        if direction is not None:
            row["direction"] = direction
        rows.append(row)
    return rows


class EntityEdgeSpec(TypedDict):
    from_entity_id: str
    to_entity_id: str
    link_type: str


@tool
def add_entity_links(links: list[EntityEdgeSpec]) -> dict[str, int]:
    """Bulk-insert directed entity→entity edges.

    Use case: structural relationships between long-lived entities — a
    parent corporation `contains` its subsidiaries, a product is a
    `kind-of` something more abstract, two providers `replace` each
    other, etc. These are distinct from statement→statement links
    (`add_links`), which connect atomic facts; entity_links connect
    the hubs that statements mention.

    Each link is `{from_entity_id, to_entity_id, link_type}`. The
    `link_type` vocabulary is open — any string is valid; reuse what
    `list_entity_link_types()` already shows in use before inventing.

    Self-loops (`from == to`) are rejected. Pre-existing edges (matched
    on the triple) are silently skipped via INSERT OR IGNORE, so the
    returned `inserted` count can be less than `len(links)`.

    Validates every referenced entity id exists before any mutation;
    if any reference is unknown the call raises ValueError and inserts
    nothing.
    """
    assert _conn is not None
    if not links:
        return {"inserted": 0}
    needed: set[str] = set()
    for link in links:
        if link["from_entity_id"] == link["to_entity_id"]:
            raise ValueError(
                f"self-loop entity link: {link['from_entity_id']!r} → itself"
            )
        needed.add(link["from_entity_id"])
        needed.add(link["to_entity_id"])
    for eid in needed:
        if store.get_entity_by_id(_conn, eid) is None:
            raise ValueError(f"entity {eid!r} does not exist")
    edges = [(l["from_entity_id"], l["to_entity_id"], l["link_type"]) for l in links]
    inserted = store.insert_entity_links(_conn, edges)
    if inserted:
        layout_baker.schedule_rebake()
    return {"inserted": inserted}


@tool
def remove_entity_links(links: list[EntityEdgeSpec]) -> dict[str, int]:
    """Bulk-delete directed entity→entity edges.

    Each link is `{from_entity_id, to_entity_id, link_type}` and must
    match an existing edge exactly. Missing edges are a no-op (idempotent
    — calling twice with the same input is fine). Returns the count of
    rows actually deleted. Does not validate that referenced entities
    exist; deleting an edge that references a non-existent entity simply
    removes nothing.
    """
    assert _conn is not None
    if not links:
        return {"removed": 0}
    edges = [(l["from_entity_id"], l["to_entity_id"], l["link_type"]) for l in links]
    removed = store.delete_entity_links(_conn, edges)
    if removed:
        layout_baker.schedule_rebake()
    return {"removed": removed}


@tool
def list_statement_kinds() -> list[dict[str, Any]]:
    """List the statement `kind` values known to the substrate.

    Returns `[{kind, description, when_to_use, usage_count}]` sorted
    alphabetically. `description` and `when_to_use` come from the
    `statement_kind_glossary` table (DB-backed, editable via the
    website or `upsert_statement_kind`); empty strings for kinds
    present on statements but missing from the glossary. `usage_count`
    is the number of statements currently carrying that kind — 0
    means the kind is defined but not yet used.

    Use this when you need to know what shape of claim to write —
    each `kind` enforces a different phrasing catalog at the
    substrate boundary (event / state / capability / rule / property
    for descriptive content; procedure / action / check / cause for
    prescriptive how-to and diagnostic content). Vocabulary is open
    — new kinds run the event phrasing catalog as a baseline.
    """
    assert _conn is not None
    glossary_rows = store.list_statement_kind_glossary(_conn)
    glossary = {
        r["kind"]: (r["description"], r["when_to_use"] or "") for r in glossary_rows
    }
    counts = store.count_statements_by_kind_all(_conn)
    all_kinds = sorted(set(counts) | set(glossary))
    return [
        {
            "kind": k,
            "description": glossary.get(k, ("", ""))[0],
            "when_to_use": glossary.get(k, ("", ""))[1],
            "usage_count": counts.get(k, 0),
        }
        for k in all_kinds
    ]


@tool
def list_entity_link_types() -> list[dict[str, Any]]:
    """List entity→entity link types known to the substrate.

    Returns `[{link_type, description, usage_count}]` sorted
    alphabetically. `description` comes from the
    `entity_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_entity_link_type`). `usage_count` is the number
    of entity_links rows currently carrying this type.
    """
    assert _conn is not None
    counts = store.count_entity_links_by_type(_conn)
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_entity_link_type_glossary(_conn)
    }
    all_types = sorted(set(counts) | set(glossary))
    return [
        {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        for t in all_types
    ]


@tool
def upsert_statement_kind(
    kind: str, description: str, when_to_use: str | None = None
) -> dict[str, str]:
    """Create or update a statement-kind glossary entry.

    The `kind` value is the primary key — pass the same `kind` to
    update an existing entry's `description` / `when_to_use`. Pass a
    new `kind` to add a new entry. Authoring this entry does NOT
    register the kind for phrasing validation — phrasing rules live in
    `phrasing.py` and apply by name; an entry here is documentation,
    not enforcement.

    Returns `{kind}` on success.
    """
    assert _conn is not None
    if not kind or not kind.strip():
        raise ValueError("kind cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    store.upsert_statement_kind_glossary(_conn, kind, description, when_to_use)
    return {"kind": kind}


@tool
def delete_statement_kind(kind: str) -> dict[str, str]:
    """Remove a statement-kind glossary entry.

    Does not affect any statement records that currently carry this
    kind — they remain valid in the substrate; only the glossary
    documentation goes away. Idempotent: deleting a missing entry is
    a no-op.

    Returns `{kind}`.
    """
    assert _conn is not None
    store.delete_statement_kind_glossary(_conn, kind)
    return {"kind": kind}


@tool
def upsert_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update a statement→statement link-type glossary entry.

    The `link_type` value is the primary key. Authoring this entry
    does NOT register the type for any validation; it is documentation
    that surfaces via `list_link_types`.

    Returns `{link_type}`.
    """
    assert _conn is not None
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    store.upsert_statement_link_type_glossary(_conn, link_type, description)
    return {"link_type": link_type}


@tool
def delete_link_type(link_type: str) -> dict[str, str]:
    """Remove a statement→statement link-type glossary entry.

    Does not affect any link rows that currently carry this type —
    they remain valid in the substrate; only the documentation goes
    away. Idempotent.

    Returns `{link_type}`.
    """
    assert _conn is not None
    store.delete_statement_link_type_glossary(_conn, link_type)
    return {"link_type": link_type}


@tool
def upsert_entity_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update an entity→entity link-type glossary entry.

    The `link_type` value is the primary key. Entity link types live
    in a separate namespace from statement link types.

    Returns `{link_type}`.
    """
    assert _conn is not None
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    store.upsert_entity_link_type_glossary(_conn, link_type, description)
    return {"link_type": link_type}


@tool
def delete_entity_link_type(link_type: str) -> dict[str, str]:
    """Remove an entity→entity link-type glossary entry.

    Does not affect any entity_links rows that currently carry this
    type. Idempotent.

    Returns `{link_type}`.
    """
    assert _conn is not None
    store.delete_entity_link_type_glossary(_conn, link_type)
    return {"link_type": link_type}


def _annotation_near_duplicates(
    vec: list[float],
    *,
    exclude_id: str | None = None,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Same shape as `_near_duplicates` but against the annotations index."""
    assert _ann_index is not None and _conn is not None
    hits = _ann_index.search(vec, k=k + (1 if exclude_id else 0))
    out: list[dict[str, Any]] = []
    for vid, distance in hits:
        aid = store.get_annotation_id_by_vector_id(_conn, vid)
        if aid is None or aid == exclude_id:
            continue
        score = 1.0 - distance
        if score < threshold:
            continue
        row = store.get_annotation(_conn, aid)
        if row is None:
            continue
        out.append(
            {
                "id": aid,
                "kind": row["kind"],
                "text": _snippet(row["text"]),
                "score": score,
            }
        )
        if len(out) >= k:
            break
    return out


def _hydrate_annotation(
    annotation_id: str, score: float | None = None
) -> dict[str, Any]:
    """Full hydrated annotation: id, kind, text, mentions, attached
    statements AND entities (an annotation can attach to either layer)."""
    assert _conn is not None
    row = store.get_annotation(_conn, annotation_id)
    assert row is not None
    mentions = [
        {"name_id": m["name_id"], "name": m["name"], "entity_id": m["entity_id"]}
        for m in store.get_annotation_mentions(_conn, annotation_id)
    ]
    statements = [
        {"id": b["id"], "text": _snippet(b["text"])}
        for b in store.get_statements_for_annotation(_conn, annotation_id)
    ]
    entities = [
        {"id": e["id"], "name": e["primary_name"] or e["id"]}
        for e in store.get_entities_for_annotation(_conn, annotation_id)
    ]
    out: dict[str, Any] = {
        "id": row["id"],
        "kind": row["kind"],
        "text": row["text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "mentions": mentions,
        "statements": statements,
        "entities": entities,
    }
    if score is not None:
        out["score"] = score
    return out


def upsert_annotation(
    kind: str,
    text: str,
    statement_ids: list[str] = [],
    entity_ids: list[str] = [],
    mentions: list[str] = [],
    id: str | None = None,
    strict_mentions: bool = False,
) -> dict[str, Any]:
    """Update an existing annotation — a typed, embedded proposition
    attached to one or more statements and/or entities. Creating new
    annotations via this tool is disabled: `id` is required, and calls
    without it raise. Existing annotations can still have their kind,
    text, mentions, and attachment sets reconciled.

    `kind` is the deliberate first-class discriminator for annotations,
    parallel to statement.kind but discriminating by *purpose of note*
    rather than shape of claim. Required on every call; the substrate
    rejects null but does NOT lock the vocabulary — kinds grow as
    needed, same posture as statement kinds and link types. Starting
    vocabulary:
      - `definition` — what something is (concept, term, role).
      - `default`    — the implicit value or behavior when nothing
                       overrides.
      - `example`    — a concrete instance illustrating a statement
                       or entity.
      - `note`       — design rationale, caveat, or other context
                       that doesn't fit a more specific kind.
    Add new leaves freely (`permission`, `invariant`, `property`,
    `compliance`, `rationale`, etc.) as the substrate's vocabulary
    grows. `list_annotation_kinds()` enumerates what's currently in
    use. No grammatical rules apply per kind — annotations
    discriminate by purpose, not phrasing.

    `statement_ids` and `entity_ids` are the FULL sets of statements and
    entities this annotation attaches to. Use statement attachment for
    facts about specific events ("only recruiters can create invites"
    attaches to the create-invite statement); use entity attachment for
    facts about an entity itself irrespective of any single event
    ("the Recruiter role is provisioned by HR" attaches to the
    Recruiter entity). Both are independent — an annotation may attach
    to both layers, either, or neither (orphan).

    On update (with `id`), each attachment set is reconciled wholesale
    — anything missing from the new list is detached. Annotations
    survive deletion of any record they were attached to; orphans are
    only removed by explicit `delete_annotation`, never as a
    side-effect.

    `mentions` works like statement mentions — name texts that
    auto-resolve to entities, with `strict_mentions=True` flipping
    auto-create off in favor of an error on unknown names. (Mentions
    record what the annotation REFERENCES; entity_ids record which
    entities the annotation IS ABOUT.)

    Returns `{annotation_id, near_duplicates}`.
    """
    assert _conn is not None and _ann_index is not None

    for bid in statement_ids:
        if store.get_statement(_conn, bid) is None:
            raise ValueError(f"statement {bid!r} does not exist")
    for eid in entity_ids:
        if store.get_entity_by_id(_conn, eid) is None:
            raise ValueError(f"entity {eid!r} does not exist")

    vec = embed.embed(text)
    name_ids = _resolve_or_create_names(mentions, strict=strict_mentions)

    if id is None:
        raise ValueError(
            "creating new annotations is disabled; pass an existing `id` to update"
        )
    if store.get_annotation(_conn, id) is None:
        raise ValueError(f"annotation {id!r} does not exist")
    store.update_annotation(_conn, id, kind, text)
    vector_id = store.get_annotation_vector_id(_conn, id)
    assert vector_id is not None
    _ann_index.replace(vector_id, vec)
    store.replace_annotation_mentions(_conn, id, name_ids)
    store.replace_annotation_attachments(_conn, id, statement_ids)
    store.replace_annotation_entity_attachments(_conn, id, entity_ids)
    annotation_id = id

    _persist_ann_index()
    return {
        "annotation_id": annotation_id,
        "near_duplicates": _annotation_near_duplicates(vec, exclude_id=annotation_id),
    }


def attach_annotation(
    annotation_id: str,
    statement_id: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Attach an existing annotation to one more statement or entity.

    Pass exactly one of `statement_id` / `entity_id`. Idempotent — an
    existing attachment is silently skipped, so a second call with the
    same args is a no-op (`attached: 0`). Validates that both records
    exist before mutating.
    """
    assert _conn is not None
    if (statement_id is None) == (entity_id is None):
        raise ValueError("pass exactly one of statement_id / entity_id")
    if store.get_annotation(_conn, annotation_id) is None:
        raise ValueError(f"annotation {annotation_id!r} does not exist")
    if statement_id is not None:
        if store.get_statement(_conn, statement_id) is None:
            raise ValueError(f"statement {statement_id!r} does not exist")
        inserted = store.attach_annotations_to_statements(
            _conn, [(statement_id, annotation_id)]
        )
    else:
        assert entity_id is not None
        if store.get_entity_by_id(_conn, entity_id) is None:
            raise ValueError(f"entity {entity_id!r} does not exist")
        inserted = store.attach_annotations_to_entities(
            _conn, [(entity_id, annotation_id)]
        )
    return {"annotation_id": annotation_id, "attached": inserted}


def detach_annotation(
    annotation_id: str,
    statement_id: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Detach an annotation from one statement or entity. Pass exactly
    one of `statement_id` / `entity_id`. The annotation itself is NOT
    deleted — it survives as an orphan if this was its last attachment.
    Use `delete_annotation` for permanent removal.

    Idempotent — a missing attachment is silently skipped.
    """
    assert _conn is not None
    if (statement_id is None) == (entity_id is None):
        raise ValueError("pass exactly one of statement_id / entity_id")
    if statement_id is not None:
        removed = store.detach_annotations_from_statements(
            _conn, [(statement_id, annotation_id)]
        )
    else:
        assert entity_id is not None
        removed = store.detach_annotations_from_entities(
            _conn, [(entity_id, annotation_id)]
        )
    return {"annotation_id": annotation_id, "detached": removed}


def get_annotation(id: str) -> dict[str, Any]:
    """Fetch one annotation by id, hydrated with mentions and the
    statements it's attached to.

    Returns `{id, kind, text, mentions, statements}` where `mentions`
    is `[{name_id, name, entity_id}]` and `statements` is `[{id, text}]`
    with `text` truncated to a snippet. Use `get_statements(ids)` for the
    full record of any attached statement.

    Raises ValueError if `id` does not exist.
    """
    assert _conn is not None
    if store.get_annotation(_conn, id) is None:
        raise ValueError(f"annotation {id!r} does not exist")
    return _hydrate_annotation(id)


def list_annotations(
    statement_id: str | None = None,
    entity_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Page through annotations in insertion order.

    Three filters, combinable with AND:
      `entity_id`    — annotations attached directly to that entity.
                       Use this to enumerate everything attached to an
                       entity — `get_entity(id)` returns the same set
                       inline, but this form paginates and combines
                       with `kind`.
      `statement_id` — annotations attached to that statement.
      `kind`         — annotations of that kind.

    Returns `{total, annotations: [{id, kind, text}]}`. `total`
    reflects the same filter applied to the full table.
    """
    assert _conn is not None
    rows = store.list_annotations(
        _conn,
        statement_id=statement_id,
        entity_id=entity_id,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    return {
        "total": store.count_annotations(
            _conn, statement_id=statement_id, entity_id=entity_id, kind=kind
        ),
        "annotations": [
            {"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows
        ],
    }


def delete_annotation(id: str) -> dict[str, Any]:
    """Permanently delete an annotation.

    Cascade statement: `mentions` of this annotation are removed, every
    `statement_annotations` and `entity_annotations` row pointing at it
    is removed, the vector slot is marked deleted in hnswlib, and the
    record + vector_id mapping are dropped. Statements and entities that
    were attached are unaffected — only the join is severed.

    Returns `{deleted: True, statement_attachments_removed,
    entity_attachments_removed, mentions_removed}`. Permanent.
    Raises ValueError on unknown id.
    """
    assert _conn is not None and _ann_index is not None

    if store.get_annotation(_conn, id) is None:
        raise ValueError(f"annotation {id!r} does not exist")

    statement_attachments_removed = _conn.execute(
        "SELECT COUNT(*) AS n FROM statement_annotations WHERE annotation_id = ?",
        (id,),
    ).fetchone()["n"]
    entity_attachments_removed = _conn.execute(
        "SELECT COUNT(*) AS n FROM entity_annotations WHERE annotation_id = ?",
        (id,),
    ).fetchone()["n"]
    mentions_removed = _conn.execute(
        "SELECT COUNT(*) AS n FROM annotation_mentions WHERE annotation_id = ?",
        (id,),
    ).fetchone()["n"]

    store.clear_annotation_attachments(_conn, id)
    store.clear_annotation_entity_attachments(_conn, id)
    store.clear_annotation_mentions(_conn, id)

    vector_id = store.get_annotation_vector_id(_conn, id)
    if vector_id is not None:
        _ann_index.delete(vector_id)
    store.delete_annotation_record(_conn, id)
    _persist_ann_index()

    return {
        "deleted": True,
        "statement_attachments_removed": statement_attachments_removed,
        "entity_attachments_removed": entity_attachments_removed,
        "mentions_removed": mentions_removed,
    }


@tool
def grep_statements(
    query: str,
    case_sensitive: bool = False,
    entity_id: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    match_aliased_mentions: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Literal substring search over statement `text`, alias-aware.

    Complements `search_statements` (vector / semantic) with deterministic
    case-insensitive substring matching. Reach for grep when you need
    exact phrases, identifiers, quoted strings, or specific tokens that
    semantic search may not surface reliably.

    By default also returns statements that mention an entity whose
    *name* contains the query as a literal substring — so grepping
    `"tree"` surfaces statements about the Selection Flow entity
    (which carries `tree` as an alias) even when the statement text
    says only `"selection flow"`. This mirrors the alias awareness in
    `search_statements`. Each result carries `matched_via`:

      `"text"`    — statement text contains the query.
      `"mention"` — statement mentions an entity whose name contains
                    the query; statement text does not.
      `"both"`    — both of the above.

    Set `match_aliased_mentions=False` to get only text-matches (the
    pre-alias-awareness behavior).

    `query` is matched literally — `%` and `_` are escaped, no glob or
    regex syntax is honored. Pass `case_sensitive=True` for an
    exact-case match. Empty `query` raises ValueError.

    Optional `entity_id` / `name` (mutually exclusive) restricts results
    to statements that mention that entity. When set, alias-mention
    expansion is suppressed — the explicit entity filter already
    specifies the mention scope. Returns `{total, statements: [{id,
    kind, text, matched_via}]}`. Use `get_statements(ids)` for full
    mentions and links.
    """
    assert _conn is not None
    if not query:
        raise ValueError("query must be a non-empty string")
    if entity_id is not None and name is not None:
        raise ValueError("pass at most one of entity_id / name, not both")
    if name is not None:
        row = store.get_name_by_text(_conn, name)
        if row is None:
            raise ValueError(f"name not found: {name!r}")
        entity_id = row["entity_id"]
    if entity_id is not None and store.get_entity_by_id(_conn, entity_id) is None:
        raise ValueError(f"entity not found: {entity_id!r}")

    # Text-match path — the historical behavior. When entity_id is set,
    # this is the only path; explicit filters suppress alias expansion.
    text_rows = store.grep_statements(
        _conn,
        query,
        case_sensitive=case_sensitive,
        entity_id=entity_id,
        kind=kind,
        limit=10_000 if (match_aliased_mentions and entity_id is None) else limit,
        offset=0 if (match_aliased_mentions and entity_id is None) else offset,
    )
    text_ids = {r["id"]: r for r in text_rows}

    if not match_aliased_mentions or entity_id is not None:
        total = store.count_grep_statements(
            _conn,
            query,
            case_sensitive=case_sensitive,
            entity_id=entity_id,
            kind=kind,
        )
        return {
            "total": total,
            "statements": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "text": r["text"],
                    "matched_via": "text",
                }
                for r in text_rows
            ],
        }

    mention_rows = store.grep_statements_via_mentions(
        _conn, query, case_sensitive=case_sensitive, kind=kind
    )
    mention_ids = {r["id"]: r for r in mention_rows}

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in text_rows:
        sid = r["id"]
        seen.add(sid)
        matched_via = "both" if sid in mention_ids else "text"
        combined.append(
            {
                "id": sid,
                "kind": r["kind"],
                "text": r["text"],
                "matched_via": matched_via,
                "_rid": r["rid"],
            }
        )
    for r in mention_rows:
        sid = r["id"]
        if sid in seen:
            continue
        seen.add(sid)
        combined.append(
            {
                "id": sid,
                "kind": r["kind"],
                "text": r["text"],
                "matched_via": "mention",
                "_rid": r["rid"],
            }
        )

    combined.sort(key=lambda x: x["_rid"])
    total = len(combined)
    sliced = combined[offset : offset + limit]
    return {
        "total": total,
        "statements": [
            {
                "id": s["id"],
                "kind": s["kind"],
                "text": s["text"],
                "matched_via": s["matched_via"],
            }
            for s in sliced
        ],
    }


def list_annotation_kinds() -> list[str]:
    """Distinct `kind` values currently materialised on at least one
    `annotations` row, sorted alphabetically.

    Snapshot of what's IN USE, not the substrate's allowed vocabulary —
    the vocabulary is open. Common conventions: `permission`,
    `invariant`, `property`, `compliance`, `fact`, `rationale`,
    `example`. Pick the leaf that best describes the annotation's role;
    invent new kinds when none fit.
    """
    assert _conn is not None
    return store.list_annotation_kinds(_conn)


@tool(role="reader")
def report_knowledge_gap(text: str) -> dict[str, Any]:
    """Flag a gap, inconsistency, or unclear area in the knowledge base
    for a human curator to review.

    Free-form text body; the reporter writes whatever's most useful —
    a missing topic, a contradiction between two statements, an entity
    that looks incomplete, a typo, a stale claim. If the report
    references a specific entity or statement, include the id in the
    text so the reviewer can jump to it.

    Open reports surface in the UI's Gaps page until a human marks
    them resolved or dismissed; nothing is auto-pruned.

    Returns the assigned `gap_id`.
    """
    assert _conn is not None
    text = text.strip()
    if not text:
        raise ValueError("text is required")

    import uuid
    from datetime import datetime, timezone

    gap_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    actor = store.get_actor()
    _conn.execute(
        "INSERT INTO knowledge_gaps (id, text, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (gap_id, text, now, actor),
    )
    _conn.commit()
    return {"gap_id": gap_id}


# --- draft management tools -----------------------------------------------
# These manipulate the draft queue itself rather than the substrate.
# Their names don't start with substrate mutation prefixes, so the @tool
# wrapper doesn't auto-attach a `draft_id` parameter — they accept one
# as a normal positional/keyword arg referring to the draft they operate
# on. `submit_draft` requires writer rank, which a drafter satisfies via
# the role-equivalence in auth.principal_satisfies.


@tool
def submit_draft(draft_id: str | None = None) -> dict[str, Any]:
    """Submit a draft for curator review.

    `draft_id` is optional — when omitted, submits the caller's
    currently-open auto-draft (the one their MCP session has been
    accumulating ops into). After submission the draft can no longer
    accept new ops via tool calls; the curator either approves it
    (replays the ops against the substrate) or rejects it.

    Returns the submitted draft's id and final op count.
    """
    from . import auth as _auth, drafts_store

    assert _drafts_conn is not None
    principal = _auth.current_principal.get()

    if draft_id is None:
        if principal is None:
            raise ValueError("no draft_id given and no caller identity")
        session_id = _auth.current_session_id.get() or f"actor:{principal.id}"
        row = drafts_store.find_open_session_draft(_drafts_conn, session_id)
        if row is None:
            raise ValueError("no open draft to submit for this caller")
        draft_id = row["id"]
    else:
        row = drafts_store.get_draft(_drafts_conn, draft_id)
        if row is None:
            raise ValueError(f"draft '{draft_id}' not found")
        if drafts_store.status_for(row) != "open":
            raise ValueError(
                f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
                f"only open drafts can be submitted"
            )

    drafts_store.set_submitted(_drafts_conn, draft_id)
    ops = drafts_store.list_ops(_drafts_conn, draft_id)
    return {"draft_id": draft_id, "op_count": len(ops)}


@tool
def list_my_drafts() -> list[dict[str, Any]]:
    """List drafts created by the calling principal, newest first.

    Useful for an agent to inspect what it queued in earlier sessions
    or check on the review state of submitted work.
    """
    from . import auth as _auth, drafts_store

    assert _drafts_conn is not None
    principal = _auth.current_principal.get()
    creator = principal.id if principal is not None else None
    rows = _drafts_conn.execute(
        "SELECT * FROM drafts WHERE created_by = ? ORDER BY created_at DESC",
        (creator,),
    ).fetchall()
    return [drafts_store.serialize_draft(r) for r in rows]


@tool
def get_draft(draft_id: str) -> dict[str, Any]:
    """Return a draft and its queued ops, in seq order.

    Anyone with read access can fetch any draft — drafts are intended
    for curator review so visibility is broad. The shape mirrors the
    HTTP `/api/drafts/<id>` response.
    """
    from . import drafts_store

    assert _drafts_conn is not None
    row = drafts_store.get_draft(_drafts_conn, draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    ops = drafts_store.list_ops(_drafts_conn, draft_id)
    return drafts_store.serialize_draft(row, ops=ops)


@tool
def discard_draft_op(draft_id: str, seq: int) -> dict[str, Any]:
    """Remove a queued op from an open draft by its seq number.

    Lets a drafter self-correct a mistake without abandoning the whole
    draft. The op's seq stays burned — remaining ops keep their original
    sequence numbers (no renumbering) so any external references to a
    `(draft_id, seq)` pair stay stable.
    """
    from . import drafts_store

    assert _drafts_conn is not None
    row = drafts_store.get_draft(_drafts_conn, draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    if drafts_store.status_for(row) != "open":
        raise ValueError(
            f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
            f"can't modify ops on a non-open draft"
        )
    removed = drafts_store.remove_op(_drafts_conn, draft_id, seq)
    if not removed:
        raise ValueError(f"no op with seq {seq} in draft '{draft_id}'")
    return {"draft_id": draft_id, "seq": seq, "removed": True}


def apply_draft(draft_id: str) -> dict[str, Any]:
    """Replay an `open` or `submitted` draft's ops against the substrate.

    Caller is responsible for having already verified the principal is
    a curator and the draft is in a state that allows approval. Iterates
    in seq order; each op invokes its matching MCP tool wrapper with the
    curator's principal already in the contextvar (so the role gate
    passes naturally). All-or-nothing: a single op raising halts replay
    and surfaces the error. Successful replay marks the draft `approved`.

    Returns `{applied: int, results: [...]}`. On failure, raises with
    the seq/kind that exploded.
    """
    from . import drafts_store

    assert _drafts_conn is not None
    row = drafts_store.get_draft(_drafts_conn, draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        raise ValueError(
            f"draft '{draft_id}' is {status}; only open or submitted "
            f"drafts can be approved"
        )

    ops = drafts_store.list_ops(_drafts_conn, draft_id)
    tools_by_name = {w.__name__: w for w in TOOLS}
    results: list[dict[str, Any]] = []
    import json as _j

    for op in ops:
        kind = op["kind"]
        wrapper = tools_by_name.get(kind)
        payload = _j.loads(op["payload_json"])
        if wrapper is None:
            # The tool was removed since this op was queued — notably
            # `add_mentions` / `remove_mentions`, now that mentions are
            # derived. Such an op is obsolete; skip it rather than fail the
            # whole draft.
            results.append({"seq": op["seq"], "kind": kind, "skipped": "obsolete_tool"})
            continue
        # Drop payload keys the tool no longer accepts (e.g. a stale
        # `mentions` / `strict_mentions` on a queued upsert_statement) so an
        # old draft replays cleanly instead of raising on an unexpected kwarg.
        sig = _ORIG_SIGNATURES.get(kind)
        if sig is not None:
            for key in [k for k in payload if k not in sig.parameters]:
                payload.pop(key)
        try:
            result = wrapper(**payload)
        except Exception as ex:
            raise RuntimeError(
                f"op seq={op['seq']} ({kind}) failed during replay: {ex}"
            ) from ex
        results.append({"seq": op["seq"], "kind": kind, "result": result})
    return {"applied": len(results), "results": results}


def run() -> None:
    mcp.run(transport="stdio")
