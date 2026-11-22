from __future__ import annotations

import json
import tarfile
from contextlib import closing

import pytest

from mycelium import backup, docs_store, documentation_archive, store


def test_document_history_and_publication_roundtrip_without_draft_operations(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with closing(store.connect(source / "mycelium.db")) as conn:
        store.migrate(conn)
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        conn.execute("CREATE TABLE private_draft_operations (secret TEXT)")
        conn.execute("INSERT INTO private_draft_operations VALUES ('excluded')")
        conn.commit()
        run = docs_store.create_run(
            conn,
            prompt="Explain invitations",
            created_by="writer",
            reasoning_effort="high",
        )
        document = docs_store.upsert_document(
            conn, slug="invitations", title="Invitations", body="First", run_id=run
        )
        docs_store.record_delivery(
            conn,
            document,
            destination="docs",
            binding="approved",
            target=json.dumps(
                {
                    "host": "github.com",
                    "owner": "example",
                    "repo": "docs",
                    "base_branch": "main",
                }
            ),
            path="docs/invitations.md",
            reference="https://github.com/example/docs/pull/1",
            content_revision="sha",
            revision=1,
        )
        docs_store.upsert_document(
            conn,
            slug="invitations",
            title="Invitations",
            body="Second",
            updates=document,
            replacing=docs_store.body_digest("First"),
            expected_revision=1,
        )
        docs_store.finish_run(
            conn, run, outcome="document_written", document_id=document
        )
        expected = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in documentation_archive.TABLES
        }
    archive = tmp_path / "backup.tar.gz"
    manifest = backup.export_substrate(source, archive, include_vectors=False)
    assert manifest["includes_documentation"] is True
    with tarfile.open(archive) as tar:
        data = tar.extractfile("documentation.json")
        assert data is not None
        assert b"excluded" not in data.read()
    restored = tmp_path / "restored"
    backup.import_substrate(archive, restored)
    with closing(docs_store.connect(restored / documentation_archive.DB_NAME)) as conn:
        actual = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in documentation_archive.TABLES
        }
        assert actual == expected
        current = docs_store.serialize_document(docs_store.get_document(conn, document))
        assert current["delivery_status"] == "changes_pending"
        assert current["published_revision"] == 1
        assert docs_store.get_revision(conn, document, 1)["body"] == "First"
        assert docs_store.get_revision(conn, document, 2)["body"] == "Second"


@pytest.mark.parametrize(
    "fault", ["missing", "bad-column", "missing-head", "bad-target", "wrong-title"]
)
def test_invalid_document_section_refuses_before_force_restore(tmp_path, fault):
    source, target, staging = (
        tmp_path / name for name in ("source", "target", "staging")
    )
    for folder in (source, target, staging):
        folder.mkdir()
    for folder in (source, target):
        with closing(store.connect(folder / "mycelium.db")) as conn:
            store.migrate(conn)
    original = (target / "mycelium.db").read_bytes()
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        docs_store.upsert_document(conn, slug="page", title="Page", body="Body")
    archive = tmp_path / "source.tar.gz"
    backup.export_substrate(source, archive, include_vectors=False)
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    section = staging / documentation_archive.FILE_NAME
    if fault == "missing":
        section.unlink()
    else:
        payload = json.loads(section.read_text())
        if fault == "bad-column":
            payload["tables"]["generated_documents"][0]["malicious_column"] = "no"
        elif fault == "bad-target":
            payload["tables"]["generated_documents"][0]["delivery_target"] = (
                "invalid JSON"
            )
        elif fault == "wrong-title":
            payload["tables"]["generated_documents"][0]["title"] = "Changed head only"
        else:
            payload["tables"]["generated_document_revisions"] = []
        section.write_text(json.dumps(payload))
    broken = tmp_path / "broken.tar.gz"
    backup._make_archive(staging, broken)
    with pytest.raises(ValueError):
        backup.import_substrate(broken, target, force=True)
    assert (target / "mycelium.db").read_bytes() == original


