from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import zlib
from pathlib import Path

import numpy as np
import pytest

from mycelium import embed, phrasing, server, store
from mycelium.server import indexes, runtime

_DATABASES = ("mycelium.db", "mycelium-history.db")


def _embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


def _unexpected_embed(text: str) -> list[float]:
    raise AssertionError(f"index was rebuilt for {text}")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MENTION_WORKER", "1")
    data = tmp_path / "data"
    store.reset_substrate()
    runtime._ctx = None
    server.init(data)
    server.upsert_entity(name="workspace", description="a workspace")
    server.upsert_statement(kind="state", text="the workspace is active", links=[])
    return data


def _copy_databases(source: Path, target: Path) -> None:
    """What a Litestream restore leaves: the databases and nothing else."""
    target.mkdir()
    for name in _DATABASES:
        with (
            sqlite3.connect(source / name) as src,
            sqlite3.connect(target / name) as dst,
        ):
            src.backup(dst)


def _assert_index_matches_database() -> None:
    mapped = store.statement_vector_texts(store.substrate_connection())
    assert set(runtime._idx().ids()) == {row["vector_id"] for row in mapped}
    for row in mapped:
        expected = np.asarray(_embed(row["text"]), dtype=np.float32)
        stored = runtime._idx().get_vector(row["vector_id"])
        assert stored is not None
        np.testing.assert_allclose(
            stored, expected / np.linalg.norm(expected), atol=1e-5
        )


def _restore(snapshot: Path, databases: Path, target: Path) -> None:
    _copy_databases(databases, target)
    for item in snapshot.iterdir():
        shutil.copyfile(item, target / item.name)
    store.reset_substrate()
    runtime._ctx = None
    server.init(target)


def test_snapshot_of_the_restored_database_loads_without_re_embedding(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indexes.snapshot_indexes(data_dir, tmp_path / "snapshot")
    _copy_databases(data_dir, tmp_path / "databases")
    monkeypatch.setattr(embed, "embed", _unexpected_embed)

    _restore(tmp_path / "snapshot", tmp_path / "databases", tmp_path / "restored")

    _assert_index_matches_database()
    meta = json.loads(
        indexes._meta_path(runtime._idx_path()).read_text(encoding="utf-8")
    )
    assert "database" not in meta


@pytest.mark.parametrize("change", ["add", "edit", "delete"])
def test_snapshot_older_than_the_database_is_rebuilt(
    data_dir: Path, tmp_path: Path, change: str
) -> None:
    indexes.snapshot_indexes(data_dir, tmp_path / "snapshot")
    statement_id = (
        store.substrate_connection()
        .execute("SELECT id FROM statements")
        .fetchone()["id"]
    )
    if change == "add":
        server.upsert_statement(
            kind="event", text="an invoice export is queued", links=[]
        )
    elif change == "edit":
        server.patch_statement(statement_id, text="the workspace is archived")
    else:
        server.delete_statement(statement_id)
    _copy_databases(data_dir, tmp_path / "databases")

    _restore(tmp_path / "snapshot", tmp_path / "databases", tmp_path / "restored")

    _assert_index_matches_database()


def test_snapshot_waits_for_an_index_write_in_flight(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "an invoice export is queued"
    written = threading.Event()
    release = threading.Event()

    def write() -> None:
        with indexes._persisted_index_write(statements=True):
            server.upsert_statement(kind="event", text=text, links=[])
            written.set()
            release.wait()

    writer = threading.Thread(target=write)
    writer.start()
    written.wait()
    snapshotter = threading.Thread(
        target=indexes.snapshot_indexes, args=(data_dir, tmp_path / "snapshot")
    )
    snapshotter.start()
    snapshotter.join(timeout=0.2)
    assert snapshotter.is_alive()
    release.set()
    writer.join()
    snapshotter.join()
    _copy_databases(data_dir, tmp_path / "databases")
    monkeypatch.setattr(embed, "embed", _unexpected_embed)

    _restore(tmp_path / "snapshot", tmp_path / "databases", tmp_path / "restored")

    _assert_index_matches_database()
    assert any(
        row["text"] == text
        for row in store.statement_vector_texts(store.substrate_connection())
    )


def test_snapshot_refuses_a_dirty_index(data_dir: Path, tmp_path: Path) -> None:
    indexes._write_dirty_marker(runtime._name_idx_path())

    with pytest.raises(indexes.SnapshotRefused, match="dirty"):
        indexes.snapshot_indexes(data_dir, tmp_path / "snapshot")
    assert not any((tmp_path / "snapshot").iterdir())
