"""The server's live runtime state and the accessors every tool reads it through.

`init` builds the `AppContext` and stores it in `_ctx`; nothing else
assigns it. The connection accessors don't read `_ctx` at all: each store keeps
its own per-thread connection, and these are the one name each tool calls to get
this thread's.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import store, vector
from ..app_context import AppContext
from ..layout_baker import LayoutBaker

#: The live application context — vector indexes, data dir, layout baker.
#: Built whole by `init`; every accessor below reads through it.
_ctx: AppContext | None = None


def _context() -> AppContext:
    """This process's application context. Built by `init`; raises if
    reached before the server is initialized."""
    if _ctx is None:
        raise RuntimeError("server not initialized (call init)")
    return _ctx


def _db() -> sqlite3.Connection:
    """This thread's substrate connection (see `store.substrate_connection`).

    Each request thread reads/writes its own connection, so a reader never
    sees another in-flight request's uncommitted rows; writers serialize
    through `store.transaction()`."""
    return store.substrate_connection()


def _auth_db() -> sqlite3.Connection:
    """This thread's auth connection (see `auth_store.connection`).

    Configured by `init`; each thread reopens lazily against the auth file.
    Raises if reached before the server is initialized."""
    from .. import auth_store

    return auth_store.connection()


def _drafts_db() -> sqlite3.Connection:
    """This thread's drafts connection (see `drafts_store.connection`).

    Configured by `init`; each thread reopens lazily against the drafts file.
    Raises if reached before the server is initialized."""
    from .. import drafts_store

    return drafts_store.connection()


def _prompts_db() -> sqlite3.Connection:
    """This thread's prompt-texts connection (see `prompt_store.connection`).

    Configured by `init`; each thread reopens lazily against the prompts file.
    Raises if reached before the server is initialized."""
    from .. import prompt_store

    return prompt_store.connection()


def _idx() -> vector.Index:
    """The statement vector index. Loaded by `init`; raises if reached
    before the server is initialized. Inside an audience scope it ranks only
    the statements that audience may see."""
    from .. import audience_scope  # local import: the scope imports the store

    scope = audience_scope.active()
    index = _context().index
    return index if scope is None else index.restricted(scope.vector_ids)


def _idx_path() -> Path:
    """On-disk path the statement index persists to (set by `init`)."""
    return _context().index_path


def _name_idx() -> vector.Index:
    """The entity-name vector index. Loaded by `init`; raises if reached
    before the server is initialized."""
    return _context().name_index


def _name_idx_path() -> Path:
    """On-disk path the name index persists to (set by `init`)."""
    return _context().name_index_path


def _baker() -> LayoutBaker:
    """The entity-layout baker for this substrate. Built by `init`; raises
    if reached before the server is initialized."""
    return _context().layout_baker
