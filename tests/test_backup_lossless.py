"""Export → fresh instance → import is lossless across every database.

The first test is the guard that keeps backups complete: it enumerates the
tables of a populated instance rather than trusting a list, so a table added
to any schema fails here until it is either archived or declared in
`backup.UNARCHIVED_TABLES` with a reason — and until `instance_scenario`
puts a row in it, so the comparison is never vacuous.
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from contextlib import closing
from pathlib import Path

import pytest

import instance_scenario
from mycelium import auth, auth_store, backup, embed, phrasing, server, store

# Rows a restore rewrites on purpose, normalized to what the restore produces.
_RESTORED_DIFFERENTLY = {
    # GitHub App connections come back disconnected until an admin re-enables.
    ("mycelium-prompts.db", "github_app_connections"): lambda row: {
        **row,
        "body_json": json.dumps({**json.loads(row["body_json"]), "enabled": False}),
    },
}


@pytest.fixture
def populated(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", instance_scenario.embed)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    source = tmp_path / "source"
    ids = instance_scenario.populate(source)
    store.set_actor(None)
    yield source, ids
    server._ctx = None


def _tables(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]


def _rows(path: Path, table: str) -> list[dict]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def _comparable(rows: list[dict]) -> list[dict]:
    """Order-free, with JSON columns compared by value: settings sections are
    re-serialized through their models on restore."""

    def value(v):
        if isinstance(v, str) and v[:1] in "{[":
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v

    parsed = [{k: value(v) for k, v in row.items()} for row in rows]
    return sorted(parsed, key=lambda row: json.dumps(row, sort_keys=True, default=repr))


def test_every_table_survives_export_and_import_or_is_declared(populated, tmp_path):
    source, _ = populated
    archive = tmp_path / "instance.tar.gz"
    backup.export_substrate(source, archive)
    restored = tmp_path / "restored"
    backup.import_substrate(archive, restored)

    checked = []
    for db in sorted(source.glob("*.db")):
        unarchived = backup.UNARCHIVED_TABLES.get(db.name, {})
        tables = _tables(db)
        assert set(unarchived) <= set(tables), f"{db.name}: stale UNARCHIVED_TABLES"
        for table in tables:
            if table in unarchived:
                continue
            expected = _rows(db, table)
            assert expected, (
                f"{db.name}:{table} is empty in the scenario; add a row to "
                "tests/instance_scenario.py so its round trip is tested"
            )
            normalize = _RESTORED_DIFFERENTLY.get((db.name, table), lambda r: r)
            assert (restored / db.name).exists(), f"{db.name} was not restored"
            assert _comparable(_rows(restored / db.name, table)) == _comparable(
                [normalize(row) for row in expected]
            ), (
                f"{db.name}:{table} did not survive export → import; archive "
                "it or declare it in backup.UNARCHIVED_TABLES with a reason"
            )
            checked.append(table)
    assert {"knowledge_gaps", "users", "mcp_tokens", "drafts"} <= set(checked)


@pytest.mark.parametrize("include_vectors", [True, False])
def test_fresh_instance_from_an_export_serves_the_same_knowledge(
    populated, tmp_path, include_vectors
):
    source, ids = populated
    statement_ids = [ids[key] for key in instance_scenario.STATEMENTS]
    before = server.get_statements(statement_ids)

    archive = tmp_path / "instance.tar.gz"
    backup.export_substrate(source, archive, include_vectors=include_vectors)
    restored = tmp_path / "restored"
    backup.import_substrate(archive, restored)
    assert (restored / "mycelium.vec").exists() is include_vectors

    server._ctx = None
    server.init(restored)

    assert server.get_statements(statement_ids) == before
    for key, (_, text) in instance_scenario.STATEMENTS.items():
        hits = server.search_statements(text, limit=1, name_boost=0.0)
        assert [hit["id"] for hit in hits] == [ids[key]]
    names = server._name_idx().search(instance_scenario.embed("Sign-in"), k=1)
    assert store.get_name_id_by_vector_id(store.substrate_connection(), names[0][0])

    with closing(auth_store.connect(restored / "mycelium-auth.db")) as conn:
        principal = auth.resolve_token(conn, ids["token"])
    assert principal is not None and principal.role == "writer"


def _emails(data_dir: Path) -> set[str]:
    return {row["email"] for row in _rows(data_dir / "mycelium-auth.db", "users")}


def test_force_restore_replaces_only_the_sections_an_archive_carries(
    populated, tmp_path
):
    source, _ = populated
    archive = tmp_path / "instance.tar.gz"
    backup.export_substrate(source, archive)
    assert archive.stat().st_mode & 0o777 == 0o600

    without_auth = tmp_path / "without-auth.tar.gz"
    work = tmp_path / "work"
    work.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(work, filter="data")
    (work / "auth.jsonl").unlink()
    manifest = json.loads((work / "manifest.json").read_text())
    (work / "manifest.json").write_text(
        json.dumps({**manifest, "includes_auth": False})
    )
    with tarfile.open(without_auth, "w:gz") as tar:
        for item in sorted(work.iterdir()):
            tar.add(item, arcname=item.name)

    target = tmp_path / "target"
    backup.import_substrate(archive, target)
    with closing(auth_store.connect(target / "mycelium-auth.db")) as conn:
        auth.create_user(conn, name="Cy", role="reader", type="human", email="cy@x.io")
        conn.commit()

    backup.import_substrate(without_auth, target, force=True)
    assert _emails(target) == {"ada@example.com", "cy@x.io"}

    backup.import_substrate(archive, target, force=True)
    assert _emails(target) == {"ada@example.com"}
