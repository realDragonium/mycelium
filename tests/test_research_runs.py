from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from mycelium import research_runs, research_store


@pytest.fixture(autouse=True)
def _reset_research_runs():
    research_runs.RUNNER = None
    research_runs._threads.clear()
    yield
    research_runs.wait_all()
    research_runs.RUNNER = None
    research_runs._threads.clear()


def _conn(tmp_path) -> sqlite3.Connection:
    conn = research_store.connect(tmp_path / "mycelium-drafts.db")
    research_store.migrate(conn)
    return conn


def _result(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(model_dump=lambda: payload)


def test_status_derivation(tmp_path):
    conn = _conn(tmp_path)

    queued = research_store.create_run(
        conn, topic="queued", source="manual", created_by="u1"
    )
    running = research_store.create_run(
        conn, topic="running", source="manual", created_by="u1"
    )
    research_store.mark_started(conn, running)
    draft = research_store.create_run(
        conn, topic="draft", source="manual", created_by="u1"
    )
    research_store.mark_started(conn, draft)
    research_store.finish_run(conn, draft, outcome="draft_created", draft_id="drf_1")
    nothing = research_store.create_run(
        conn, topic="nothing", source="manual", created_by="u1"
    )
    research_store.mark_started(conn, nothing)
    research_store.finish_run(conn, nothing, outcome="nothing_found", error="no hits")
    failed = research_store.create_run(
        conn, topic="failed", source="manual", created_by="u1"
    )
    research_store.mark_started(conn, failed)
    research_store.finish_run(conn, failed, outcome="failed", error="boom")
    null_outcome = research_store.create_run(
        conn, topic="null", source="manual", created_by="u1"
    )
    conn.execute(
        "UPDATE research_runs SET started_at = 's', finished_at = 'f' WHERE id = ?",
        (null_outcome,),
    )
    conn.commit()

    assert research_store.status_for(research_store.get_run(conn, queued)) == "queued"
    assert research_store.status_for(research_store.get_run(conn, running)) == "running"
    assert (
        research_store.status_for(research_store.get_run(conn, draft))
        == "draft_created"
    )
    assert (
        research_store.status_for(research_store.get_run(conn, nothing))
        == "nothing_found"
    )
    assert research_store.status_for(research_store.get_run(conn, failed)) == "failed"
    assert (
        research_store.status_for(research_store.get_run(conn, null_outcome))
        == "failed"
    )


def test_create_before_thread_and_finish_draft_created(tmp_path):
    conn = _conn(tmp_path)
    release = threading.Event()

    def runner(topic, *, source):
        release.wait()
        return _result({"outcome": "draft_created", "draft_id": "drf_abc"})

    run_id = research_runs.start_run(
        topic="topic",
        source="manual",
        created_by="u1",
        data_dir=tmp_path,
        conn=conn,
        runner=runner,
    )
    row = research_store.get_run(conn, run_id)
    assert row is not None
    assert research_store.status_for(row) == "running"

    release.set()
    research_runs.wait_all()
    row = research_store.get_run(conn, run_id)
    assert row["outcome"] == "draft_created"
    assert row["draft_id"] == "drf_abc"
    assert row["trace_ref"].endswith("research_trace.jsonl")


def test_nothing_found_reason_in_error_column(tmp_path):
    conn = _conn(tmp_path)

    run_id = research_runs.start_run(
        topic="topic",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=lambda topic, *, source: {
            "outcome": "nothing_found",
            "reason": "no sources",
        },
    )

    research_runs.wait_all()
    row = research_store.get_run(conn, run_id)
    assert row["outcome"] == "nothing_found"
    assert row["error"] == "no sources"


def test_runner_exception_marks_failed(tmp_path):
    conn = _conn(tmp_path)

    def runner(topic, *, source):
        raise RuntimeError("bad crawl")

    run_id = research_runs.start_run(
        topic="topic",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=runner,
    )

    research_runs.wait_all()
    row = research_store.get_run(conn, run_id)
    assert row["outcome"] == "failed"
    assert "RuntimeError: bad crawl" in row["error"]
    assert row["finished_at"] is not None


def test_capacity_refuses_when_at_max(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv(research_runs.MAX_ACTIVE_ENV, "2")
    release = threading.Event()

    def runner(topic, *, source):
        release.wait()
        return {"outcome": "nothing_found", "reason": "done"}

    run1 = research_runs.start_run(
        topic="one",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=runner,
    )
    run2 = research_runs.start_run(
        topic="two",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=runner,
    )
    assert {
        research_store.status_for(research_store.get_run(conn, run1)),
        research_store.status_for(research_store.get_run(conn, run2)),
    } == {"running"}

    with pytest.raises(ValueError, match="max 2"):
        research_runs.start_run(
            topic="three",
            source="manual",
            created_by=None,
            data_dir=tmp_path,
            conn=conn,
            runner=runner,
        )

    release.set()
    research_runs.wait_all()
    run3 = research_runs.start_run(
        topic="three",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=lambda topic, *, source: {"outcome": "nothing_found", "reason": "done"},
    )
    research_runs.wait_all()
    assert (
        research_store.status_for(research_store.get_run(conn, run3)) == "nothing_found"
    )


def test_bound_is_db_derived(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv(research_runs.MAX_ACTIVE_ENV, "1")
    run_id = research_store.create_run(
        conn, topic="stranded", source="manual", created_by=None
    )
    research_store.mark_started(conn, run_id)

    with pytest.raises(ValueError, match="max 1"):
        research_runs.start_run(
            topic="new",
            source="manual",
            created_by=None,
            data_dir=tmp_path,
            conn=conn,
            runner=lambda topic, *, source: {"outcome": "nothing_found"},
        )


def test_concurrent_starts_race_one_wins(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv(research_runs.MAX_ACTIVE_ENV, "1")
    release = threading.Event()
    barrier = threading.Barrier(2)
    errors = []
    run_ids = []

    def runner(topic, *, source):
        release.wait()
        return {"outcome": "nothing_found", "reason": "done"}

    def start():
        barrier.wait()
        try:
            run_ids.append(
                research_runs.start_run(
                    topic="topic",
                    source="manual",
                    created_by=None,
                    data_dir=tmp_path,
                    conn=conn,
                    runner=runner,
                )
            )
        except ValueError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(run_ids) == 1
    assert len(errors) == 1
    assert "max 1" in str(errors[0])

    release.set()
    research_runs.wait_all()


def test_mark_orphaned_flips_only_unfinished(tmp_path):
    conn = _conn(tmp_path)
    unfinished = research_store.create_run(
        conn, topic="unfinished", source="manual", created_by=None
    )
    research_store.mark_started(conn, unfinished)
    finished = research_store.create_run(
        conn, topic="finished", source="manual", created_by=None
    )
    research_store.mark_started(conn, finished)
    research_store.finish_run(conn, finished, outcome="nothing_found", error="original")
    queued = research_store.create_run(
        conn, topic="queued", source="manual", created_by=None
    )

    # Both the running row AND the stranded queued row are swept: at startup
    # no worker thread can exist, so any unfinished row is an orphan.
    assert research_store.mark_orphaned(conn) == 2

    unfinished_row = research_store.get_run(conn, unfinished)
    assert research_store.status_for(unfinished_row) == "failed"
    assert unfinished_row["error"] == "orphaned by restart"
    assert (
        research_store.status_for(research_store.get_run(conn, finished))
        == "nothing_found"
    )
    assert research_store.get_run(conn, finished)["error"] == "original"
    assert research_store.status_for(research_store.get_run(conn, queued)) == "failed"


def test_explicit_runner_beats_module_override(tmp_path):
    """An explicitly passed runner wins over the module-level RUNNER hook;
    RUNNER only fills in when no runner is passed (how HTTP tests use it)."""
    conn = _conn(tmp_path)
    called = []

    def module_runner(topic, *, source):
        called.append("module")
        return {"outcome": "nothing_found", "reason": "module"}

    def kwarg_runner(topic, *, source):
        called.append("kwarg")
        return {"outcome": "nothing_found", "reason": "kwarg"}

    research_runs.RUNNER = module_runner
    run_id = research_runs.start_run(
        topic="topic",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
        runner=kwarg_runner,
    )
    research_runs.wait_all()
    assert called == ["kwarg"]
    assert research_store.get_run(conn, run_id)["error"] == "kwarg"

    called.clear()
    run_id2 = research_runs.start_run(
        topic="topic2",
        source="manual",
        created_by=None,
        data_dir=tmp_path,
        conn=conn,
    )
    research_runs.wait_all()
    assert called == ["module"]
    assert research_store.get_run(conn, run_id2)["error"] == "module"


def test_serialize_run_includes_status(tmp_path):
    conn = _conn(tmp_path)
    run_id = research_store.create_run(
        conn, topic="topic", source="manual", created_by="u1"
    )

    data = research_store.serialize_run(research_store.get_run(conn, run_id))
    assert data["id"] == run_id
    assert data["status"] == "queued"
