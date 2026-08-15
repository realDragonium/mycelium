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
    document_id = docs_store.upsert_document(
        conn,
        slug="written",
        title="Written",
        body="First body",
        run_id=written,
    )
    docs_store.finish_run(
        conn, written, outcome="document_written", document_id=document_id
    )
    written_row_before_rewrite = docs_store.get_run(conn, written)
    assert docs_store.status_for(written_row_before_rewrite) == "document_written"
    rewritten = docs_store.create_run(conn, prompt="rewritten", created_by="u1")
    docs_store.mark_started(conn, rewritten)
    rewritten_document_id = docs_store.upsert_document(
        conn,
        slug="written",
        title="Written",
        body="Second body",
        run_id=rewritten,
        updates=document_id,
        replacing=docs_store.body_digest("First body"),
    )
    assert rewritten_document_id == document_id
    docs_store.finish_run(
        conn,
        rewritten,
        outcome="document_written",
        document_id=rewritten_document_id,
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
    written_row_after_rewrite = docs_store.get_run(conn, written)
    rewritten_row = docs_store.get_run(conn, rewritten)
    assert docs_store.status_for(written_row_after_rewrite) == "document_superseded"
    assert docs_store.status_for(rewritten_row) == "document_written"
    assert docs_store.status_for(docs_store.get_run(conn, nothing)) == "nothing_written"
    assert docs_store.status_for(docs_store.get_run(conn, failed)) == "failed"
    assert docs_store.status_for(docs_store.get_run(conn, null_outcome)) == "failed"


def test_status_for_rejects_a_row_that_did_not_come_from_get_run(tmp_path):
    """Reject a foreign row shape before a queued status can hide the mistake."""
    conn = _conn(tmp_path)
    run_id = docs_store.create_run(conn, prompt="raw", created_by=None)
    raw_row = conn.execute(
        "SELECT * FROM documentation_runs WHERE id = ?", (run_id,)
    ).fetchone()

    with pytest.raises(
        ValueError, match="document_exists.*document_last_run_id.*get_run.*list_runs"
    ):
        docs_store.status_for(raw_row)
    assert docs_store.status_for(docs_store.get_run(conn, run_id)) == "queued"

    docs_store.finish_run(
        conn, run_id, outcome="document_written", document_id="gdc_missing"
    )
    raw_row = conn.execute(
        "SELECT * FROM documentation_runs WHERE id = ?", (run_id,)
    ).fetchone()

    with pytest.raises(
        ValueError, match="document_exists.*document_last_run_id.*get_run.*list_runs"
    ):
        docs_store.status_for(raw_row)
    assert docs_store.status_for(docs_store.get_run(conn, run_id)) == "document_written"


def test_a_failed_run_holding_another_runs_document_is_not_superseded(tmp_path):
    """A failed run cannot contradict its status by claiming supersession."""
    conn = _conn(tmp_path)
    run_a = docs_store.create_run(conn, prompt="write", created_by=None)
    document_id = docs_store.upsert_document(
        conn,
        slug="shared",
        title="Shared",
        body="Body",
        run_id=run_a,
    )
    docs_store.finish_run(
        conn, run_a, outcome="document_written", document_id=document_id
    )
    run_b = docs_store.create_run(conn, prompt="fail", created_by=None)
    docs_store.finish_run(
        conn,
        run_b,
        outcome="failed",
        document_id=document_id,
        error="boom",
    )

    row_b = docs_store.get_run(conn, run_b)
    assert docs_store.status_for(row_b) == "failed"
    assert docs_store.serialize_run(row_b)["document_superseded"] is False


def test_a_run_whose_document_row_is_gone_is_not_superseded(tmp_path):
    """A missing row cannot establish that another run replaced the document."""
    conn = _conn(tmp_path)
    missing = docs_store.create_run(conn, prompt="missing", created_by="u1")
    docs_store.mark_started(conn, missing)
    docs_store.finish_run(
        conn,
        missing,
        outcome="document_written",
        document_id="gdc_missing",
    )

    missing_row = docs_store.get_run(conn, missing)
    assert docs_store.status_for(missing_row) == "document_written"
    assert docs_store.serialize_run(missing_row)["document_superseded"] is False


def test_a_document_with_no_current_writer_still_leaves_an_earlier_run_superseded(
    tmp_path,
):
    """An existing unattributed row means the run no longer owns its body."""
    conn = _conn(tmp_path)
    no_writer = docs_store.create_run(conn, prompt="no writer", created_by="u1")
    docs_store.mark_started(conn, no_writer)
    document_id = docs_store.upsert_document(
        conn,
        slug="no-writer",
        title="No Writer",
        body="Body",
    )
    docs_store.finish_run(
        conn,
        no_writer,
        outcome="document_written",
        document_id=document_id,
    )

    no_writer_row = docs_store.get_run(conn, no_writer)
    assert docs_store.status_for(no_writer_row) == "document_superseded"
    assert docs_store.serialize_run(no_writer_row)["document_superseded"] is True


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


def test_upsert_document_refuses_to_replace_another_runs_body(tmp_path):
    """A title collision must not silently destroy an unrelated page."""
    conn = _conn(tmp_path)
    first_body = "# Getting started with SSO\n"
    document_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body=first_body,
        statement_ids=["stm_sso"],
        run_id="drn_first",
    )

    with pytest.raises(ValueError) as exc_info:
        docs_store.upsert_document(
            conn,
            slug="getting-started",
            title="Getting Started",
            guideline_set="kb-authoring",
            document_type="how-to",
            body="# Getting started with billing\n",
            statement_ids=["stm_billing"],
            run_id="drn_second",
        )

    message = str(exc_info.value)
    assert document_id in message
    assert "drn_first" in message
    assert "drn_second" in message
    assert "getting-started" in message
    documents = docs_store.list_documents(conn)
    assert len(documents) == 1
    document = docs_store.serialize_document(docs_store.get_document(conn, document_id))
    assert document["body"] == first_body
    assert document["last_run_id"] == "drn_first"
    assert document["statement_ids"] == ["stm_sso"]


