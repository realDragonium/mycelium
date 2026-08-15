"""The documentation executor and the one tool that feeds it.

Two layers. The executor tests drive `doc_runs` against stub runners — a
canned document, a refusal, a crash — which is the whole point of the `RUNNER`
seam: every terminal state and every capacity rule is provable before a
generation loop exists. The tool tests pin what `request_documentation`
refuses at the door, so a request that could only fail never becomes a run.
"""

from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from mycelium import auth, doc_runs, docs_store, drafts_store, prompt_store, server


@pytest.fixture(autouse=True)
def _reset_doc_runs():
    doc_runs.RUNNER = None
    doc_runs._threads.clear()
    yield
    doc_runs.wait_all()
    doc_runs.RUNNER = None
    doc_runs._threads.clear()
    doc_runs._in_memory_conns.clear()


def _conn(tmp_path) -> sqlite3.Connection:
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    return conn


def _document(**overrides) -> dict:
    payload = {
        "outcome": "document_written",
        "slug": "how-to-x",
        "title": "How to X",
        "body": "# How to X\n\nDo the thing.\n",
    }
    payload.update(overrides)
    return payload


def _start(conn, tmp_path, runner=None, **overrides) -> str:
    kwargs = {
        "prompt": "document X",
        "guideline_set": None,
        "document_type": None,
        "created_by": None,
        "conn": conn,
    }
    kwargs.update(overrides)
    if runner is not None:
        kwargs["runner"] = runner
    return doc_runs.start_run(**kwargs)


# --- the executor -----------------------------------------------------------


def test_row_is_running_before_the_runner_returns(tmp_path):
    conn = _conn(tmp_path)
    release = threading.Event()

    def runner(prompt, *, guideline_set, document_type):
        release.wait()
        return SimpleNamespace(model_dump=lambda: _document())

    run_id = _start(conn, tmp_path, runner)
    assert docs_store.status_for(docs_store.get_run(conn, run_id)) == "running"

    release.set()
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "document_written"
    assert row["error"] is None
    document = docs_store.get_document(conn, row["document_id"])
    assert document["slug"] == "how-to-x"
    assert document["body"].startswith("# How to X")
    assert document["last_run_id"] == run_id


def test_runner_resolution_lands_on_the_document(tmp_path):
    """A request that named neither leaves both null on the RUN row — that is
    what it asked for. What the run actually wrote against is a property of
    the document, and the store has columns for it there."""
    conn = _conn(tmp_path)
    seen = {}

    def runner(prompt, *, guideline_set, document_type):
        seen["guideline_set"] = guideline_set
        seen["document_type"] = document_type
        return _document(
            guideline_set="kb-authoring",
            document_type="how-to",
            statement_ids=["stm_1", "stm_2"],
        )

    run_id = _start(conn, tmp_path, runner)
    doc_runs.wait_all()

    assert seen == {"guideline_set": None, "document_type": None}
    row = docs_store.get_run(conn, run_id)
    assert row["guideline_set"] is None
    assert row["document_type"] is None
    document = docs_store.serialize_document(
        docs_store.get_document(conn, row["document_id"])
    )
    assert document["guideline_set"] == "kb-authoring"
    assert document["document_type"] == "how-to"
    assert document["statement_ids"] == ["stm_1", "stm_2"]


def test_requested_set_and_type_reach_the_runner_and_the_row(tmp_path):
    conn = _conn(tmp_path)
    seen = {}

    def runner(prompt, *, guideline_set, document_type):
        seen["guideline_set"] = guideline_set
        seen["document_type"] = document_type
        return _document()

    run_id = _start(
        conn,
        tmp_path,
        runner,
        guideline_set="internal-doc",
        document_type="reference",
    )
    doc_runs.wait_all()

    assert seen == {"guideline_set": "internal-doc", "document_type": "reference"}
    row = docs_store.get_run(conn, run_id)
    assert row["guideline_set"] == "internal-doc"
    assert row["document_type"] == "reference"
    document = docs_store.get_document(conn, row["document_id"])
    assert document["guideline_set"] == "internal-doc"
    assert document["document_type"] == "reference"


def test_nothing_written_reason_in_error_column(tmp_path):
    conn = _conn(tmp_path)

    run_id = _start(
        conn,
        tmp_path,
        lambda prompt, *, guideline_set, document_type: {
            "outcome": "nothing_written",
            "reason": "substrate has nothing on this",
        },
    )
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "nothing_written"
    assert row["error"] == "substrate has nothing on this"
    assert row["document_id"] is None


def test_runner_exception_marks_failed(tmp_path):
    conn = _conn(tmp_path)

    def runner(prompt, *, guideline_set, document_type):
        raise RuntimeError("model refused")

    run_id = _start(conn, tmp_path, runner)
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "failed"
    assert "RuntimeError: model refused" in row["error"]
    assert row["finished_at"] is not None


