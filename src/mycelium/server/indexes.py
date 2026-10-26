"""Keeping the two vector indexes durable alongside the substrate they mirror.

The hnswlib files are written outside SQLite's transaction, so each write that
touches an index brackets it with a `.dirty` marker: present from the first
index mutation until the persisted file and the outermost commit both land. A
marker found at startup means the file may disagree with the database, and
`init` rebuilds that index by re-embedding.

A copy of the index files is only safe to restore beside the database it was
taken with. `snapshot_indexes` copies them under a file lock every index write
holds, so another process can take the copy while the server runs, and records
a fingerprint of the vector-id mappings and their texts in each copied sidecar.
`init` loads such a copy only while the restored database still has that
fingerprint, and rebuilds it otherwise.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .. import automation_stops, embed, store, vector
from .runtime import _db, _idx, _idx_path, _name_idx, _name_idx_path

logger = logging.getLogger(__name__)

_REBUILD_BATCH = embed.OPENAI_BATCH
_INVALID_IDENTITY = "<invalid index identity>"
_EARLIER_FORMAT = "<an earlier index format>"
#: Bumped when index files written by earlier code cannot be trusted, so each
#: is rebuilt once. 2: `Index.add` could leave a vector id on a stale slot or
#: on none.
INDEX_FORMAT = 2
STATEMENT_INDEX = "mycelium.vec"
NAME_INDEX = "mycelium-names.vec"
_FILES_LOCK = "mycelium-vec.lock"
_INDEXES: dict[str, Callable[[sqlite3.Connection], list[sqlite3.Row]]] = {
    STATEMENT_INDEX: store.statement_vector_texts,
    NAME_INDEX: store.name_vector_texts,
}
#: Guarded by `store.write_lock`, which every in-process lock holder takes first.
_files_lock_depth = 0


class SnapshotRefused(Exception):
    """The live index files may not match the database, so no copy was taken."""


@dataclass(frozen=True)
class Fingerprint:
    """The database state an index copy reflects: its vector-id mappings and
    their texts. A text edit keeps the mapping but replaces the vector, so the
    text belongs in it."""

    vectors: int
    sha256: str


def fingerprint(rows: Iterable[sqlite3.Row]) -> Fingerprint:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update(json.dumps([row["vector_id"], row["text"]]).encode())
        digest.update(b"\n")
        count += 1
    return Fingerprint(count, digest.hexdigest())


@contextlib.contextmanager
def _flock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / _FILES_LOCK, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


@contextlib.contextmanager
def _index_files_lock(data_dir: Path) -> Iterator[None]:
    """Hold the lock over the index files in `data_dir` for an index write.

    Callers hold `store.write_lock`, which excludes this process's other
    writers and makes this reentrant; the flock excludes `snapshot_indexes`."""
    global _files_lock_depth
    if _files_lock_depth:
        _files_lock_depth += 1
        try:
            yield
        finally:
            _files_lock_depth -= 1
        return
    with _flock(data_dir):
        _files_lock_depth = 1
        try:
            yield
        finally:
            _files_lock_depth = 0


def _try_embed(text: str) -> list[float] | None:
    try:
        return embed.embed(text)
    except embed.EmbeddingError as exc:
        logger.warning("embedding deferred: %s", exc)
        return None


def _set_statement_vector(statement_id: str, vec: list[float] | None) -> None:
    vector_id = store.get_vector_id(_db(), statement_id)
    if vec is None:
        if vector_id is not None:
            _idx().delete(vector_id)
            store.drop_vector_id(_db(), statement_id)
        return
    if vector_id is None:
        vector_id = store.next_vector_id(_db())
        store.set_vector_id(_db(), statement_id, vector_id)
        _idx().add(vector_id, vec)
    else:
        _idx().replace(vector_id, vec)


def _set_name_vector(name_id: str, vec: list[float] | None) -> None:
    vector_id = store.get_name_vector_id(_db(), name_id)
    if vec is None:
        if vector_id is not None:
            _name_idx().delete(vector_id)
            store.delete_name_vector_mapping(_db(), name_id)
        return
    if vector_id is None:
        vector_id = store.next_name_vector_id(_db())
        store.set_name_vector_id(_db(), name_id, vector_id)
        _name_idx().add(vector_id, vec)
    else:
        _name_idx().replace(vector_id, vec)


@dataclass(frozen=True)
class Pending:
    kind: Literal["statement", "name"]
    id: str
    text: str

    @property
    def key(self) -> str:
        """Its `automation_stops` item id."""
        return f"{self.kind}:{self.id}"


def pending(limit: int, skip: Collection[str] = ()) -> list[Pending]:
    """Up to `limit` statements, then names, without a vector, apart from
    the keys in `skip` and those stopped at their retry limit."""
    if limit <= 0:
        return []
    statements = store.list_pending_statements(
        _db(), limit, [key.removeprefix("statement:") for key in skip]
    )
    names = store.list_pending_names(
        _db(), limit - len(statements), [key.removeprefix("name:") for key in skip]
    )
    return [
        Pending("statement", str(row["id"]), str(row["text"])) for row in statements
    ] + [Pending("name", str(row["id"]), str(row["text"])) for row in names]


def embed_pending(rows: Sequence[Pending]) -> int:
    """Embed `rows` whose text remains unchanged. Raises EmbeddingError."""
    if not rows:
        return 0
    vectors = embed.embed_many([row.text for row in rows])
    embedded = 0
    with _persisted_index_write(
        statements=any(row.kind == "statement" for row in rows),
        names=any(row.kind == "name" for row in rows),
    ):
        for item, vec in zip(rows, vectors, strict=True):
            if item.kind == "statement":
                row = store.get_statement(_db(), item.id)
                mapped = store.get_vector_id(_db(), item.id)
            else:
                row = store.get_name_by_id(_db(), item.id)
                mapped = store.get_name_vector_id(_db(), item.id)
            if row is None or row["text"] != item.text or mapped is not None:
                continue
            if item.kind == "statement":
                _set_statement_vector(item.id, vec)
            else:
                _set_name_vector(item.id, vec)
            embedded += 1
        automation_stops.clear(_db(), "embedding", [row.key for row in rows])
    return embedded


def reembed_pending(limit: int = 256) -> int:
    """Embed pending statements and names whose text remains unchanged."""
    try:
        return embed_pending(pending(limit))
    except embed.EmbeddingError as exc:
        logger.warning("pending embedding pass failed: %s", exc)
        return 0


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
    logger.info(
        "rebuilding %s vector index with %s: re-embedding %d row(s)",
        label,
        embed.identity(),
        len(rows),
    )
    started = time.monotonic()
    for start in range(0, len(rows), _REBUILD_BATCH):
        batch = rows[start : start + _REBUILD_BATCH]
        vectors = embed.embed_many([row["text"] for row in batch])
        for row, embedding in zip(batch, vectors, strict=True):
            existing = get_id(_db(), row["id"])
            vid = existing if existing is not None else next_id(_db())
            index.add(vid, embedding)
            if existing is None:
                set_id(_db(), row["id"], vid)
        done = start + len(batch)
        logger.info(
            "rebuilding %s vector index: %d/%d re-embedded (%.0fs)",
            label,
            done,
            len(rows),
            time.monotonic() - started,
        )


def _rebuild_reason(
    path: Path,
    mapped: Callable[[sqlite3.Connection], list[sqlite3.Row]],
    configured_identity: str,
) -> str | None:
    """Why the index at `path` cannot be loaded, or None when it can."""
    if not path.exists():
        return "no index file"
    if _dirty_marker_path(path).exists():
        return "dirty marker indicates a crash before the index was persisted"
    recorded_identity, recorded = _read_index_meta(path)
    if recorded_identity != configured_identity:
        return f"built by {recorded_identity}, configured embedder is {configured_identity}"
    if recorded is None:
        return None
    current = fingerprint(mapped(_db()))
    if current != recorded:
        return (
            f"snapshot reflects {recorded.vectors} mapped vector(s) of another "
            f"database state; the database maps {current.vectors}"
        )
    return None


def load_or_rebuild(
    path: Path,
    *,
    label: str,
    rows: Callable[[sqlite3.Connection], list[sqlite3.Row]],
    mapped: Callable[[sqlite3.Connection], list[sqlite3.Row]],
    get_id: Callable[[sqlite3.Connection, str], int | None],
    next_id: Callable[[sqlite3.Connection], int],
    set_id: Callable[[sqlite3.Connection, str, int], None],
    on_load: Callable[[vector.Index, Path], None] | None = None,
) -> vector.Index:
    """Load a clean, compatible index or durably rebuild it from the substrate.

    A snapshot's sidecar carries the fingerprint of `mapped`; it loads only
    when the database still has it. Fetch rebuild rows inside the substrate
    transaction.
    """
    configured_identity = embed.identity()
    with store.write_lock(), _index_files_lock(path.parent):
        reason = _rebuild_reason(path, mapped, configured_identity)
        if reason is None:
            index = vector.Index.load(path)
            if _read_index_meta(path)[1] is not None:
                logger.info("loaded %s vector index from a matching snapshot", label)
                # Writes from here on leave the fingerprint behind.
                _write_index_identity(path, configured_identity)
            if on_load is not None:
                on_load(index, path)
            return index

        if path.exists():
            logger.warning("rebuilding %s vector index: %s", label, reason)
        _write_dirty_marker(path)
        index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                index, rows(_db()), get_id, next_id, set_id, label=label
            )
        index.save(path)
        _fsync_file(path)
        _write_index_identity(path, configured_identity)
        _clear_dirty_marker(path)
        return index


def prune_stranded_name_vectors(index: vector.Index, path: Path) -> None:
    """Prune loaded name vectors whose mappings were dropped by a migration
    (v6's case-variant merge does). Stranded vectors resolve to nothing but
    still occupy top-k slots in every name search."""
    stranded = [
        vid for vid in index.ids() if store.get_name_id_by_vector_id(_db(), vid) is None
    ]
    if stranded:
        logger.info("pruning %d stranded name vector(s)", len(stranded))
        # Called from `load_or_rebuild`, which holds the index files lock.
        _write_dirty_marker(path)
        for vid in stranded:
            index.delete(vid)
        index.save(path)
        _fsync_file(path)
        _clear_dirty_marker(path)


def _persist_index() -> None:
    _idx().save(_idx_path())


def _persist_name_index() -> None:
    _name_idx().save(_name_idx_path())


def _dirty_marker_path(index_path: Path) -> Path:
    return index_path.with_name(index_path.name + ".dirty")


def _meta_path(index_path: Path) -> Path:
    return index_path.with_name(index_path.name + ".meta.json")


def _read_index_identity(index_path: Path) -> str:
    return _read_index_meta(index_path)[0]


def _read_index_meta(index_path: Path) -> tuple[str, Fingerprint | None]:
    """The recorded embedder identity, and the fingerprint a snapshot records."""
    path = _meta_path(index_path)
    if not path.exists():
        return _EARLIER_FORMAT, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _INVALID_IDENTITY, None
    if not isinstance(payload, dict):
        return _INVALID_IDENTITY, None
    if payload.get("format") != INDEX_FORMAT:
        return _EARLIER_FORMAT, None
    identity = payload.get("embedder")
    if not isinstance(identity, str):
        return _INVALID_IDENTITY, None
    if "database" not in payload:
        return identity, None
    recorded = payload["database"]
    if (
        not isinstance(recorded, dict)
        or not isinstance(recorded.get("vectors"), int)
        or not isinstance(recorded.get("sha256"), str)
    ):
        return _INVALID_IDENTITY, None
    return identity, Fingerprint(recorded["vectors"], recorded["sha256"])


def _write_index_identity(
    index_path: Path, identity: str, database: Fingerprint | None = None
) -> None:
    path = _meta_path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            payload: dict[str, object] = {"embedder": identity, "format": INDEX_FORMAT}
            if database is not None:
                payload["database"] = {
                    "vectors": database.vectors,
                    "sha256": database.sha256,
                }
            json.dump(payload, file)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
        _fsync_file(path)
    finally:
        temp_path.unlink(missing_ok=True)


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
    with store.write_lock(), _index_files_lock(_idx_path().parent):
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


def snapshot_indexes(data_dir: Path, out_dir: Path) -> None:
    """Copy both index files and their sidecars from `data_dir` into `out_dir`,
    recording in each sidecar the fingerprint of the database they match.

    Safe while a server writes to `data_dir`: the copy holds the index files
    lock, so it sees no index write in flight. Raises `SnapshotRefused` when an
    index is missing or may disagree with the database."""
    database = data_dir / "mycelium.db"
    if not database.exists():
        raise SnapshotRefused(f"no database at {database}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (
        _flock(data_dir),
        contextlib.closing(
            sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        ) as conn,
    ):
        conn.row_factory = sqlite3.Row
        identities = [_snapshot_identity(data_dir / name) for name in _INDEXES]
        for (name, mapped), identity in zip(_INDEXES.items(), identities, strict=True):
            shutil.copyfile(data_dir / name, out_dir / name)
            _write_index_identity(out_dir / name, identity, fingerprint(mapped(conn)))


def _snapshot_identity(live: Path) -> str:
    if not live.exists():
        raise SnapshotRefused(f"{live} does not exist")
    if _dirty_marker_path(live).exists():
        # Left by a crashed or failed write; only a restart clears it.
        raise SnapshotRefused(f"{live} is marked dirty")
    identity = _read_index_identity(live)
    if identity in (_EARLIER_FORMAT, _INVALID_IDENTITY):
        raise SnapshotRefused(f"{live} has no current sidecar")
    return identity
