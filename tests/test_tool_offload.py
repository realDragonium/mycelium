"""A slow tool must not freeze the server for everyone else.

`admission._offloaded` runs each tool body on a worker thread under that tool's
bound, so a single multi-second `ask` cannot stall every concurrent request on
the process — including any health probe, which is what would turn one slow
call into a 503 for every caller behind a proxy that drops unhealthy backends.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time

import anyio
import pytest

from mycelium import auth, product_settings, server
from mycelium.server import admission
from product_settings_helpers import set_product


def test_offloaded_call_leaves_the_event_loop_free():
    released = threading.Event()

    def blocking_tool() -> str:
        assert released.wait(5)
        return "done"

    offloaded = admission._offloaded(blocking_tool)

    async def scenario():
        task = asyncio.ensure_future(offloaded())
        await asyncio.sleep(0)
        # Inline execution would block here until the tool's wait timed out.
        released.set()
        return await task

    assert asyncio.run(scenario()) == "done"


def test_offloaded_call_returns_the_wrapped_result():
    def add(a: int, b: int = 1) -> int:
        return a + b

    offloaded = admission._offloaded(add)

    assert asyncio.run(offloaded(2, b=3)) == 5


def test_offloaded_call_propagates_the_exception():
    def boom() -> None:
        raise ValueError("nope")

    offloaded = admission._offloaded(boom)

    with pytest.raises(ValueError, match="nope"):
        asyncio.run(offloaded())


def test_offloaded_call_runs_off_the_calling_thread():
    def which_thread() -> int:
        return threading.get_ident()

    offloaded = admission._offloaded(which_thread)

    assert asyncio.run(offloaded()) != threading.get_ident()


def test_offloaded_call_carries_the_principal_into_the_worker_thread():
    """The role gate inside the tool wrapper reads `auth.current_principal`, so
    the offload is only correct if contextvars follow the call across threads."""

    def caller_role() -> str | None:
        principal = auth.current_principal.get()
        return principal.role if principal is not None else None

    offloaded = admission._offloaded(caller_role)

    async def scenario():
        token = auth.current_principal.set(
            auth.Principal(id="t", name="t", role="drafter", type="service")
        )
        try:
            return await offloaded()
        finally:
            auth.current_principal.reset(token)

    assert asyncio.run(scenario()) == "drafter"


def test_offloaded_preserves_the_signature_pydantic_reads():
    """The MCP server derives each tool's JSON schema from `inspect.signature`, and this
    module's `from __future__ import annotations` means a naively-copied
    signature carries unresolvable string forward refs."""

    def some_tool(query: str, k: int = 5) -> dict[str, str]:
        """A docstring."""
        return {}

    offloaded = admission._offloaded(some_tool)

    import inspect

    assert inspect.signature(offloaded) == inspect.signature(some_tool)
    assert offloaded.__name__ == "some_tool"
    assert offloaded.__doc__ == "A docstring."


def test_every_registered_mcp_tool_is_offloaded():
    """The wiring assertion: a tool registered as sync would silently reintroduce
    the stall, and nothing else in the suite would notice."""
    registered = server.mcp._tool_manager.list_tools()

    assert registered
    assert [t.name for t in registered if not t.is_async] == []


def test_model_loop_tools_are_bounded_more_tightly_than_the_general_pool(monkeypatch):
    set_product(product_settings.ConcurrencySettings(model_loops=3))
    admission._model_loop_limiter.cache_clear()

    async def scenario():
        return (
            admission._model_loop_limiter().total_tokens,
            anyio.to_thread.current_default_thread_limiter().total_tokens,
        )

    try:
        bound, general_pool = asyncio.run(scenario())
    finally:
        admission._model_loop_limiter.cache_clear()

    assert bound == 3
    assert bound < general_pool
    assert admission._MODEL_LOOP_TOOLS == {"ask", "ingest", "connect_statements"}


def test_limiter_is_selected_by_name_not_by_transport():
    assert server.limiter_for("ask") is server.limiter_for("ingest")
    assert server.limiter_for("search_statements") is None
    assert server.limiter_for("upsert_statement") is None


def test_rest_mirror_routes_bounded_tools_through_an_async_handler():
    """The REST handlers are built from the raw sync wrapper in `server.TOOLS`,
    not from the MCP offloading shim — so a bounded tool needs its own async
    handler here, or posting to `/ingest` walks straight past the bound."""
    from mycelium.http import app

    for name in sorted(admission._MODEL_LOOP_TOOLS):
        route = next(r for r in app.routes if getattr(r, "name", None) == name)
        assert inspect.iscoroutinefunction(route.endpoint), name


def test_rest_offload_applies_the_same_bound(monkeypatch):
    """The regression Codex caught: `/ask` and `/ingest` over REST bypassed the
    limiter entirely, so the bound could be exceeded by choosing a transport."""
    set_product(product_settings.ConcurrencySettings(model_loops=2))
    admission._model_loop_limiter.cache_clear()

    from mycelium.http import tool_routes

    peak = 0
    live = 0
    lock = threading.Lock()

    def model_loop():
        nonlocal peak, live
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1

    model_loop.__name__ = "ingest"

    async def scenario():
        await asyncio.gather(*(tool_routes._offload(model_loop, {}) for _ in range(6)))

    try:
        asyncio.run(scenario())
    finally:
        admission._model_loop_limiter.cache_clear()

    assert peak == 2


def test_background_runs_draw_on_the_same_budget_as_ask_and_ingest(monkeypatch):
    """A background run lives on its own daemon thread with no event loop, so it
    cannot wait on the anyio limiter. If it kept a private cap the two would add up and
    the box would hold more model contexts than either cap intended."""
    set_product(product_settings.ConcurrencySettings(model_loops=2))
    admission._model_loop_budget.cache_clear()

    peak = 0
    live = 0
    lock = threading.Lock()

    def model_loop():
        nonlocal peak, live
        with server.model_loop_slot():
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.05)
            with lock:
                live -= 1

    # Mixed starters: some on worker threads (ask/ingest), some standing in for
    # a background run's own daemon thread. One budget covers both.
    threads = [threading.Thread(target=model_loop) for _ in range(6)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    finally:
        admission._model_loop_budget.cache_clear()

    assert peak == 2


def test_model_loop_limiter_admits_only_its_bound_concurrently(monkeypatch):
    set_product(product_settings.ConcurrencySettings(model_loops=2))
    admission._model_loop_limiter.cache_clear()

    peak = 0
    live = 0
    lock = threading.Lock()

    def model_loop() -> None:
        nonlocal peak, live
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1

    model_loop.__name__ = "ask"
    offloaded = admission._offloaded(model_loop)

    async def scenario():
        await asyncio.gather(*(offloaded() for _ in range(6)))

    try:
        asyncio.run(scenario())
    finally:
        admission._model_loop_limiter.cache_clear()

    assert peak == 2