def test_unwritable_document_fails_the_run_rather_than_claiming_one(tmp_path):
    """The store refuses a blank slug. The run must finish failed, not
    'document_written' pointing at nothing."""
    conn = _conn(tmp_path)

    run_id = _start(
        conn,
        tmp_path,
        lambda prompt, *, guideline_set, document_type: _document(slug="   "),
    )
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "failed"
    assert "slug is required" in row["error"]
    assert row["document_id"] is None


def test_unknown_runner_outcome_fails_rather_than_reading_as_a_refusal(tmp_path):
    conn = _conn(tmp_path)

    run_id = _start(
        conn,
        tmp_path,
        lambda prompt, *, guideline_set, document_type: {
            "outcome": "failed",
            "error": "the runner's own word for it",
        },
    )
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "failed"
    assert "unknown outcome: 'failed'" in row["error"]


def test_a_thread_that_never_starts_finishes_the_row(tmp_path, monkeypatch):
    """The window between the insert and `Thread.start()`: the row is already
    committed, so it must be finished as failed rather than left queued to
    hold capacity until the next restart sweeps it."""
    conn = _conn(tmp_path)
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda self: (_ for _ in ()).throw(RuntimeError("can't start new thread")),
    )

    with pytest.raises(RuntimeError, match="can't start new thread"):
        _start(
            conn,
            tmp_path,
            lambda prompt, *, guideline_set, document_type: _document(),
        )

    (row,) = docs_store.list_runs(conn)
    assert docs_store.status_for(row) == "failed"
    assert "failed to start: RuntimeError" in row["error"]
    assert doc_runs._threads == {}
    assert doc_runs._in_memory_conns == {}


def test_in_memory_runs_reuse_the_handed_connection(tmp_path):
    """`:memory:` has no file path for the worker thread to reopen, so the
    connection passed to `start_run` is what the run must finish through."""
    conn = docs_store.connect(":memory:")
    docs_store.migrate(conn)
    started = threading.Event()
    release = threading.Event()

    def runner(prompt, *, guideline_set, document_type):
        started.set()
        release.wait()
        return _document()

    try:
        run_id = _start(conn, tmp_path, runner)
        assert started.wait(5)
        assert doc_runs._threads[run_id].is_alive()
        release.set()
        doc_runs.wait_all()

        # Visibility on THIS connection is the proof of the handoff: with no
        # file path, a worker that opened its own connection would have
        # written into a private temporary database instead.
        row = docs_store.get_run(conn, run_id)
        assert row["outcome"] == "document_written"
        assert docs_store.get_document(conn, row["document_id"])["slug"] == "how-to-x"
        # Nothing accumulates in either registry once the run is over.
        assert doc_runs._in_memory_conns == {}
        assert doc_runs._threads == {}
    finally:
        release.set()
        doc_runs.wait_all()
        conn.close()


def test_unconfigured_runner_finishes_the_run_failed(tmp_path):
    """No RUNNER and no explicit runner: the request still becomes a run row
    that reaches a terminal state, saying why."""
    conn = _conn(tmp_path)

    run_id = _start(conn, tmp_path)
    doc_runs.wait_all()

    row = docs_store.get_run(conn, run_id)
    assert row["outcome"] == "failed"
    assert "no documentation runner is configured" in row["error"]