def test_upsert_document_allows_the_same_run_to_rewrite_its_own_page(tmp_path):
    """A run may refine the page it already owns without declaring an update."""
    conn = _conn(tmp_path)
    first_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="First body",
        run_id="drn_first",
    )

    second_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="Second body",
        run_id="drn_first",
    )

    assert second_id == first_id
    assert docs_store.get_document(conn, first_id)["body"] == "Second body"


def test_upsert_document_allows_an_identical_rewrite_by_anyone(tmp_path):
    """Identical content cannot lose a page even when a new run claims it."""
    conn = _conn(tmp_path)
    body = "# Getting started with SSO\n"
    first_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body=body,
        run_id="drn_first",
    )

    second_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body=body,
        run_id="drn_second",
    )

    document = docs_store.get_document(conn, first_id)
    assert second_id == first_id
    assert document["last_run_id"] == "drn_second"


def test_upsert_document_allows_a_replacement_the_caller_asked_for(tmp_path):
    """An explicit target distinguishes a deliberate edit from a collision."""
    conn = _conn(tmp_path)
    first_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="First body",
        run_id="drn_first",
    )

    second_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="Second body",
        run_id="drn_second",
        updates=first_id,
        replacing=docs_store.body_digest("First body"),
    )

    document = docs_store.get_document(conn, first_id)
    assert second_id == first_id
    assert document["body"] == "Second body"
    assert document["last_run_id"] == "drn_second"


