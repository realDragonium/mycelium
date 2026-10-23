"""Admission for tool calls: the shared model-loop budget and worker offloading.

Every transport passes through here — MCP, the REST mirror, stdio and draft
replay — so a caller cannot dodge the bound on model loops by choosing a
different entry point. The bound caps memory rather than threads: each loop
holds a model context while it runs.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable, Iterator
from typing import Any

import anyio
import anyio.to_thread

from ..model_capacity import Capacity

#: Tools that drive a multi-turn model loop, so they occupy a worker thread for
#: tens of seconds and hold a model context worth of memory while they do. They
#: are bounded far tighter than the general pool: memory, not threads, is what
#: runs out first, and the embedding backend is usually competing for the same
#: box. `start_research` and `request_documentation` are not here because the
#: TOOLS are fast — they return a run id immediately. Their background runs are
#: model loops like any other and draw on the same budget; see
#: `model_loop_slot`.
_MODEL_LOOP_TOOLS = frozenset({"ask", "ingest"})


def _model_loop_max_concurrent() -> int:
    from .. import product_settings

    return product_settings.get(product_settings.ConcurrencySettings).model_loops


# Two primitives, one number, because the model loops do not all start from the
# same place. `ask`/`ingest` are requests: they arrive on the event loop, so the
# CapacityLimiter gates them BEFORE they take a worker thread — without it, an
# arbitrary number of them would each grab a thread just to sit blocked, which
# is how the general pool gets starved. A research run has no event loop at all;
# it is a plain daemon thread, and can only wait on a threading primitive.
#
# So the semaphore is the real budget — every model loop holds one of its slots
# while it runs, whatever started it — and the limiter is the front door that
# keeps request-shaped callers from piling up on threads to reach it. Both follow
# the saved shared concurrency limit, so at most that many loops run
# and at most that many threads are ever parked waiting for one.


@functools.cache
def _model_loop_limiter() -> anyio.CapacityLimiter:
    """One request-side limiter; limiter_for refreshes its saved capacity."""
    return anyio.CapacityLimiter(_model_loop_max_concurrent())


@functools.cache
def _model_loop_budget() -> Capacity:
    return Capacity(_model_loop_max_concurrent)


@contextlib.contextmanager
def model_loop_slot() -> Iterator[None]:
    """Hold one slot of the shared model-loop budget for the duration of the
    call. Acquirable from any thread, which is the point: `ask` and `ingest`
    take a slot from their worker thread, a research run takes one from its own
    daemon thread, and the three cannot collectively exceed the budget."""
    budget = _model_loop_budget()
    budget.acquire()
    try:
        yield
    finally:
        budget.release()


def _run_tool(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    budgeted: bool,
) -> Any:
    """Execute a tool body — under the shared model-loop budget when the tool
    declares one.

    This is the seam every transport passes through, which is the point: the
    budget is enforced here rather than at any one entry point, so MCP, the REST
    mirror, stdio and draft replay are all bound by the same accounting.
    """
    with model_loop_slot() if budgeted else contextlib.nullcontext():
        return func(*args, **kwargs)


def limiter_for(tool_name: str) -> anyio.CapacityLimiter | None:
    """The bound `tool_name` runs under, or None to use the general worker pool.

    Deliberately shared by BOTH transports — the MCP shim below and the REST
    mirror's handlers in `http.py`. The bound exists to cap memory on the box,
    which does not care which transport asked, so a caller must not be able to
    slip past it by calling `/ingest` instead of the MCP tool.
    """
    if tool_name not in _MODEL_LOOP_TOOLS:
        return None
    limiter = _model_loop_limiter()
    limiter.total_tokens = _model_loop_max_concurrent()
    return limiter


def _offloaded(wrapper: Callable[..., Any]) -> Callable[..., Any]:
    """Present `wrapper` to the MCP server as a coroutine that runs the real
    work in a worker thread, under this tool's bound.

    The SDK dispatches a sync tool function to its own worker thread, but on
    the general pool with no per-tool bound. That bound is the point here: the
    model-loop tools each hold a model context worth of memory, so what runs
    out first is the box, not the thread pool. Registering as a coroutine
    keeps the dispatch ours, which is what lets `limiter_for` gate it —
    against the same limiter the REST mirror uses, so a caller cannot slip
    past the cap by choosing a transport.

    Safe because the store hands every thread its own SQLite connection
    (`store.kernel.ConnectionProvider`), and `anyio.to_thread.run_sync`
    propagates contextvars, so the resolved principal follows the call in.
    """

    name = wrapper.__name__

    @functools.wraps(wrapper)
    async def offloaded(*args: Any, **kwargs: Any) -> Any:
        if name == "ask":
            from ..ask.events import run_cancellable

            return await run_cancellable(
                lambda: anyio.to_thread.run_sync(
                    functools.partial(wrapper, *args, **kwargs),
                    limiter=limiter_for(name),
                    abandon_on_cancel=True,
                )
            )
        return await anyio.to_thread.run_sync(
            functools.partial(wrapper, *args, **kwargs), limiter=limiter_for(name)
        )

    # No __signature__ is set here: functools.wraps copies the wrapper's __dict__
    # (carrying the spliced draft_id signature when there is one) and otherwise
    # leaves inspect.signature to follow __wrapped__ back to the original, whose
    # annotations Pydantic can still resolve. Setting one explicitly would freeze
    # in the unresolved string forward refs the tool modules' `from __future__
    # import annotations` produces.
    return offloaded
