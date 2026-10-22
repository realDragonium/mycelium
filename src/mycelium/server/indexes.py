"""Keeping the two vector indexes durable alongside the substrate they mirror.

The hnswlib files are written outside SQLite's transaction, so each write that
touches an index brackets it with a `.dirty` marker: present from the first
index mutation until the persisted file and the outermost commit both land. A
marker found at startup means the file may disagree with the database, and
`init` rebuilds that index by re-embedding.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from .. import embed, store, vector
from .runtime import _db, _idx, _idx_path, _name_idx, _name_idx_path

logger = logging.getLogger(__name__)


def _rebuild_vector_index(
    index: vector.Index,
    rows: list[sqlite3.Row],
    get_id: Callable[[sqlite3.Connection, str], int | None],
    next_id: Callable[[sqlite3.Connection], int],
    set_id: Callable[[sqlite3.Connection, str, int], None],
    *,
    label: str,
) -> None:
    """Populate an empty vector index by re-embedding every row in the DB.

    Shared by the statement and name index rebuilds (parameterized by the
    matching `*_vector_id` store calls). A restore drops the re-derivable .vec
    files but keeps the `*_vector_ids` mappings, so reuse each row's existing
    id when present — re-adding under the same id keeps rows that reference it
    valid — and allocate (and persist) a fresh id only for rows with none.
    Called during `init` before the context is assembled, so the index is
    passed explicitly rather than reached through an accessor."""
    if rows:
        logger.info(
            "rebuilding %s vector index: re-embedding %d row(s)", label, len(rows)
        )
    for row in rows:
        existing = get_id(_db(), row["id"])
        vid = existing if existing is not None else next_id(_db())
        index.add(vid, embed.embed(row["text"]))
        if existing is None:
            set_id(_db(), row["id"], vid)


def _persist_index() -> None:
    _idx().save(_idx_path())


def _persist_name_index() -> None:
    _name_idx().save(_name_idx_path())


def _dirty_marker_path(index_path: Path) -> Path:
    return index_path.with_name(index_path.name + ".dirty")


def _fsync_file(path: Path) -> None:
    file_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(file_fd)
    finally:
        os.close(file_fd)

    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _write_dirty_marker(index_path: Path) -> None:
    marker_path = _dirty_marker_path(index_path)
    marker_fd = os.open(marker_path, os.O_CREAT | os.O_WRONLY)
    try:
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)

    parent_fd = os.open(marker_path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _clear_dirty_marker(index_path: Path) -> None:
    _dirty_marker_path(index_path).unlink(missing_ok=True)


def _fsync_and_clear_marker(index_path: Path, *, keep_marker: bool) -> None:
    """Post-commit marker teardown for one index; never raises.

    `keep_marker=True` preserves a marker inherited from an earlier failed
    write (sticky until startup reconciliation)."""
    try:
        _fsync_file(index_path)
        if not keep_marker:
            _clear_dirty_marker(index_path)
    except OSError:
        logger.warning(
            "could not fsync %s or clear its dirty marker; next startup will rebuild",
            index_path,
            exc_info=True,
        )


@contextlib.contextmanager
def _persisted_index_write(
    *, statements: bool = False, names: bool = False
) -> Iterator[None]:
    """Run one write operation's substrate and index mutations, then persist
    them before releasing the write lock.

    This is the persist-inside-lock guarantee apply_draft got in DRA-373. A
    dirty marker covers the window from the first index mutation through a
    successful persist and outermost commit, so a hard crash triggers a startup
    rebuild. Nested writes persist but leave marker ownership to the outer
    transaction, which clears only after its real COMMIT. A marker inherited
    from an earlier failed write is sticky: later writes may persist and commit,
    but only startup reconciliation clears it. If commit fails, DRA-418 rolls
    the DB back and the next startup heals the divergent index.
    """
    with store.write_lock():
        conn = _db()
        outermost = not store.in_transaction(conn)
        statement_marker_preexisting = (
            outermost and statements and _dirty_marker_path(_idx_path()).exists()
        )
        name_marker_preexisting = (
            outermost and names and _dirty_marker_path(_name_idx_path()).exists()
        )
        with store.transaction(conn):
            if statements:
                _write_dirty_marker(_idx_path())
            if names:
                _write_dirty_marker(_name_idx_path())
            yield
            if statements:
                _persist_index()
            if names:
                _persist_name_index()
        # The outer transaction committed; still under the reentrant lock so
        # no other writer can interleave between commit and marker clear.
        # Best-effort from here: the write succeeded the moment commit
        # returned, so a failed fsync or marker unlink must not surface as a
        # failed operation (apply_draft would wrongly restore pre-apply
        # indexes over a committed replay). A kept marker just means the next
        # startup rebuilds.
        if outermost:
            if statements:
                _fsync_and_clear_marker(
                    _idx_path(), keep_marker=statement_marker_preexisting
                )
            if names:
                _fsync_and_clear_marker(
                    _name_idx_path(), keep_marker=name_marker_preexisting
                )


def _restore_index_snapshots(
    snapshots: tuple[tuple[vector.Index, Path, Path], ...],
) -> None:
    """Best-effort restore each index without hiding the replay failure.

    Restore indexes independently so one damaged snapshot cannot prevent the
    other from recovering. Keep every dirty marker set so startup rebuilds both
    indexes after a failed apply, and keep any snapshot whose restore,
    persistence, or cleanup fails so an operator still has the recovery
    artifact.
    """
    for index, snapshot_path, live_path in snapshots:
        try:
            _write_dirty_marker(live_path)
            index.restore(snapshot_path)
            index.save(live_path)
            _fsync_file(live_path)
            snapshot_path.unlink(missing_ok=True)
        except Exception:
            logger.exception(
                "failed to restore vector index %s from %s; "
                "snapshot kept at %s for operator recovery",
                live_path,
                snapshot_path,
                snapshot_path,
            )