def test_upsert_document_refuses_to_replace_a_body_the_caller_never_saw(tmp_path):
    """A stale judgement must not destroy content written after it was made."""
    conn = _conn(tmp_path)
    body_a = "Body the stale caller saw"
    body_b = "Body written after the stale caller read"
    document_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body=body_a,
        run_id="drn_owner",
    )
    replacing = docs_store.body_digest(body_a)
    docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body=body_b,
        run_id="drn_owner",
    )

    with pytest.raises(ValueError) as exc_info:
        docs_store.upsert_document(
            conn,
            slug="getting-started",
            title="Getting Started",
            guideline_set="kb-authoring",
            document_type="how-to",
            body=body_a,
            run_id="drn_stale",
            updates=document_id,
            replacing=replacing,
        )

    assert document_id in str(exc_info.value)
    documents = docs_store.list_documents(conn)
    assert len(documents) == 1
    document = docs_store.get_document(conn, document_id)
    assert document["body"] == body_b
    assert document["last_run_id"] == "drn_owner"


def test_upsert_document_refuses_a_replacement_that_states_no_expectation(tmp_path):
    """Naming a target alone must not authorize the loss of its current body."""
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="First body",
        run_id="drn_first",
    )

    with pytest.raises(ValueError, match="replacing"):
        docs_store.upsert_document(
            conn,
            slug="getting-started",
            title="Getting Started",
            guideline_set="kb-authoring",
            document_type="how-to",
            body="Second body",
            run_id="drn_second",
            updates=document_id,
        )

    assert docs_store.get_document(conn, document_id)["body"] == "First body"


def test_upsert_document_refuses_an_expectation_that_names_no_document(tmp_path):
    """An expectation without a target cannot protect any known body."""
    conn = _conn(tmp_path)

    with pytest.raises(ValueError):
        docs_store.upsert_document(
            conn,
            slug="getting-started",
            title="Getting Started",
            guideline_set="kb-authoring",
            document_type="how-to",
            body="First body",
            run_id="drn_first",
            replacing=docs_store.body_digest("Expected body"),
        )

    assert docs_store.list_documents(conn) == []


def test_a_deliberate_replacement_carries_the_replacing_runs_review(tmp_path):
    """The stored review describes the body it accepted, so a deliberate
    replacement replaces the review with the body."""
    conn = _conn(tmp_path)
    first_review = {
        "exposure": {"status": "pass", "findings": []},
        "conformance": {"status": "pass", "findings": []},
        "attempts": 1,
        "passed": True,
    }
    second_review = {
        "exposure": {"status": "unchecked", "findings": []},
        "conformance": {"status": "pass", "findings": []},
        "attempts": 2,
        "passed": True,
    }
    first_run_id = "drn_first"
    second_run_id = "drn_second"

    first_id = docs_store.upsert_document(
        conn,
        slug="how-to-x",
        title="How to X",
        body="First body",
        review=first_review,
        run_id=first_run_id,
    )
    second_id = docs_store.upsert_document(
        conn,
        slug="how-to-x",
        title="How to X",
        body="Second body",
        review=second_review,
        run_id=second_run_id,
        updates=first_id,
        replacing=docs_store.body_digest("First body"),
    )

    documents = docs_store.list_documents(conn)
    assert len(documents) == 1
    document = docs_store.serialize_document(documents[0])
    assert first_run_id != second_run_id
    assert second_id == first_id
    assert document["body"] == "Second body"
    assert document["last_run_id"] == second_run_id
    assert document["review"] == second_review


def test_upsert_document_refuses_an_intent_that_names_the_wrong_document(tmp_path):
    """A stale or misplaced update target must never redirect a write."""
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn,
        slug="getting-started",
        title="Getting Started",
        guideline_set="kb-authoring",
        document_type="how-to",
        body="First body",
        run_id="drn_first",
    )

    with pytest.raises(ValueError):
        docs_store.upsert_document(
            conn,
            slug="getting-started",
            title="Getting Started",
            guideline_set="kb-authoring",
            document_type="how-to",
            body="Second body",
            run_id="drn_second",
            updates="gdc_somewhere_else",
            replacing=docs_store.body_digest("First body"),
        )

    document_count = len(docs_store.list_documents(conn))
    with pytest.raises(ValueError):
        docs_store.upsert_document(
            conn,
            slug="billing-overview",
            title="Billing Overview",
            guideline_set="kb-authoring",
            document_type="how-to",
            body="Billing body",
            run_id="drn_second",
            updates=document_id,
            replacing=docs_store.body_digest("First body"),
        )
    assert len(docs_store.list_documents(conn)) == document_count


