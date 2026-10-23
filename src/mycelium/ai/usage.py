"""Metering of every model call: who asked, what it used, what it cost.

`turn` and `structured` report each call here, so an action is metered by
calling the model at all. What the call was for comes from the attribution in
the calling context: an action names itself with `attributed` (or, at the top
of a worker thread's own context, `attribute`). A call made outside any
attribution is still recorded, as `other`.

The package stays free of storage: the server installs a `Recorder` that
persists calls and a `Gate` that may refuse one before it is sent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from .pricing import price
from .types import IncompleteTurn, ModelConfig, ModelError, Usage

_LOG = logging.getLogger(__name__)

UNATTRIBUTED = "other"


@dataclass(frozen=True)
class Attribution:
    action: str = UNATTRIBUTED
    run_id: str | None = None
    draft_id: str | None = None


@dataclass(frozen=True)
class Call:
    action: str
    provider: str
    model: str
    usage: Usage
    cost_usd: float | None
    duration_ms: int
    ok: bool
    run_id: str | None
    draft_id: str | None


class Paused(ModelError):
    """The call was refused before reaching the provider."""


Recorder = Callable[[Call], None]
#: Returns why the action may not call a model now, or None to let it.
Gate = Callable[[str], str | None]

_attribution: ContextVar[Attribution | None] = ContextVar(
    "ai_usage_attribution", default=None
)
_recorder: Recorder | None = None
_gate: Gate | None = None


def install(recorder: Recorder | None, gate: Gate | None = None) -> None:
    global _recorder, _gate
    _recorder, _gate = recorder, gate


def current() -> Attribution:
    return _attribution.get() or Attribution()


def _merged(
    action: str | None, run_id: str | None, draft_id: str | None
) -> Attribution:
    outer = current()
    return replace(
        outer,
        action=action or outer.action,
        run_id=run_id or outer.run_id,
        draft_id=draft_id or outer.draft_id,
    )


def attribute(
    action: str | None = None,
    *,
    run_id: str | None = None,
    draft_id: str | None = None,
) -> None:
    """Attribute the rest of this context's calls. Only for a context that
    belongs to one piece of work, such as a worker thread's own."""
    _attribution.set(_merged(action, run_id, draft_id))


@contextmanager
def attributed(
    action: str | None = None,
    *,
    run_id: str | None = None,
    draft_id: str | None = None,
) -> Iterator[None]:
    """Attribute the calls made inside the block; unset fields keep the
    enclosing attribution."""
    token = _attribution.set(_merged(action, run_id, draft_id))
    try:
        yield
    finally:
        _attribution.reset(token)


@contextmanager
def metered(config: ModelConfig) -> Iterator[Callable[[Usage], None]]:
    """Meter one call. The block reports its usage through the yielded
    callback; a failure is recorded with the usage it carried, if any."""
    who = current()
    reason = _refusal(who.action)
    if reason is not None:
        raise Paused(reason)
    started = time.monotonic()
    reported: list[Usage] = []
    try:
        yield reported.append
    except BaseException as exc:
        used = exc.usage if isinstance(exc, IncompleteTurn) else Usage()
        _record(config, who, used, started, ok=False)
        raise
    _record(config, who, reported[-1] if reported else Usage(), started, ok=True)


def _refusal(action: str) -> str | None:
    if _gate is None:
        return None
    try:
        return _gate(action)
    except Exception:  # an unreadable budget must not stop every action
        _LOG.warning("could not check the AI budget", exc_info=True)
        return None


def _record(
    config: ModelConfig, who: Attribution, used: Usage, started: float, *, ok: bool
) -> None:
    if _recorder is None:
        return
    rate = price(config.provider, config.model)
    call = Call(
        action=who.action,
        provider=config.provider,
        model=config.model,
        usage=used,
        cost_usd=rate.cost_usd(used) if rate is not None else None,
        duration_ms=round((time.monotonic() - started) * 1000),
        ok=ok,
        run_id=who.run_id,
        draft_id=who.draft_id,
    )
    try:
        _recorder(call)
    except Exception:  # metering must never fail the call it measures
        _LOG.warning("could not record AI usage", exc_info=True)
