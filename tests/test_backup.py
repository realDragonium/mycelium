"""Export → import round-trip tests.

Builds a small substrate, exports it, restores into a fresh data dir,
and verifies every row survives. Also covers the opt-out flags, the
fresh-dir refusal, the --force safety snapshot, and the prompt texts
that ride along with the substrate — every version of them, and what
happens when that part of the archive is missing or unreadable.
"""

from __future__ import annotations

import json
import logging
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

from mycelium import backup, prompt_store, store

# Build the substrate via the same store helpers normal writes go
# through, so audit columns and history events populate naturally.


@pytest.fixture(autouse=True)
def _reset_actor():
    store.set_actor(None)
    yield
    store.set_actor(None)


def _seed_substrate(data_dir):
    conn = store.connect(
        data_dir / "mycelium.db",
        history_path=data_dir / "mycelium-history.db",
    )
    store.migrate(conn)
    store.set_actor("alice")

    with store.transaction(conn):
        e1 = store.create_entity(conn, "Auth surface")
        e2 = store.create_entity(conn, None)
        n1 = store.create_name(conn, "Login", e1)
        n2 = store.create_name(conn, "Session", e2)

        b1 = store.create_statement(conn, "event", "user logs in")
        b2 = store.create_statement(conn, "event", "server issues a session token")
        store.replace_mentions(conn, b1, [n1])
        store.replace_mentions(conn, b2, [n2])
        store.insert_links(conn, [(b1, b2, "triggers", None)])
        store.insert_entity_links(conn, [(e1, e2, "contains")])

        # Edit to set updated_at, generating an additional history event.
        store.set_actor("bob")
        store.update_statement_text(conn, b1, "user authenticates")

    conn.close()
    return {
        "entities": [e1, e2],
        "names": [n1, n2],
        "statements": [b1, b2],
    }


def _seed_prompts(data_dir):
    """An edited doctrine (three versions) plus a retired guideline set —
    the two shapes a restore has to bring back: the newest text, and a name
    whose newest version is a tombstone."""
    conn = prompt_store.connect(data_dir / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    try:
        for text in ("packaged default", "operator edit", "sharper edit"):
            prompt_store.save(conn, type="doctrine", name="ingest", text=text)
        prompt_store.save(conn, type="guidelines", name="tutorial", text="g1")
        prompt_store.delete(conn, type="guidelines", name="tutorial")
    finally:
        conn.close()


def _prompt_rows(data_dir):
    conn = prompt_store.connect(data_dir / backup.PROMPTS_DB_NAME)
    try:
        return list(
            conn.execute(
                "SELECT * FROM prompt_texts ORDER BY type, name, version"
            ).fetchall()
        )
    finally:
        conn.close()


def _repack(archive: Path, work: Path, out: Path, mutate: Callable[[Path], None]):
    """Unpack `archive`, let `mutate` edit the extracted tree, repack to
    `out` — how a damaged or hand-edited archive is simulated."""
    work.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(work, filter="data")
    mutate(work)
    with tarfile.open(out, "w:gz") as tar:
        for item in sorted(work.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(work)))
    return out


def _row_count(data_dir, table, *, history=False):
    if history:
        conn = store.connect(
            data_dir / "mycelium.db",
            history_path=data_dir / "mycelium-history.db",
        )
        n = conn.execute(f"SELECT COUNT(*) AS n FROM history.{table}").fetchone()["n"]
    else:
        conn = store.connect(data_dir / "mycelium.db")
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    conn.close()
    return n


# --- export -----------------------------------------------------------------


def test_export_creates_archive_with_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    manifest = backup.export_substrate(src, archive)
    assert archive.exists()

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert "manifest.json" in names
    assert "data.jsonl" in names
    assert "history.jsonl" in names
    assert "vectors/" not in names  # no vector files were ever generated in seed

    assert manifest["schema_version"] == backup.SCHEMA_VERSION
    assert manifest["includes_history"] is True
    assert manifest["row_counts"]["entities"] == 2
    assert manifest["row_counts"]["statements"] == 2
    # The substrate emitted history events for every write above.
    assert manifest["row_counts"]["history_events"] > 0


def test_export_no_history_omits_history(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive, include_history=False)

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert "history.jsonl" not in names

    # manifest reflects the choice
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("manifest.json")
        assert member is not None
        manifest = json.loads(member.read())
    assert manifest["includes_history"] is False


