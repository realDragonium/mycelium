from __future__ import annotations

import contextlib
import sqlite3
import zlib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from mycelium import auth, embed, phrasing, server, store, vector
from mycelium.server import indexes, runtime


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
    runtime._ctx = None
    server.init(data_dir)


def _restart(data_dir: Path) -> None:
    runtime._ctx = None
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
        assert indexes._dirty_marker_path(path).exists()
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
        assert not indexes._dirty_marker_path(index_path).exists()
        events.clear()

    statement_path = runtime._idx_path()
    name_path = runtime._name_idx_path()

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
    assert_persisted(name_path)

    server.upsert_entity("reviewer", "an updated reviewer")
    assert all(event[0] != "persist" for event in events)
    assert not indexes._dirty_marker_path(name_path).exists()
    events.clear()

    name_id = server.upsert_name("assessor", entity_id)["name_id"]
    assert_persisted(name_path)

    server.rename_name(name_id, "evaluator")
    assert_persisted(name_path)


def test_draft_replay_clears_markers_only_after_outermost_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    drafter = auth.Principal(id="drafter", name="Drafter", role="drafter", type="human")
    principal_token = auth.current_principal.set(drafter)
    session_token = auth.current_session_id.set("index-persistence")
    try:
        receipt = server.upsert_entity(name="reviewer", description="a reviewer")
        server.upsert_statement(kind="state", text="the reviewer is ready", links=[])
    finally:
        auth.current_session_id.reset(session_token)
        auth.current_principal.reset(principal_token)

    events: list[tuple[str, str | None]] = []
    transaction_depth = 0
    original_transaction = store.transaction
    original_save = vector.Index.save
    original_clear_dirty_marker = indexes._clear_dirty_marker

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
        if index is runtime._idx():
            live_path = runtime._idx_path()
        elif index is runtime._name_idx():
            live_path = runtime._name_idx_path()
        else:
            raise AssertionError("unexpected index")
        assert indexes._dirty_marker_path(live_path).exists()
        events.append(("persist", path.name))
        original_save(index, path)

    def tracked_clear_dirty_marker(index_path: Path) -> None:
        events.append(("clear", index_path.name))
        original_clear_dirty_marker(index_path)

    monkeypatch.setattr(store, "transaction", tracked_transaction)
    monkeypatch.setattr(vector.Index, "save", tracked_save)
    monkeypatch.setattr(indexes, "_clear_dirty_marker", tracked_clear_dirty_marker)

    curator_token = auth.current_principal.set(auth.LOCAL_ADMIN)
    try:
        server.apply_draft(receipt["draft_id"])
    finally:
        auth.current_principal.reset(curator_token)

    commit_positions = [i for i, event in enumerate(events) if event[0] == "commit"]
    persist_positions = [i for i, event in enumerate(events) if event[0] == "persist"]
    clear_positions = [i for i, event in enumerate(events) if event[0] == "clear"]
    assert len(commit_positions) == 1
    # The pre-apply snapshot saves also count as persist events, so require
    # the LIVE .vec files explicitly or the assertion passes vacuously.
    persisted_files = {event[1] for event in events if event[0] == "persist"}
    assert runtime._idx_path().name in persisted_files
    assert runtime._name_idx_path().name in persisted_files
    assert all(position < commit_positions[0] for position in persist_positions)
    assert clear_positions
    assert all(position > commit_positions[0] for position in clear_positions)
    assert {event[1] for event in events if event[0] == "clear"} == {
        runtime._idx_path().name,
        runtime._name_idx_path().name,
    }
    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert not indexes._dirty_marker_path(runtime._name_idx_path()).exists()


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

    indexes._write_dirty_marker(runtime._idx_path())
    indexes._write_dirty_marker(runtime._name_idx_path())
    vector.Index.empty().save(runtime._idx_path())
    vector.Index.empty().save(runtime._name_idx_path())

    _restart(tmp_path)

    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert not indexes._dirty_marker_path(runtime._name_idx_path()).exists()
    assert runtime._idx().get_vector(statement_vector_id) is not None
    name_hits = runtime._name_idx().search(_embed("reviewer"), k=1)
    assert name_hits
    assert (
        store.get_name_id_by_vector_id(store.substrate_connection(), name_hits[0][0])
        == name_id
    )


def _outage(texts: list[str]) -> list[list[float]]:
    raise embed.EmbeddingError("provider unavailable")


