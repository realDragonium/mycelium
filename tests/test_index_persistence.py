from __future__ import annotations

import contextlib
import sqlite3
import zlib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from mycelium import embed, phrasing, server, store, vector


def _embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


def _no_phrasing_violations(
    text: str, kind: str | None = None
) -> list[phrasing.Violation]:
    return []


def _init(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setattr(phrasing, "check", _no_phrasing_violations)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MENTION_WORKER", "1")
    store.reset_substrate()
    server._ctx = None
    server.init(data_dir)


def _restart(data_dir: Path) -> None:
    server._ctx = None
    server.init(data_dir)


def test_index_persists_before_outermost_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    events: list[tuple[str, str | None]] = []
    transaction_depth = 0
    original_transaction = store.transaction
    original_save = vector.Index.save

    @contextlib.contextmanager
    def tracked_transaction(
        conn: sqlite3.Connection,
    ) -> Iterator[sqlite3.Connection]:
        nonlocal transaction_depth
        outermost = transaction_depth == 0
        transaction_depth += 1
        try:
            with original_transaction(conn) as transaction_conn:
                yield transaction_conn
            if outermost:
                events.append(("commit", None))
        finally:
            transaction_depth -= 1

    def tracked_save(index: vector.Index, path: Path) -> None:
        assert server._dirty_marker_path(path).exists()
        events.append(("persist", path.name))
        original_save(index, path)

    monkeypatch.setattr(store, "transaction", tracked_transaction)
    monkeypatch.setattr(vector.Index, "save", tracked_save)

    def assert_persisted(index_path: Path) -> None:
        persist = ("persist", index_path.name)
        commit = ("commit", None)
        assert persist in events
        assert commit in events
        assert events.index(persist) < events.index(commit)
        assert not server._dirty_marker_path(index_path).exists()
        events.clear()

    statement_path = server._idx_path()
    name_path = server._name_idx_path()

    server.upsert_statement(kind="state", text="alpha is ready", links=[])
    assert_persisted(statement_path)

    server.upsert_statements([{"kind": "state", "text": "beta is ready", "links": []}])
    assert_persisted(statement_path)

    merge_from = server.upsert_statement(
        kind="state", text="merge source is ready", links=[]
    )["statement_id"]
    merge_into = server.upsert_statement(
        kind="state", text="merge target is ready", links=[]
    )["statement_id"]
    events.clear()
    server.merge_statements(merge_from, merge_into)
    assert_persisted(statement_path)

    delete_id = server.upsert_statement(
        kind="state", text="delete target is ready", links=[]
    )["statement_id"]
    events.clear()
    server.delete_statement(delete_id)
    assert_persisted(statement_path)

    replace_id = server.upsert_statement(
        kind="state", text="old wording is active", links=[]
    )["statement_id"]
    events.clear()
    server.replace_text(replace_id, "new wording is active")
    assert_persisted(statement_path)

    entity_id = server.upsert_entity("reviewer", "a reviewer")["entity_id"]
    events.clear()
    name_id = server.upsert_name("assessor", entity_id)["name_id"]
    assert_persisted(name_path)

    server.rename_name(name_id, "evaluator")
    assert_persisted(name_path)


def test_startup_rebuilds_dirty_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    server.upsert_entity(name="reviewer", description="a reviewer")
    statement_id = server.upsert_statement(
        kind="state", text="the reviewer is screened", links=[]
    )["statement_id"]

    conn = store.substrate_connection()
    statement_vector_id = store.get_vector_id(conn, statement_id)
    name_row = next(
        row for row in store.list_all_names(conn) if row["text"] == "reviewer"
    )
    name_id = name_row["id"]
    name_vector_id = store.get_name_vector_id(conn, name_id)
    assert statement_vector_id is not None
    assert name_vector_id is not None

    server._write_dirty_marker(server._idx_path())
    server._write_dirty_marker(server._name_idx_path())
    vector.Index.empty().save(server._idx_path())
    vector.Index.empty().save(server._name_idx_path())

    _restart(tmp_path)

    assert not server._dirty_marker_path(server._idx_path()).exists()
    assert not server._dirty_marker_path(server._name_idx_path()).exists()
    assert server._idx().get_vector(statement_vector_id) is not None
    name_hits = server._name_idx().search(_embed("reviewer"), k=1)
    assert name_hits
    assert (
        store.get_name_id_by_vector_id(store.substrate_connection(), name_hits[0][0])
        == name_id
    )


def test_persist_failure_leaves_marker_and_restart_rebuilds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    original_save = vector.Index.save
    original_create_statement = store.create_statement
    created_ids: list[str] = []

    def capture_statement_id(conn: sqlite3.Connection, kind: str, text: str) -> str:
        statement_id = original_create_statement(conn, kind, text)
        created_ids.append(statement_id)
        return statement_id

    def fail_live_statement_save(index: vector.Index, path: Path) -> None:
        if path == server._idx_path():
            raise OSError("simulated index persistence failure")
        original_save(index, path)

    monkeypatch.setattr(store, "create_statement", capture_statement_id)
    monkeypatch.setattr(vector.Index, "save", fail_live_statement_save)

    with pytest.raises(OSError, match="simulated index persistence failure"):
        server.upsert_statement(kind="state", text="write is pending", links=[])

    assert len(created_ids) == 1
    assert server._dirty_marker_path(server._idx_path()).exists()
    assert store.get_statement(store.substrate_connection(), created_ids[0]) is None

    monkeypatch.setattr(vector.Index, "save", original_save)
    _restart(tmp_path)

    assert not server._dirty_marker_path(server._idx_path()).exists()
    assert store.get_statement(store.substrate_connection(), created_ids[0]) is None
    assert server._idx().search(_embed("write is pending"), k=1) == []


def test_kind_only_patch_does_not_mark_or_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    statement_id = server.upsert_statement(
        kind="state", text="the service is active", links=[]
    )["statement_id"]
    save_calls: list[Path] = []
    marker_writes: list[Path] = []
    original_save = vector.Index.save
    original_write_dirty_marker = server._write_dirty_marker

    def track_save(index: vector.Index, path: Path) -> None:
        save_calls.append(path)
        original_save(index, path)

    def track_marker(index_path: Path) -> None:
        marker_writes.append(index_path)
        original_write_dirty_marker(index_path)

    monkeypatch.setattr(vector.Index, "save", track_save)
    monkeypatch.setattr(server, "_write_dirty_marker", track_marker)

    server.patch_statement(statement_id, kind="capability")

    assert save_calls == []
    assert marker_writes == []
    assert not server._dirty_marker_path(server._idx_path()).exists()
