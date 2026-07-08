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

    a1 = store.create_annotation(conn, "note", "default delay is 1 day")
    store.attach_annotations_to_statements(conn, [(b1, a1)])
    store.attach_annotations_to_entities(conn, [(e2, a1)])

    # Edit to ensure updated_at is set, generating an additional history event.
    store.set_actor("bob")
    store.update_statement_text(conn, b1, "user authenticates")

    conn.close()
    return {
        "entities": [e1, e2],
        "names": [n1, n2],
        "statements": [b1, b2],
        "annotations": [a1],
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
        "annotations",
        "statement_mentions",
        "statement_links",
        "entity_links",
        "statement_annotations",
        "entity_annotations",
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