def test_startup_requeues_mapped_vectors_the_indexes_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycelium import embedding_worker

    _init(tmp_path, monkeypatch)
    server.upsert_entity(name="workspace", description="a tenant")
    lost = server.upsert_statement(
        kind="state", text="the workspace is archived", links=[]
    )["statement_id"]
    kept = server.upsert_statement(kind="state", text="the invoice is paid", links=[])[
        "statement_id"
    ]
    conn = store.substrate_connection()
    kept_vector_id = store.get_vector_id(conn, kept)
    assert kept_vector_id is not None
    name_id = next(
        row["id"] for row in store.list_all_names(conn) if row["text"] == "workspace"
    )
    statements = vector.Index.empty()
    statements.add(kept_vector_id, _embed("the invoice is paid"))
    statements.save(runtime._idx_path())
    names = runtime._name_idx()
    name_vector_id = store.get_name_vector_id(conn, name_id)
    assert name_vector_id is not None
    names.delete(name_vector_id)
    names.save(runtime._name_idx_path())
    monkeypatch.setattr(embed, "embed", lambda text: _outage([text])[0])
    monkeypatch.setattr(embed, "embed_many", _outage)

    _restart(tmp_path)
    embedding_worker.run_pass(embedding_worker.Isolation())
    _restart(tmp_path)

    conn = store.substrate_connection()
    assert store.get_vector_id(conn, kept) == kept_vector_id
    assert {row.key for row in indexes.pending(10)} == {
        f"statement:{lost}",
        f"name:{name_id}",
    }

    monkeypatch.setattr(embed, "embed_many", lambda texts: [_embed(t) for t in texts])
    embedding_worker.run_pass(embedding_worker.Isolation())

    assert indexes.pending(10) == []
    healed = store.get_vector_id(conn, lost)
    assert healed is not None
    assert runtime._idx().search(_embed("the workspace is archived"), k=1)[0][0] == (
        healed
    )


def test_startup_compacts_and_prunes_what_no_mapping_reaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    statement_id = server.upsert_statement(
        kind="state", text="the export is queued", links=[]
    )["statement_id"]
    vector_id = store.get_vector_id(store.substrate_connection(), statement_id)
    assert vector_id is not None
    index = runtime._idx()
    index.add(998, _embed("a freed export"))
    index.delete(998)
    # The statement's id moves into the freed slot, as `add` once did, and its
    # old slot keeps answering searches for the old wording.
    index._index.add_items(
        np.asarray([_embed("the export is sent")], dtype=np.float32),
        np.array([vector_id]),
        replace_deleted=True,
    )
    index.add(999, _embed("an export nobody maps"))
    index.save(runtime._idx_path())
    monkeypatch.setattr(embed, "embed_many", _outage)

    _restart(tmp_path)

    persisted = vector.Index.load(runtime._idx_path())
    assert persisted.unreachable_slots() == 0
    assert persisted.live_ids() == {vector_id}
    assert [hit for hit, _ in persisted.search(_embed("the export is queued"), 5)] == [
        vector_id
    ]
    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()


def test_startup_rebuilds_an_index_from_empty_when_embedder_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed.reset()
    _init(tmp_path, monkeypatch)
    statement_id = server.upsert_statement(
        kind="state", text="the workspace is ready", links=[]
    )["statement_id"]
    statement_path = runtime._idx_path()
    runtime._idx().add(999, _embed("stranded legacy vector"))
    runtime._idx().save(statement_path)
    indexes._write_index_identity(statement_path, "openai/catalog-v2/768")

    _restart(tmp_path)

    vector_id = store.get_vector_id(store.substrate_connection(), statement_id)
    assert vector_id is not None
    assert runtime._idx().get_vector(vector_id) is not None
    assert 999 not in runtime._idx().ids()
    assert indexes._read_index_identity(statement_path) == embed.LEGACY_IDENTITY


def test_startup_loads_a_legacy_index_and_adds_its_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed.reset()
    _init(tmp_path, monkeypatch)
    statement_id = server.upsert_statement(
        kind="state", text="the workspace remains available", links=[]
    )["statement_id"]
    statement_path = runtime._idx_path()
    indexes._meta_path(statement_path).unlink()

    def unexpected_embed(text: str) -> list[float]:
        raise AssertionError(f"legacy index was rebuilt for {text}")

    monkeypatch.setattr(embed, "embed", unexpected_embed)
    _restart(tmp_path)

    vector_id = store.get_vector_id(store.substrate_connection(), statement_id)
    assert vector_id is not None
    assert runtime._idx().get_vector(vector_id) is not None
    assert indexes._read_index_identity(statement_path) == embed.LEGACY_IDENTITY