def test_unreadable_document_database_fails_export(tmp_path):
    with closing(store.connect(tmp_path / "mycelium.db")) as conn:
        store.migrate(conn)
    (tmp_path / documentation_archive.DB_NAME).write_text("corrupt")
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError):
        backup.export_substrate(
            tmp_path, tmp_path / "bad.tar.gz", include_vectors=False
        )


def test_restore_requires_force_for_document_only_target(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    with closing(store.connect(source / "mycelium.db")) as conn:
        store.migrate(conn)
    with closing(docs_store.connect(target / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        document = docs_store.upsert_document(
            conn, slug="kept", title="Kept", body="Keep this"
        )
    archive = tmp_path / "backup.tar.gz"
    backup.export_substrate(source, archive, include_vectors=False)
    with pytest.raises(FileExistsError):
        backup.import_substrate(archive, target)
    with closing(docs_store.connect(target / documentation_archive.DB_NAME)) as conn:
        assert docs_store.get_document(conn, document)["body"] == "Keep this"


def test_unresolved_legacy_destination_remains_restorable(tmp_path):
    source, staging = tmp_path / "source", tmp_path / "staging"
    source.mkdir()
    staging.mkdir()
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        document = docs_store.upsert_document(
            conn, slug="legacy", title="Legacy", body="Body"
        )
        conn.execute(
            "UPDATE generated_documents SET delivery_destination = 'retired', delivery_target = '{}' WHERE id = ?",
            (document,),
        )
        conn.commit()
        documentation_archive.write(conn, staging)
    prepared = documentation_archive.prepare(staging, required=True)
    assert prepared is not None
    with closing(docs_store.connect(prepared)) as conn:
        row = docs_store.get_document(conn, document)
        assert row["delivery_target"] == "{}"
        assert row["delivery_binding"] is None


def test_force_restore_refuses_unrecoverable_document_only_target(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    with closing(store.connect(source / "mycelium.db")) as conn:
        store.migrate(conn)
    with closing(docs_store.connect(target / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        document = docs_store.upsert_document(
            conn, slug="only-copy", title="Only copy", body="Keep"
        )
    archive = tmp_path / "backup.tar.gz"
    backup.export_substrate(source, archive, include_vectors=False)
    with pytest.raises(ValueError, match="Cannot safely overwrite documentation"):
        backup.import_substrate(archive, target, force=True)
    assert not (target / "mycelium.db").exists()
    with closing(docs_store.connect(target / documentation_archive.DB_NAME)) as conn:
        assert docs_store.get_document(conn, document)["body"] == "Keep"


@pytest.mark.parametrize(
    "field", ["delivery_path", "delivery_target", "delivery_binding"]
)
def test_archive_rejects_publication_that_disagrees_with_receipt(tmp_path, field):
    source, staging = tmp_path / "source", tmp_path / "staging"
    source.mkdir()
    staging.mkdir()
    target = json.dumps(
        {
            "host": "github.com",
            "owner": "example",
            "repo": "docs",
            "base_branch": "main",
        }
    )
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        document = docs_store.upsert_document(
            conn, slug="page", title="Page", body="Body"
        )
        docs_store.record_delivery(
            conn,
            document,
            destination="docs",
            binding="approved",
            target=target,
            path="docs/page.md",
            reference="https://github.com/example/docs/pull/1",
            content_revision="sha",
            revision=1,
        )
        documentation_archive.write(conn, staging)
    path = staging / documentation_archive.FILE_NAME
    payload = json.loads(path.read_text())
    # Equivalent coordinate JSON stays valid despite different whitespace/key order.
    payload["tables"]["generated_documents"][0]["delivery_target"] = json.dumps(
        json.loads(target), sort_keys=True, indent=2
    )
    path.write_text(json.dumps(payload))
    assert documentation_archive.prepare(staging, required=True) is not None
    (staging / "documentation-validated.db").unlink()
    payload["tables"]["generated_documents"][0][field] = (
        json.dumps({**json.loads(target), "repo": "different"})
        if field == "delivery_target"
        else "different"
    )
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="differs from its receipt"):
        documentation_archive.prepare(staging, required=True)


def test_an_archive_from_before_plans_restores_without_them(tmp_path):
    source, staging = tmp_path / "source", tmp_path / "staging"
    source.mkdir()
    staging.mkdir()
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        docs_store.upsert_document(conn, slug="page", title="Page", body="Body")
        documentation_archive.write(conn, staging)
    section = staging / documentation_archive.FILE_NAME
    payload = json.loads(section.read_text())
    for table in (
        "documentation_plans",
        "documentation_plan_items",
        "documentation_plan_dismissals",
        "document_maintenance",
        "agent_tasks",
    ):
        del payload["tables"][table]
    section.write_text(json.dumps({**payload, "version": 1}))

    prepared = documentation_archive.prepare(staging, required=True)

    assert prepared is not None
    with closing(docs_store.connect(prepared)) as conn:
        assert (
            conn.execute("SELECT title FROM generated_documents").fetchone()[0]
            == "Page"
        )


def _flow_json() -> dict:
    from mycelium.docgen import flows
    from mycelium.docgen.schema import StoredFlow

    class Chain:
        def statement(self, statement_id):
            return flows.FlowStatement("event", "An invoice is exported.")

        def links(self, statement_id):
            return []

    drawing = flows.draw_flow(Chain(), "stm_exported")
    assert drawing is not None
    return StoredFlow(
        name="export-steps", title="Export steps", start="stm_exported", drawing=drawing
    ).model_dump(mode="json")


def _archive_with_flows(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with closing(store.connect(source / "mycelium.db")) as conn:
        store.migrate(conn)
    body = "An [[Invoice]] is exported.\n\n```flow\nexport-steps\n```\n"
    links = [{"name": "Invoice", "entity_id": "ent_invoice"}]
    with closing(docs_store.connect(source / documentation_archive.DB_NAME)) as conn:
        docs_store.migrate(conn)
        document = docs_store.upsert_document(
            conn,
            slug="exports",
            title="Exports",
            body=body,
            statement_ids=["stm_exported"],
            concept_links=links,
            flows=[_flow_json()],
        )
        run = docs_store.create_run(conn, prompt="Explain exports", created_by=None)
        docs_store.finish_run(
            conn,
            run,
            outcome="nothing_written",
            draft_title="Exports",
            draft_body=body,
            draft_concept_links=links,
            draft_flows=[_flow_json()],
        )
    archive = tmp_path / "backup.tar.gz"
    backup.export_substrate(source, archive, include_vectors=False)
    return archive, document, run


def test_links_and_flows_travel_with_revisions_and_refused_drafts(tmp_path):
    archive, document, run = _archive_with_flows(tmp_path)
    restored = tmp_path / "restored"

    backup.import_substrate(archive, restored)

    with closing(docs_store.connect(restored / documentation_archive.DB_NAME)) as conn:
        revision = docs_store.get_revision(conn, document, 1)
        expected = {
            "concept_links": [{"name": "Invoice", "entity_id": "ent_invoice"}],
            "flows": [_flow_json()],
        }
        assert docs_store.links_and_flows(revision) == expected
        assert docs_store.draft_links_and_flows(docs_store.get_run(conn, run)) == (
            expected
        )


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("generated_document_revisions", "flows", '[{"name": "export-steps"}]'),
        ("generated_document_revisions", "concept_links", '[{"name": "Invoice"}]'),
        ("documentation_runs", "draft_flows", "not json"),
        ("generated_document_revisions", "flows", "twice"),
    ],
)
def test_an_archive_with_unreadable_links_or_flows_is_refused(
    tmp_path, table, column, value
):
    archive, _document, _run = _archive_with_flows(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    section = staging / documentation_archive.FILE_NAME
    payload = json.loads(section.read_text())
    if value == "twice":
        value = json.dumps([_flow_json(), _flow_json()])
    payload["tables"][table][0][column] = value
    section.write_text(json.dumps(payload))
    broken = tmp_path / "broken.tar.gz"
    backup._make_archive(staging, broken)

    with pytest.raises(ValueError, match=r"links or flows|flow name twice"):
        backup.import_substrate(broken, tmp_path / "restored")
