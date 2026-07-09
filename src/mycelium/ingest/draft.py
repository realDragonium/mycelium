"""The no-live-write keystone.

`ingest` turns text into a *reviewable draft*, never a live substrate write.
This module is the single seam through which a draft is created and ops are
queued — and it does so exclusively via `drafts_store`, which touches only the
drafts DB. It imports **no** substrate write tool and **never** touches
`server._conn`.

That is the structural guarantee: the inner model is handed read tools plus one
terminal `emit_draft` tool and never sees a write tool; the only write path in
the whole package is `drafts_store.create_draft` / `add_op` against this
thread's drafts connection (`server._drafts_db()`), reached only through here.

A draft op's `kind` is the substrate write-tool function name; its payload is
that tool's kwargs with None-valued keys dropped. The kind is validated against
`valid_kinds()` (the live `server.TOOLS` registry) before anything is queued —
validation can't be deferred to the model, because a bad kind would only fail
at curator replay time.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

from .. import drafts_store, store


class DraftEmitter(Protocol):
    """The seam the loop depends on for the (only) write path. Injectable so
    the loop is exercisable with a plain fake — no server, no DB."""

    def valid_kinds(self) -> set[str]: ...

    def allowed_keys(self, kind: str) -> set[str]: ...

    def create(self, *, title: str | None = None) -> str: ...

    def add_op(self, draft_id: str, kind: str, payload: dict) -> int: ...


class InProcessDraftEmitter:
    """Creates a draft and queues ops in the live drafts DB, in-process.

    `server_module` is injectable so tests can supply a stub; in production it
    is `mycelium.server` (it must be `init()`-ialised, so `_drafts_db()`
    returns this thread's live drafts connection).
    """

    def __init__(self, server_module: Any | None = None) -> None:
        self._server = server_module or importlib.import_module("mycelium.server")

    def valid_kinds(self) -> set[str]:
        """The registered substrate tool function names. A draft op's kind must
        be one of these or curator replay can never run it."""
        return {getattr(w, "__name__", "") for w in getattr(self._server, "TOOLS", [])}

    def allowed_keys(self, kind: str) -> set[str]:
        """The kwarg names the real `kind` tool accepts at curator replay.

        Sourced from `server._ORIG_SIGNATURES`, which holds each tool's
        PRE-draft-splice signature, so the injected `draft_id` is already
        excluded. The curator replays an op as `wrapper(**payload)` with ZERO
        key filtering, so any payload key NOT in this set raises a TypeError and
        aborts the whole all-or-nothing draft — the loop uses this to reject
        such ops before they are queued.

        SAFE FALLBACK: if `_ORIG_SIGNATURES` is missing or `kind` is not in it,
        return the empty set, which the loop reads as "unknown — do not filter",
        so we never over-drop a legitimate op. Mirrors `valid_kinds()`."""
        sigs = getattr(self._server, "_ORIG_SIGNATURES", None)
        if not sigs or kind not in sigs:
            return set()
        return set(sigs[kind].parameters)

    def create(self, *, title: str | None = None) -> str:
        conn = self._server._drafts_db()
        with store.transaction(conn):
            return drafts_store.create_draft(
                conn,
                created_by=None,
                session_id=None,
                title=title,
            )

    def add_op(self, draft_id: str, kind: str, payload: dict) -> int:
        clean = {k: v for k, v in payload.items() if v is not None}
        conn = self._server._drafts_db()
        with store.transaction(conn):
            return drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind=kind,
                payload=clean,
                created_by=None,
            )