def test_capacity_refuses_when_at_max_and_names_the_env_var(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv(doc_runs.MAX_ACTIVE_ENV, "2")
    release = threading.Event()

    def runner(prompt, *, guideline_set, document_type):
        release.wait()
        return {"outcome": "nothing_written", "reason": "done"}

    run1 = _start(conn, tmp_path, runner)
    run2 = _start(conn, tmp_path, runner)
    assert {
        docs_store.status_for(docs_store.get_run(conn, run1)),
        docs_store.status_for(docs_store.get_run(conn, run2)),
    } == {"running"}

    with pytest.raises(ValueError, match="max 2, from MYCELIUM_DOCGEN_MAX_ACTIVE"):
        _start(conn, tmp_path, runner)

    release.set()
    doc_runs.wait_all()

    run3 = _start(
        conn,
        tmp_path,
        lambda prompt, *, guideline_set, document_type: {
            "outcome": "nothing_written",
            "reason": "done",
        },
    )
    doc_runs.wait_all()
    assert docs_store.status_for(docs_store.get_run(conn, run3)) == "nothing_written"


def test_bound_is_db_derived(tmp_path, monkeypatch):
    """A row left running by a previous process still counts, because the
    count comes from the table and not from this process's threads."""
    conn = _conn(tmp_path)
    monkeypatch.setenv(doc_runs.MAX_ACTIVE_ENV, "1")
    stranded = docs_store.create_run(conn, prompt="stranded", created_by=None)
    docs_store.mark_started(conn, stranded)

    with pytest.raises(ValueError, match="max 1"):
        _start(
            conn,
            tmp_path,
            lambda prompt, *, guideline_set, document_type: _document(),
        )


def test_concurrent_starts_race_one_wins(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv(doc_runs.MAX_ACTIVE_ENV, "1")
    release = threading.Event()
    barrier = threading.Barrier(2)
    errors = []
    run_ids = []

    def runner(prompt, *, guideline_set, document_type):
        release.wait()
        return {"outcome": "nothing_written", "reason": "done"}

    def start():
        barrier.wait()
        try:
            run_ids.append(_start(conn, tmp_path, runner))
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
    doc_runs.wait_all()


def test_explicit_runner_beats_module_override(tmp_path):
    """An explicitly passed runner wins over the module-level RUNNER hook;
    RUNNER only fills in when no runner is passed (how HTTP callers reach it)."""
    conn = _conn(tmp_path)
    called = []

    def module_runner(prompt, *, guideline_set, document_type):
        called.append("module")
        return {"outcome": "nothing_written", "reason": "module"}

    def kwarg_runner(prompt, *, guideline_set, document_type):
        called.append("kwarg")
        return {"outcome": "nothing_written", "reason": "kwarg"}

    doc_runs.RUNNER = module_runner
    run_id = _start(conn, tmp_path, kwarg_runner)
    doc_runs.wait_all()
    assert called == ["kwarg"]
    assert docs_store.get_run(conn, run_id)["error"] == "kwarg"

    called.clear()
    run_id2 = _start(conn, tmp_path)
    doc_runs.wait_all()
    assert called == ["module"]
    assert docs_store.get_run(conn, run_id2)["error"] == "module"


def test_run_holds_a_shared_model_loop_slot(tmp_path, monkeypatch):
    """The wiring: the runner must execute inside the slot, not beside it —
    otherwise a documentation run and `ask` each get the full budget."""
    monkeypatch.setenv(server._MODEL_LOOP_MAX_CONCURRENT_ENV, "1")
    server._model_loop_budget.cache_clear()

    db_path = tmp_path / "mycelium-drafts.db"
    conn = _conn(tmp_path)
    run_id = docs_store.create_run(conn, prompt="p", created_by=None)
    docs_store.mark_started(conn, run_id)
    observed = {}

    def runner(prompt, *, guideline_set, document_type):
        observed["another_slot_available"] = server._model_loop_budget().acquire(
            blocking=False
        )
        return {"outcome": "nothing_written", "reason": "test"}

    try:
        doc_runs._execute_run(run_id, "p", None, None, str(db_path), runner)
    finally:
        server._model_loop_budget.cache_clear()

    assert observed["another_slot_available"] is False
    assert docs_store.get_run(conn, run_id)["outcome"] == "nothing_written"


# --- the tool ---------------------------------------------------------------


@pytest.fixture
def _stores(tmp_path):
    """Pin this thread's drafts and prompts connections, as a booted server
    would, without building one."""
    drafts_conn = _conn(tmp_path)
    drafts_store.use_connection(drafts_conn)
    prompts_conn = prompt_store.connect(":memory:")
    prompt_store.migrate(prompts_conn)
    prompt_store.use_connection(prompts_conn)
    try:
        yield drafts_conn, prompts_conn
    finally:
        drafts_store.reset()
        prompt_store.reset()
        drafts_conn.close()
        prompts_conn.close()


def _save_set(conn, set_name: str, slots: list[str]) -> None:
    from mycelium import guidelines

    for slot in slots:
        prompt_store.save(
            conn, type=guidelines.TYPE, name=f"{set_name}/{slot}", text="text"
        )


def test_request_documentation_returns_a_running_row(_stores):
    drafts_conn, _ = _stores
    release = threading.Event()

    def runner(prompt, *, guideline_set, document_type):
        release.wait()
        return _document()

    doc_runs.RUNNER = runner

    # Held open, so "returns immediately with a running row" is what is
    # asserted rather than a race the worker usually loses.
    row = server.request_documentation("  document the login flow  ")

    assert row["prompt"] == "document the login flow"
    assert row["status"] == "running"
    assert row["guideline_set"] is None
    assert row["document_type"] is None

    release.set()
    doc_runs.wait_all()
    assert docs_store.get_run(drafts_conn, row["id"])["outcome"] == "document_written"


def test_named_set_and_type_must_exist(_stores):
    _, prompts_conn = _stores
    _save_set(prompts_conn, "kb-authoring", ["guidance", "how-to", "reference"])
    _save_set(prompts_conn, "internal-doc", ["guidance", "how-to"])
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: _document()

    with pytest.raises(ValueError) as unknown_set:
        server.request_documentation("p", guideline_set="no-such-set")
    assert "unknown guideline set 'no-such-set'" in str(unknown_set.value)
    assert "['internal-doc', 'kb-authoring']" in str(unknown_set.value)

    with pytest.raises(ValueError) as unknown_type:
        server.request_documentation(
            "p", guideline_set="internal-doc", document_type="tutorial"
        )
    # `guidance` is the set-wide instruction, so it is never offered as a
    # document type a run could produce.
    assert "available: ['how-to']" in str(unknown_type.value)

    row = server.request_documentation(
        "p", guideline_set="kb-authoring", document_type="reference"
    )
    assert row["guideline_set"] == "kb-authoring"
    assert row["document_type"] == "reference"


def test_the_shipped_set_validates_as_the_convention_says(_stores):
    """Against the rows startup actually seeds, not hand-written stand-ins:
    the `<set>/<slot>` parse here has to agree with the names in
    `guidelines.SOURCES`, or the one set that ships would be unrequestable."""
    from mycelium import guidelines

    _, prompts_conn = _stores
    for name, text in guidelines.read_rows().items():
        prompt_store.save(prompts_conn, type=guidelines.TYPE, name=name, text=text)
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: _document()

    row = server.request_documentation(
        "p", guideline_set=guidelines.SET_NAME, document_type="how-to"
    )
    assert row["guideline_set"] == "kb-authoring"

    with pytest.raises(ValueError, match="no template for document type"):
        server.request_documentation(
            "p", guideline_set=guidelines.SET_NAME, document_type="guidance"
        )


def test_a_document_type_without_a_set_is_left_to_the_run(_stores):
    """Nothing to check it against until a set is chosen, and refusing on a
    guess would be worse than letting the run resolve both."""
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: _document()

    row = server.request_documentation("p", document_type="anything-at-all")

    assert row["guideline_set"] is None
    assert row["document_type"] == "anything-at-all"


def test_blank_and_oversized_prompts_are_refused(_stores, monkeypatch):
    with pytest.raises(ValueError, match="prompt is required"):
        server.request_documentation("   ")

    monkeypatch.setenv("MYCELIUM_DOCGEN_MAX_PROMPT_CHARS", "10")
    with pytest.raises(ValueError, match="the limit is 10"):
        server.request_documentation("x" * 11)


def test_no_refusal_leaves_a_run_behind(_stores, monkeypatch):
    """Every door this tool can close, closed before `create_run`: a refused
    request must not leave a row that then counts against capacity."""
    drafts_conn, prompts_conn = _stores
    _save_set(prompts_conn, "internal-doc", ["guidance", "how-to"])

    refusals = [
        ({"prompt": "   "}, "prompt is required"),
        ({"prompt": "x" * 3000}, "the limit is 2000"),
        (
            {"prompt": "p", "guideline_set": "no-such-set"},
            "unknown guideline set",
        ),
        (
            {"prompt": "p", "guideline_set": "internal-doc", "document_type": "essay"},
            "no template for document type",
        ),
    ]
    for kwargs, message in refusals:
        with pytest.raises(ValueError, match=message):
            server.request_documentation(**kwargs)

    monkeypatch.setenv(doc_runs.MAX_ACTIVE_ENV, "0")
    with pytest.raises(ValueError, match="MYCELIUM_DOCGEN_MAX_ACTIVE"):
        server.request_documentation("p")

    assert docs_store.list_runs(drafts_conn) == []


def test_request_documentation_is_registered_outside_the_model_loop_set():
    names = {function.__name__ for function in server.TOOLS}

    assert "request_documentation" in names
    # `real_role`: a drafter must NOT reach this. Their write gates are waived
    # only because the wrapper redirects them onto a draft, and a generated
    # document is not redirected — it lands live.
    assert server.request_documentation._mycelium_required_role == "writer"
    assert server.request_documentation._mycelium_real_role is True
    # The TOOL is fast — it returns a run row. Its background run takes the
    # slot, so gating the tool would double-count the budget.
    assert "request_documentation" not in server._MODEL_LOOP_TOOLS
    assert server.limiter_for("request_documentation") is None


def test_a_drafter_is_refused_and_a_writer_is_not(_stores):
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: {
        "outcome": "nothing_written",
        "reason": "done",
    }

    token = auth.current_principal.set(
        auth.Principal(id="d", name="Drafter", role="drafter", type="human")
    )
    try:
        with pytest.raises(PermissionError):
            server.request_documentation("p")
    finally:
        auth.current_principal.reset(token)

    token = auth.current_principal.set(
        auth.Principal(id="w", name="Writer", role="writer", type="human")
    )
    try:
        assert server.request_documentation("p")["created_by"] == "w"
    finally:
        auth.current_principal.reset(token)
