from __future__ import annotations

import sqlite3

import pytest

from mycelium import auth, docs_store, server
from mycelium.ask import substrate


def _conn(tmp_path) -> sqlite3.Connection:
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    return conn


def test_status_derivation(tmp_path):
    conn = _conn(tmp_path)
    queued = docs_store.create_run(conn, prompt="queued", created_by="u1")
    running = docs_store.create_run(conn, prompt="running", created_by="u1")
    docs_store.mark_started(conn, running)
    written = docs_store.create_run(conn, prompt="written", created_by="u1")
    docs_store.mark_started(conn, written)
    docs_store.finish_run(
        conn, written, outcome="document_written", document_id="gdc_1"
    )
    nothing = docs_store.create_run(conn, prompt="nothing", created_by="u1")
    docs_store.mark_started(conn, nothing)
    docs_store.finish_run(conn, nothing, outcome="nothing_written")
    failed = docs_store.create_run(conn, prompt="failed", created_by="u1")
    docs_store.mark_started(conn, failed)
    docs_store.finish_run(conn, failed, outcome="failed", error="boom")
    null_outcome = docs_store.create_run(conn, prompt="null", created_by="u1")
    conn.execute(
        "UPDATE documentation_runs SET started_at = 's', finished_at = 'f' "
        "WHERE id = ?",
        (null_outcome,),
    )
    conn.commit()

    assert docs_store.status_for(docs_store.get_run(conn, queued)) == "queued"
    assert docs_store.status_for(docs_store.get_run(conn, running)) == "running"
    assert (
        docs_store.status_for(docs_store.get_run(conn, written)) == "document_written"
    )
    assert docs_store.status_for(docs_store.get_run(conn, nothing)) == "nothing_written"
    assert docs_store.status_for(docs_store.get_run(conn, failed)) == "failed"
    assert docs_store.status_for(docs_store.get_run(conn, null_outcome)) == "failed"


def test_finish_run_rejects_unknown_outcome(tmp_path):
    conn = _conn(tmp_path)
    run_id = docs_store.create_run(conn, prompt="prompt", created_by=None)

    with pytest.raises(ValueError, match="invalid outcome: unknown"):
        docs_store.finish_run(conn, run_id, outcome="unknown")


def test_finish_run_does_not_overwrite_finished_row(tmp_path):
    conn = _conn(tmp_path)
    run_id = docs_store.create_run(conn, prompt="prompt", created_by=None)
    docs_store.finish_run(
        conn, run_id, outcome="document_written", document_id="gdc_first"
    )
    first = docs_store.get_run(conn, run_id)

    docs_store.finish_run(conn, run_id, outcome="failed", error="later")
    row = docs_store.get_run(conn, run_id)

    assert row["finished_at"] == first["finished_at"]
    assert row["outcome"] == "document_written"
    assert row["document_id"] == "gdc_first"
    assert row["error"] is None


def test_mark_orphaned_flips_only_unfinished(tmp_path):
    conn = _conn(tmp_path)
    running = docs_store.create_run(conn, prompt="running", created_by=None)
    docs_store.mark_started(conn, running)
    queued = docs_store.create_run(conn, prompt="queued", created_by=None)
    finished = docs_store.create_run(conn, prompt="finished", created_by=None)
    docs_store.finish_run(conn, finished, outcome="failed", error="original")

    assert docs_store.mark_orphaned(conn) == 2

    for run_id in (running, queued):
        row = docs_store.get_run(conn, run_id)
        assert row["outcome"] == "failed"
        assert row["error"] == "orphaned by restart"
        assert row["finished_at"] is not None
    row = docs_store.get_run(conn, finished)
    assert row["outcome"] == "failed"
    assert row["error"] == "original"


def test_mark_started_resolves_fields_without_clearing_existing_values(tmp_path):
    conn = _conn(tmp_path)
    resolved = docs_store.create_run(conn, prompt="resolved", created_by=None)
    docs_store.mark_started(
        conn, resolved, guideline_set="guide", document_type="reference"
    )
    row = docs_store.get_run(conn, resolved)
    assert row["guideline_set"] == "guide"
    assert row["document_type"] == "reference"

    existing = docs_store.create_run(
        conn,
        prompt="existing",
        guideline_set="original-guide",
        document_type="original-type",
        created_by=None,
    )
    docs_store.mark_started(conn, existing, guideline_set=None, document_type=None)
    row = docs_store.get_run(conn, existing)
    assert row["guideline_set"] == "original-guide"
    assert row["document_type"] == "original-type"


def test_serialize_run_includes_status_and_prompt(tmp_path):
    conn = _conn(tmp_path)
    run_id = docs_store.create_run(conn, prompt="Write the page", created_by="u1")

    serialized = docs_store.serialize_run(docs_store.get_run(conn, run_id))

    assert serialized["status"] == "queued"
    assert serialized["prompt"] == "Write the page"


def test_upsert_document_inserts_and_round_trips_statement_ids(tmp_path):
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn,
        slug="topic",
        title="Topic",
        body="Body",
        statement_ids=["stm_1", "stm_2"],
        run_id="drn_1",
    )

    document = docs_store.serialize_document(docs_store.get_document(conn, document_id))
    assert document["statement_ids"] == ["stm_1", "stm_2"]
    assert document["last_run_id"] == "drn_1"


def test_upsert_document_updates_same_slug_in_place(tmp_path):
    conn = _conn(tmp_path)
    first_id = docs_store.upsert_document(
        conn, slug="topic", title="Old", body="Old body", run_id="drn_1"
    )
    created_at = docs_store.get_document(conn, first_id)["created_at"]

    second_id = docs_store.upsert_document(
        conn, slug="topic", title="New", body="New body", run_id="drn_2"
    )
    row = docs_store.get_document(conn, second_id)

    assert second_id == first_id
    assert row["created_at"] == created_at
    assert row["title"] == "New"
    assert row["body"] == "New body"
    assert row["last_run_id"] == "drn_2"
    assert len(docs_store.list_documents(conn)) == 1


def test_upsert_document_rejects_blank_slug_and_title(tmp_path):
    conn = _conn(tmp_path)

    with pytest.raises(ValueError, match="slug is required"):
        docs_store.upsert_document(conn, slug="  ", title="Title", body="Body")
    with pytest.raises(ValueError, match="title is required"):
        docs_store.upsert_document(conn, slug="topic", title="  ", body="Body")


def test_serialize_document_summary_omits_body(tmp_path):
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn,
        slug="topic",
        title="Topic",
        body="four",
        statement_ids=["stm_1"],
    )

    summary = docs_store.serialize_document_summary(
        docs_store.get_document(conn, document_id)
    )

    assert "body" not in summary
    assert summary["chars"] == 4
    assert summary["statement_ids"] == ["stm_1"]


def test_get_document_by_slug(tmp_path):
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn, slug="topic", title="Topic", body="Body"
    )

    assert docs_store.get_document_by_slug(conn, "topic")["id"] == document_id
    assert docs_store.get_document_by_slug(conn, "unknown") is None


def test_documentation_tools_registered():
    tool_names = {
        "list_documentation_runs",
        "get_documentation_run",
        "list_generated_documents",
        "get_generated_document",
    }
    names = {function.__name__ for function in server.TOOLS}

    assert tool_names <= names
    assert all(auth.required_role_for(name) == "reader" for name in tool_names)
    assert tool_names <= substrate._NON_READ_READER_TOOLS