def test_startup_rebuilds_an_index_with_unreadable_identity_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed.reset()
    _init(tmp_path, monkeypatch)
    statement_path = runtime._idx_path()
    runtime._idx().add(999, _embed("stranded corrupt vector"))
    runtime._idx().save(statement_path)
    indexes._meta_path(statement_path).write_bytes(b"\xff")

    _restart(tmp_path)

    assert 999 not in runtime._idx().ids()
    assert indexes._read_index_identity(statement_path) == embed.LEGACY_IDENTITY


def test_persist_failure_marker_stays_sticky_until_restart(
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
        if path == runtime._idx_path():
            raise OSError("simulated index persistence failure")
        original_save(index, path)

    monkeypatch.setattr(store, "create_statement", capture_statement_id)
    monkeypatch.setattr(vector.Index, "save", fail_live_statement_save)

    with pytest.raises(OSError, match="simulated index persistence failure"):
        server.upsert_statement(kind="state", text="write is pending", links=[])

    assert len(created_ids) == 1
    assert indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert store.get_statement(store.substrate_connection(), created_ids[0]) is None

    monkeypatch.setattr(vector.Index, "save", original_save)
    successful_id = server.upsert_statement(
        kind="state", text="the later write succeeds", links=[]
    )["statement_id"]

    assert len(created_ids) == 2
    assert indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert store.get_statement(store.substrate_connection(), successful_id) is not None

    _restart(tmp_path)

    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert store.get_statement(store.substrate_connection(), created_ids[0]) is None
    assert store.get_statement(store.substrate_connection(), successful_id) is not None
    hits = server.search_statements("the later write succeeds", limit=5, name_boost=0.0)
    assert successful_id in {hit["id"] for hit in hits}


def test_failed_draft_replay_leaves_markers_until_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    drafter = auth.Principal(id="drafter", name="Drafter", role="drafter", type="human")
    principal_token = auth.current_principal.set(drafter)
    session_token = auth.current_session_id.set("failed-index-replay")
    try:
        receipt = server.upsert_entity(
            name="Replay Fixture", description="created only during replay"
        )
        server.upsert_statement(
            kind="state",
            text="the replay references a missing statement",
            links=[
                {
                    "to_id": "stm_nonexistent",
                    "link_type": "depends_on",
                }
            ],
        )
    finally:
        auth.current_session_id.reset(session_token)
        auth.current_principal.reset(principal_token)

    curator_token = auth.current_principal.set(auth.LOCAL_ADMIN)
    try:
        with pytest.raises(RuntimeError, match="failed during replay"):
            server.apply_draft(receipt["draft_id"])
    finally:
        auth.current_principal.reset(curator_token)

    assert indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert indexes._dirty_marker_path(runtime._name_idx_path()).exists()
    assert store.all_statements_with_text(store.substrate_connection()) == []
    assert store.list_all_names(store.substrate_connection()) == []
    assert runtime._idx().ids() == []
    assert runtime._name_idx().ids() == []

    _restart(tmp_path)

    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()
    assert not indexes._dirty_marker_path(runtime._name_idx_path()).exists()
    assert store.all_statements_with_text(store.substrate_connection()) == []
    assert store.list_all_names(store.substrate_connection()) == []
    assert runtime._idx().ids() == []
    assert runtime._name_idx().ids() == []


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
    original_write_dirty_marker = indexes._write_dirty_marker

    def track_save(index: vector.Index, path: Path) -> None:
        save_calls.append(path)
        original_save(index, path)

    def track_marker(index_path: Path) -> None:
        marker_writes.append(index_path)
        original_write_dirty_marker(index_path)

    monkeypatch.setattr(vector.Index, "save", track_save)
    monkeypatch.setattr(indexes, "_write_dirty_marker", track_marker)

    server.patch_statement(statement_id, kind="capability")

    assert save_calls == []
    assert marker_writes == []
    assert not indexes._dirty_marker_path(runtime._idx_path()).exists()
