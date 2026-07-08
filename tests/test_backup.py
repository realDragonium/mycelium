"""Export → import round-trip tests.

Builds a small substrate, exports it, restores into a fresh data dir,
and verifies every row survives. Also covers the opt-out flags, the
fresh-dir refusal, and the --force safety snapshot.
"""

from __future__ import annotations

import json
import tarfile

import pytest

from mycelium import backup, store

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