# --- import -----------------------------------------------------------------


def test_round_trip_preserves_relational_data(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    ids = _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    # Same row counts on every table the seed populated.
    for table in (
        "entities",
        "names",
        "statements",
        "statement_mentions",
        "statement_links",
        "entity_links",
    ):
        assert _row_count(dst, table) == _row_count(src, table), table

    # Specific records survive with their ids and audit columns intact.
    conn = store.connect(dst / "mycelium.db")
    row = conn.execute(
        "SELECT * FROM statements WHERE id = ?", (ids["statements"][0],)
    ).fetchone()
    assert row["text"] == "user authenticates"
    assert row["created_by"] == "alice"
    assert row["updated_by"] == "bob"
    assert row["created_at"] is not None
    assert row["updated_at"] is not None
    conn.close()


def test_round_trip_preserves_history(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    assert _row_count(dst, "history_events", history=True) == _row_count(
        src, "history_events", history=True
    )


def test_import_refuses_existing_data_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    # First import succeeds.
    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    # Second one refuses without --force.
    with pytest.raises(FileExistsError):
        backup.import_substrate(archive, dst)


def test_import_force_clobbers_with_safety_snapshot(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    # Populate dst with substrate A, then restore over it with substrate B.
    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    # Now mutate dst so the safety snapshot has different content from src.
    conn = store.connect(dst / "mycelium.db", history_path=dst / "mycelium-history.db")
    store.set_actor("carol")
    store.create_statement(conn, "event", "extra row that only dst has")
    conn.close()

    # Force-restore the original archive.
    backup.import_substrate(archive, dst, force=True)

    # A safety snapshot landed next to dst.
    snapshots = list(dst.parent.glob(f"{dst.name}.before-restore.*.tar.gz"))
    assert len(snapshots) == 1

    # And dst now matches the archive again (the extra row is gone).
    n = _row_count(dst, "statements")
    assert n == _row_count(src, "statements")


def test_import_round_trip_with_no_history(tmp_path):
    """When the archive carries no history, the destination has no
    history table populated, but the rest restores fine."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive, include_history=False)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    # No history file was written.
    assert not (dst / "mycelium-history.db").exists()
    # But relational data is intact.
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_import_rejects_wrong_schema_version(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    # Rewrite manifest to claim a future schema_version.
    import shutil

    tampered = tmp_path / "tampered.tar.gz"
    work = tmp_path / "work"
    work.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(work, filter="data")
    manifest = json.loads((work / "manifest.json").read_text())
    manifest["schema_version"] = 999
    (work / "manifest.json").write_text(json.dumps(manifest))
    with tarfile.open(tampered, "w:gz") as tar:
        for item in sorted(work.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(work)))
    shutil.rmtree(work)

    dst = tmp_path / "dst"
    with pytest.raises(ValueError, match="schema_version"):
        backup.import_substrate(tampered, dst)


def test_import_skips_legacy_annotation_records(tmp_path, caplog):
    """Archives exported before the annotation subsystem was removed still
    carry annotation-kind records. Import must skip them (one info log),
    not error, and restore everything else."""
    import logging
    import shutil

    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    # Rebuild the archive with legacy annotation lines spliced into
    # data.jsonl, mimicking a pre-removal export.
    work = tmp_path / "work"
    work.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(work, filter="data")
    legacy_lines = [
        {"_kind": "annotation", "id": "ann_1", "kind": "note", "text": "legacy"},
        {
            "_kind": "statement_annotation",
            "statement_id": "stm_x",
            "annotation_id": "ann_1",
        },
        {"_kind": "entity_annotation", "entity_id": "ent_x", "annotation_id": "ann_1"},
        {"_kind": "annotation_mention", "annotation_id": "ann_1", "name_id": "nam_x"},
        {"_kind": "annotation_vector_id", "annotation_id": "ann_1", "vector_id": 0},
    ]
    with (work / "data.jsonl").open("a", encoding="utf-8") as fp:
        for line in legacy_lines:
            fp.write(json.dumps(line) + "\n")
    legacy_archive = tmp_path / "legacy.tar.gz"
    with tarfile.open(legacy_archive, "w:gz") as tar:
        for item in sorted(work.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(work)))
    shutil.rmtree(work)

    dst = tmp_path / "dst"
    with caplog.at_level(logging.INFO, logger="mycelium.backup"):
        backup.import_substrate(legacy_archive, dst)

    skip_logs = [r for r in caplog.records if "legacy annotation" in r.getMessage()]
    assert len(skip_logs) == 1
    assert "5" in skip_logs[0].getMessage()
    # Everything else restored.
    assert _row_count(dst, "statements") == _row_count(src, "statements")
    assert _row_count(dst, "entities") == _row_count(src, "entities")

    # An unknown kind that is NOT a legacy annotation kind still errors.
    work2 = tmp_path / "work2"
    work2.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(work2, filter="data")
    with (work2 / "data.jsonl").open("a", encoding="utf-8") as fp:
        fp.write(json.dumps({"_kind": "mystery", "id": "x"}) + "\n")
    bad_archive = tmp_path / "bad.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        for item in sorted(work2.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(work2)))
    with pytest.raises(ValueError, match="unknown record kind"):
        backup.import_substrate(bad_archive, tmp_path / "dst2")


# --- prompt texts -----------------------------------------------------------


def test_export_archives_every_prompt_text_version(tmp_path):
    """The store is append-only and the archive keeps it that way: five
    rows in, five rows out — superseded versions and the tombstone
    included, not one current row per name."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    manifest = backup.export_substrate(src, archive)

    with tarfile.open(archive, "r:gz") as tar:
        assert "prompts.jsonl" in set(tar.getnames())
    assert manifest["includes_prompts"] is True
    assert manifest["row_counts"]["prompt_texts"] == 5


def test_round_trip_preserves_prompt_text_history(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    # Row for row, column for column — ids and version numbers included.
    before = [dict(r) for r in _prompt_rows(src)]
    after = [dict(r) for r in _prompt_rows(dst)]
    assert after == before

    conn = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    try:
        # The edit is what the instance reads, not the seed it shipped with.
        assert prompt_store.latest_text(conn, "doctrine", "ingest") == "sharper edit"
        # A retired name stays retired: the tombstone rode along.
        assert prompt_store.latest(conn, "guidelines", "tutorial") is None
        assert [
            r["deleted"] for r in prompt_store.history(conn, "guidelines", "tutorial")
        ] == [1, 0]
    finally:
        conn.close()


def test_export_without_a_prompts_db_carries_no_prompts_section(tmp_path):
    """An instance that never wrote a prompt text — or an archive made
    before they existed — exports and imports as it always did."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)

    archive = tmp_path / "snap.tar.gz"
    manifest = backup.export_substrate(src, archive)

    with tarfile.open(archive, "r:gz") as tar:
        assert "prompts.jsonl" not in set(tar.getnames())
    assert manifest["includes_prompts"] is False
    assert "prompt_texts" not in manifest["row_counts"]

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)
    assert not (dst / backup.PROMPTS_DB_NAME).exists()
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_export_survives_an_unreadable_prompts_db(tmp_path, caplog):
    """The substrate is the payload. A prompts DB that will not open costs
    the archive its prompt texts and a warning, not the backup."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    (src / backup.PROMPTS_DB_NAME).write_bytes(b"this is not a database")

    archive = tmp_path / "snap.tar.gz"
    with caplog.at_level(logging.WARNING, logger="mycelium.backup"):
        manifest = backup.export_substrate(src, archive)

    assert manifest["includes_prompts"] is False
    with tarfile.open(archive, "r:gz") as tar:
        assert "prompts.jsonl" not in set(tar.getnames())
    assert any("prompt texts" in r.getMessage() for r in caplog.records)

    # And the substrate in that archive is intact.
    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_export_survives_a_prompt_row_json_cannot_hold(tmp_path, caplog):
    """The other way a prompts DB reads badly: SQLite hands back a BLOB
    where text belongs. The archive loses its prompts section, not the
    backup — scheduled backups and the pre-restore safety snapshot both
    come through here."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    conn = prompt_store.connect(src / backup.PROMPTS_DB_NAME)
    conn.execute(
        "INSERT INTO prompt_texts "
        "  (id, type, name, text, deleted, version, created_at) "
        "VALUES ('ptx_blob', 'doctrine', 'blob', ?, 0, 1, '2026-01-01T00:00:00Z')",
        (b"\x00\x01raw bytes",),
    )
    conn.close()

    archive = tmp_path / "snap.tar.gz"
    with caplog.at_level(logging.WARNING, logger="mycelium.backup"):
        manifest = backup.export_substrate(src, archive)

    assert manifest["includes_prompts"] is False
    assert any("prompt texts" in r.getMessage() for r in caplog.records)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_import_survives_an_unreadable_prompts_section(tmp_path, caplog):
    """Same posture on the way back in, and all-or-nothing: a damaged
    section leaves an empty store — which startup re-seeds — rather than a
    half-restored history or a failed restore."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    def _truncate_mid_history(work: Path) -> None:
        lines = (work / "prompts.jsonl").read_text(encoding="utf-8").splitlines()
        lines[2] = "{ this is not json"
        (work / "prompts.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    damaged = _repack(
        archive, tmp_path / "work", tmp_path / "damaged.tar.gz", _truncate_mid_history
    )

    dst = tmp_path / "dst"
    with caplog.at_level(logging.WARNING, logger="mycelium.backup"):
        backup.import_substrate(damaged, dst)

    assert any("prompt texts" in r.getMessage() for r in caplog.records)
    assert _prompt_rows(dst) == []  # rolled back, not partially applied
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_import_refuses_prompt_columns_the_table_does_not_have(tmp_path, caplog):
    """A row's column names reach the INSERT as text, so an archive that
    names something other than a `prompt_texts` column — a tampered one
    smuggling SQL, say — is refused before the statement is built, and the
    restore degrades to an empty store like any other damaged section."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    def _smuggle_a_column(work: Path) -> None:
        lines = (work / "prompts.jsonl").read_text(encoding="utf-8").splitlines()
        lines.append(
            json.dumps(
                {"_kind": "prompt_text", "id) VALUES ('x') --": "anything"},
            )
        )
        (work / "prompts.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tampered = _repack(
        archive, tmp_path / "work", tmp_path / "tampered.tar.gz", _smuggle_a_column
    )

    dst = tmp_path / "dst"
    with caplog.at_level(logging.WARNING, logger="mycelium.backup"):
        backup.import_substrate(tampered, dst)

    assert any("prompt texts" in r.getMessage() for r in caplog.records)
    assert _prompt_rows(dst) == []
    assert _row_count(dst, "statements") == _row_count(src, "statements")


def test_import_refuses_a_data_dir_holding_only_prompt_texts(tmp_path):
    """Steering texts left behind by a wiped substrate are still an
    instance. Restoring into them would merge two instances' configuration,
    so it takes the same --force as any other clobber, and the force starts
    the prompts from empty rather than on top."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    dst = tmp_path / "dst"
    dst.mkdir()
    conn = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    prompt_store.save(conn, type="doctrine", name="ingest", text="another instance")
    conn.close()

    with pytest.raises(FileExistsError):
        backup.import_substrate(archive, dst)

    backup.import_substrate(archive, dst, force=True)

    assert [dict(r) for r in _prompt_rows(dst)] == [dict(r) for r in _prompt_rows(src)]
    # No substrate was there to snapshot, so the force left no safety net.
    assert list(dst.parent.glob(f"{dst.name}.before-restore.*.tar.gz")) == []


def test_force_restore_replaces_prompt_texts(tmp_path):
    """A restore makes the data dir be the archive: the destination's own
    steering texts go, and the safety snapshot is where they went."""
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    _seed_prompts(src)

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)

    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)

    conn = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    prompt_store.save(conn, type="doctrine", name="ingest", text="local drift")
    conn.close()

    backup.import_substrate(archive, dst, force=True)

    conn = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    try:
        assert prompt_store.latest_text(conn, "doctrine", "ingest") == "sharper edit"
        assert len(prompt_store.history(conn, "doctrine", "ingest")) == 3
    finally:
        conn.close()

    # The drifted version is not lost — it is in the pre-restore snapshot.
    (snapshot,) = list(dst.parent.glob(f"{dst.name}.before-restore.*.tar.gz"))
    recovered = tmp_path / "recovered"
    backup.import_substrate(snapshot, recovered)
    conn = prompt_store.connect(recovered / backup.PROMPTS_DB_NAME)
    try:
        assert prompt_store.latest_text(conn, "doctrine", "ingest") == "local drift"
    finally:
        conn.close()