def test_migrate_adds_review_to_an_existing_table_and_is_idempotent(tmp_path):
    """Upgrading a database preserves old pages and marks their review as
    unrecorded, while repeated startup migrations leave the schema usable."""
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    conn.execute(
        """
        CREATE TABLE generated_documents (
            id            TEXT PRIMARY KEY,
            slug          TEXT NOT NULL UNIQUE,
            title         TEXT NOT NULL,
            guideline_set TEXT,
            document_type TEXT,
            body          TEXT NOT NULL,
            statement_ids TEXT NOT NULL DEFAULT '[]',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            last_run_id   TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO generated_documents "
        "(id, slug, title, body, statement_ids, created_at, updated_at) "
        "VALUES ('gdc_old', 'old-page', 'Old page', 'Old body', '[]', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    docs_store.migrate(conn)
    docs_store.migrate(conn)

    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(generated_documents)")
    }
    rows = docs_store.list_documents(conn)
    assert "review" in columns
    assert len(rows) == 1
    assert rows[0]["id"] == "gdc_old"
    assert docs_store.serialize_document(rows[0])["review"] == {}


def test_upsert_document_updates_same_slug_in_place(tmp_path):
    conn = _conn(tmp_path)
    first_id = docs_store.upsert_document(
        conn, slug="topic", title="Old", body="Old body", run_id="drn_1"
    )
    created_at = docs_store.get_document(conn, first_id)["created_at"]

    second_id = docs_store.upsert_document(
        conn,
        slug="topic",
        title="New",
        body="New body",
        run_id="drn_2",
        updates=first_id,
        replacing=docs_store.body_digest("Old body"),
    )
    row = docs_store.get_document(conn, second_id)

    assert second_id == first_id
    assert row["created_at"] == created_at
    assert row["title"] == "New"
    assert row["body"] == "New body"
    assert row["last_run_id"] == "drn_2"
    assert len(docs_store.list_documents(conn)) == 1


def test_upsert_document_preserves_fields_a_later_write_omits(tmp_path):
    """Partial writers must not erase metadata recorded by an earlier stage."""
    conn = _conn(tmp_path)
    first_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="First",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=["stm_a", "stm_b"],
        review={"passed": True, "attempts": 1},
        run_id="drn_1",
    )

    second_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO (Revised)",
        body="Second",
        guideline_set="kb-authoring",
        document_type="how-to",
        run_id="drn_1",
    )
    document = docs_store.serialize_document(docs_store.get_document(conn, second_id))

    assert second_id == first_id
    assert document["title"] == "Configuring SSO (Revised)"
    assert document["body"] == "Second"
    assert document["statement_ids"] == ["stm_a", "stm_b"]
    assert document["review"] == {"passed": True, "attempts": 1}

    third_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO (Revised)",
        body="Second",
        guideline_set="kb-authoring",
        document_type="how-to",
    )
    document = docs_store.serialize_document(docs_store.get_document(conn, third_id))

    assert document["last_run_id"] == "drn_1"


def test_upsert_document_clears_a_field_only_when_the_caller_says_so(tmp_path):
    """Merge semantics must retain an intentional way to clear stale metadata."""
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="First",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=["stm_a", "stm_b"],
        review={"passed": True, "attempts": 1},
        run_id="drn_1",
    )

    docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="First",
        guideline_set="kb-authoring",
        document_type="how-to",
        statement_ids=[],
        review={},
        run_id="drn_1",
    )
    document = docs_store.serialize_document(docs_store.get_document(conn, document_id))

    assert document["statement_ids"] == []
    assert document["review"] == {}


def test_upsert_document_keeps_the_same_slug_apart_across_sets_and_types(tmp_path):
    """A slug follows from a title, and titles repeat. What makes two pages the
    same page is the slug together with the set and type they were written
    for — a tutorial's "Overview" is not a reference's."""
    conn = _conn(tmp_path)
    tutorial = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="The tutorial's overview",
        guideline_set="kb-authoring",
        document_type="tutorial",
    )
    reference = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="The reference's overview",
        guideline_set="kb-authoring",
        document_type="reference",
    )
    other_set = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="Another set's overview",
        guideline_set="api-docs",
        document_type="tutorial",
    )

    assert len({tutorial, reference, other_set}) == 3
    assert len(docs_store.list_documents(conn)) == 3
    assert docs_store.get_document(conn, tutorial)["body"] == "The tutorial's overview"
    assert (
        docs_store.get_document(conn, reference)["body"] == "The reference's overview"
    )


def test_upsert_document_still_updates_the_same_page_in_place(tmp_path):
    """A deliberate second pass at one page updates it instead of adding a row."""
    conn = _conn(tmp_path)
    first = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="First",
        guideline_set="kb-authoring",
        document_type="tutorial",
        run_id="drn_1",
    )
    second = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="Second",
        guideline_set="kb-authoring",
        document_type="tutorial",
        run_id="drn_2",
        updates=first,
        replacing=docs_store.body_digest("First"),
    )

    assert first == second
    assert len(docs_store.list_documents(conn)) == 1
    assert docs_store.get_document(conn, first)["body"] == "Second"


def test_migrating_a_pre_rekey_database_keeps_its_pages_and_applies_the_new_key(
    tmp_path,
):
    """The table this changes already exists in deployed databases, holding
    rows under a UNIQUE(slug) it no longer has.

    This is that table verbatim as the previous release created it, including
    a page whose set and type were never resolved — the case a NULL-tolerant
    unique key would quietly fail to constrain.
    """
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    conn.executescript(
        """
        CREATE TABLE generated_documents (
            id            TEXT PRIMARY KEY,
            slug          TEXT NOT NULL UNIQUE,
            title         TEXT NOT NULL,
            guideline_set TEXT,
            document_type TEXT,
            body          TEXT NOT NULL,
            statement_ids TEXT NOT NULL DEFAULT '[]',
            review        TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            last_run_id   TEXT
        );
        CREATE INDEX generated_documents_updated
            ON generated_documents (updated_at);
        INSERT INTO generated_documents
            (id, slug, title, guideline_set, document_type, body, statement_ids,
             review, created_at, updated_at, last_run_id)
        VALUES
            ('gdc_sso', 'configuring-sso', 'Configuring SSO', 'kb-authoring',
             'how-to', '# SSO', '["stm_1"]', '{"passed": true}',
             '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', 'drn_old'),
            ('gdc_overview', 'overview', 'Overview', NULL, NULL,
             'Legacy overview', '["stm_9"]', '{}',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL);
        """
    )
    conn.commit()

    docs_store.migrate(conn)
    docs_store.migrate(conn)

    rows = {row["id"]: row for row in docs_store.list_documents(conn)}
    assert set(rows) == {"gdc_sso", "gdc_overview"}
    assert rows["gdc_sso"]["body"] == "# SSO"
    assert rows["gdc_sso"]["created_at"] == "2026-01-01T00:00:00Z"
    assert rows["gdc_sso"]["last_run_id"] == "drn_old"
    assert docs_store.serialize_document(rows["gdc_sso"])["statement_ids"] == ["stm_1"]
    assert rows["gdc_overview"]["body"] == "Legacy overview"

    # The old page is still reachable and still updated in place by its own key.
    assert (
        docs_store.upsert_document(
            conn,
            slug="configuring-sso",
            title="Configuring SSO",
            body="# SSO\n\nRewritten",
            guideline_set="kb-authoring",
            document_type="how-to",
            updates="gdc_sso",
            replacing=docs_store.body_digest(rows["gdc_sso"]["body"]),
        )
        == "gdc_sso"
    )
    # And the slug alone no longer collapses two pages onto it.
    other = docs_store.upsert_document(
        conn,
        slug="configuring-sso",
        title="Configuring SSO",
        body="The tutorial",
        guideline_set="kb-authoring",
        document_type="tutorial",
    )
    assert other != "gdc_sso"
    assert len(docs_store.list_documents(conn)) == 3


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
        review={"passed": True, "attempts": 1},
    )

    summary = docs_store.serialize_document_summary(
        docs_store.get_document(conn, document_id)
    )

    assert "body" not in summary
    assert summary["chars"] == 4
    assert summary["statement_ids"] == ["stm_1"]
    assert summary["review"] == {"passed": True, "attempts": 1}


def test_get_document_by_slug(tmp_path):
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn, slug="topic", title="Topic", body="Body"
    )

    assert docs_store.get_document_by_slug(conn, "topic")["id"] == document_id
    assert docs_store.get_document_by_slug(conn, "unknown") is None


def test_get_document_by_slug_filters_identity_and_defaults_to_latest(tmp_path):
    """The slug-only compatibility lookup must be deterministic now that one
    slug can correctly name several pages."""
    conn = _conn(tmp_path)
    unresolved = docs_store.upsert_document(
        conn, slug="overview", title="Overview", body="Unresolved"
    )
    tutorial = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="Tutorial",
        guideline_set="kb-authoring",
        document_type="tutorial",
    )
    reference = docs_store.upsert_document(
        conn,
        slug="overview",
        title="Overview",
        body="Reference",
        guideline_set="kb-authoring",
        document_type="reference",
    )
    conn.executemany(
        "UPDATE generated_documents SET updated_at = ? WHERE id = ?",
        [
            ("2026-01-01T00:00:00.000Z", unresolved),
            ("2026-01-02T00:00:00.000Z", tutorial),
            ("2026-01-03T00:00:00.000Z", reference),
        ],
    )
    conn.commit()

    assert docs_store.get_document_by_slug(conn, "overview")["id"] == reference
    assert (
        docs_store.get_document_by_slug(conn, "overview", guideline_set="kb-authoring")[
            "id"
        ]
        == reference
    )
    assert (
        docs_store.get_document_by_slug(conn, "overview", document_type="tutorial")[
            "id"
        ]
        == tutorial
    )
    assert (
        docs_store.get_document_by_slug(
            conn,
            "overview",
            guideline_set="kb-authoring",
            document_type="tutorial",
        )["id"]
        == tutorial
    )
    assert (
        docs_store.get_document_by_slug(
            conn, "overview", guideline_set="", document_type=""
        )["id"]
        == unresolved
    )


def test_migrating_an_already_rekeyed_database_is_a_no_op(tmp_path):
    """The origin-sensitive detection must not rebuild the replacement table
    on every startup merely because its explicit identity index is unique."""
    conn = _conn(tmp_path)
    document_id = docs_store.upsert_document(
        conn, slug="topic", title="Topic", body="Body"
    )
    before_row = dict(docs_store.get_document(conn, document_id))
    before_schema = list(
        conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'generated_documents' ORDER BY type, name"
        )
    )

    docs_store.migrate(conn)
    docs_store.migrate(conn)

    assert dict(docs_store.get_document(conn, document_id)) == before_row
    assert (
        list(
            conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE tbl_name = 'generated_documents' ORDER BY type, name"
            )
        )
        == before_schema
    )

    identity_indexes = []
    for index in conn.execute("PRAGMA index_list(generated_documents)"):
        columns = [
            row["name"] for row in conn.execute(f"PRAGMA index_info({index['name']})")
        ]
        if index["unique"] and columns == [
            "guideline_set",
            "document_type",
            "slug",
        ]:
            identity_indexes.append((index["name"], index["origin"]))

    assert identity_indexes == [("generated_documents_identity", "c")]


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
