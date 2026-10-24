"""Model-produced drafts reach the internal reviewer without a person."""

import dataclasses
import json
from datetime import datetime, timedelta

import pytest

from mycelium import (
    ai,
    alias_suggestions,
    auth,
    draft_review_runs,
    draft_review_settings,
    draft_review_store,
    drafts_store,
    ingest,
    server,
    store,
)
from mycelium.draft_review_store import Assessment
from mycelium.ingest import loop as ingest_loop
from mycelium.ingest.tools import EMIT_TOOL
from mycelium.server import runtime
from settings_helpers import assume_configured_models, save_model, set_review_controls
from test_ingest import (
    FakeAnthropic,
    FakeSubstrate,
    _emit_input,
    _ledger_row,
    _message,
    _op,
    _reconcile_then_adjacency,
    _tool_use,
)
from test_internal_draft_review import _assessment, _draft
from test_reviewed_application import _app


@pytest.fixture(autouse=True)
def _configured_models(monkeypatch):
    assume_configured_models(monkeypatch)


TEXT = "Single sign-on (SSO) is required in the Admin console."


@pytest.fixture
def curated_app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())
    with _app(tmp_path, monkeypatch) as client:
        with store.transaction(runtime._auth_db()):
            reviewer = auth.create_user(
                runtime._auth_db(), name="Reviewer", role="writer", type="service"
            )
        set_review_controls(reviewer_id=reviewer)
        save_model("draft_review", openai_model="gpt-fixture")
        token = auth.current_principal.set(auth.LOCAL_ADMIN)
        try:
            entity_id = server.upsert_entity(
                name="Single sign-on", description="Federated authentication"
            )["entity_id"]
        finally:
            auth.current_principal.reset(token)
        yield client, entity_id
        draft_review_runs.wait_all()


def _automatic():
    set_review_controls(mode="review-and-apply", application_enabled=True)


def _stub_ingest_model(monkeypatch, entity_id):
    alias = alias_suggestions.Proposal(
        entity_id=entity_id,
        alias="SSO",
        quote="Single sign-on (SSO)",
        reason="The abbreviation is defined in parentheses.",
        ambiguity="",
    )
    emission = _emit_input(
        ops=[
            _op("alias_suggestion", alias.model_dump(exclude_none=True)),
            _op(
                "upsert_entity",
                {"name": "Admin console", "description": "Administration UI"},
            ),
        ],
        ledger=[
            _ledger_row(
                "the Admin console requires single sign-on",
                "new",
                matched=[entity_id],
                considered=[],
                note="new concept",
            )
        ],
    )
    run_ingest = ingest_loop.run_ingest

    def stub(text, *, config):
        return run_ingest(
            text,
            client=FakeAnthropic(
                _reconcile_then_adjacency()
                + [_message([_tool_use(EMIT_TOOL, emission)])]
            ),
            substrate=FakeSubstrate(),
            config=dataclasses.replace(
                config,
                provider="claude",
                limits=config.limits.model_copy(update={"thinking": False}),
                trace_log_path=None,
            ),
        )

    monkeypatch.setattr(ingest, "run_ingest", stub)


def _entity_names():
    return {entity["name"] for entity in server.list_entities()["entities"]}


def test_ingested_prose_is_applied_without_a_person(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    _stub_ingest_model(monkeypatch, entity_id)

    response = client.post("/ingest", json={"text": TEXT})

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["submitted_for_review"] is True
    draft_review_runs.wait_all()
    draft = server.get_draft(result["draft_id"])
    assert draft["status"] == "approved"
    assert draft["review_assessment"]["application"] == "applied"
    assert "Admin console" in _entity_names()
    aliases = server.get_draft(result["alias_draft_id"])
    assert aliases["status"] == "submitted"
    assert aliases["review_assessment"] is None
    [pending] = alias_suggestions.list_entries()
    assert pending.draft_id == result["alias_draft_id"]
    assert store.get_name_by_text(server._db(), "SSO") is None


def test_ingest_leaves_the_draft_open_while_review_is_off(curated_app, monkeypatch):
    client, entity_id = curated_app
    _stub_ingest_model(monkeypatch, entity_id)

    result = client.post("/ingest", json={"text": TEXT}).json()

    assert result["submitted_for_review"] is False
    draft = server.get_draft(result["draft_id"])
    assert draft["status"] == "open"
    assert draft["review_assessment"] is None
    assert "Admin console" not in _entity_names()


QUESTION = "Is the Admin console the same concept as the Settings page?"


def _asks_then_approves(monkeypatch):
    contexts = []

    def model(context):
        contexts.append(json.loads(context))
        if len(contexts) == 1:
            return Assessment(
                label="needs_context",
                rationale="The draft may duplicate a live concept.",
                questions=[QUESTION],
                alias_decisions=[],
                corrections=[],
                contradictions=[],
            )
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    return contexts


def _ingested_draft(client, monkeypatch, entity_id):
    _stub_ingest_model(monkeypatch, entity_id)
    draft_id = client.post("/ingest", json={"text": TEXT}).json()["draft_id"]
    draft_review_runs.wait_all()
    return draft_id


def _answer(client, draft_id, text, *, run_id=None):
    run_id = run_id or server.get_draft(draft_id)["review_assessment"]["run_id"]
    return client.post(
        f"/api/drafts/{draft_id}/review/answer",
        json={"run_id": run_id, "answer": text},
    )


def test_reviewer_question_waits_for_a_person(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    _asks_then_approves(monkeypatch)

    draft_id = _ingested_draft(client, monkeypatch, entity_id)

    draft = client.get(f"/api/drafts/{draft_id}").json()["draft"]
    assert draft["status"] == "submitted"
    assessment = draft["review_assessment"]
    assert assessment["status"] == "completed"
    assert assessment["label"] == "needs_context"
    assert assessment["application"] == "needs_human"
    assert assessment["questions"] == [QUESTION]
    [review] = drafts_store.list_reviews(server._drafts_db(), draft_id)
    assert review["outcome"] == "needs_context"
    assert QUESTION in json.loads(review["unresolved_json"])
    [gap] = [row["text"] for row in store.list_knowledge_gaps(server._db())]
    assert draft_id in gap and QUESTION in gap
    assert "Admin console" not in _entity_names()


def test_answer_reviews_the_draft_again_with_it(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    contexts = _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)

    asked = server.get_draft(draft_id)["review_assessment"]["run_id"]

    response = _answer(client, draft_id, "No, they are separate screens.")

    assert response.status_code == 200, response.text
    draft_review_runs.wait_all()
    [answer] = contexts[1]["answers_from_curators"]
    assert answer["run_id"] == asked
    assert answer["questions"] == [QUESTION]
    assert answer["answer"] == "No, they are separate screens."
    assert answer["answered_by"] == auth.LOCAL_ADMIN.id
    assert contexts[1]["draft"]["review_evidence"] is None
    draft = server.get_draft(draft_id)
    assert draft["status"] == "approved"
    assert draft["review_assessment"]["application"] == "applied"
    assert "Admin console" in _entity_names()


def _agent(role):
    with store.transaction(runtime._auth_db()):
        agent = auth.create_user(
            runtime._auth_db(), name="Code agent", role=role, type="service"
        )
    return auth.Principal(id=agent, name="Code agent", role=role, type="service")


EVIDENCE = {
    "kind": "code",
    "path": "app/admin/routes.py",
    "lines": "3-9",
    "excerpt": "admin = Blueprint('admin')\nsettings = Blueprint('settings')",
    "claim": "The Admin console and the Settings page are separate screens.",
}


def test_a_curation_agent_answers_a_question_with_evidence(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    contexts = _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)
    agent = _agent("drafter")

    token = auth.current_principal.set(agent)
    try:
        [item] = server.claim_curation_work("question")["items"]
        assert item["question"]["questions"] == [QUESTION]
        assert item["question"]["draft_id"] == draft_id
        with pytest.raises(ValueError, match="needs evidence"):
            server.release_curation_work([item["id"]], "answered", answer="No.")
        server.release_curation_work(
            [item["id"]],
            "answered",
            answer="No, they are separate screens.",
            evidence=[EVIDENCE],
        )
    finally:
        auth.current_principal.reset(token)
    draft_review_runs.wait_all()

    [answer] = contexts[1]["answers_from_curators"]
    assert answer["answered_by"] == agent.id
    assert answer["evidence"] == [EVIDENCE]
    assert server.get_draft(draft_id)["status"] == "approved"


def test_the_drafts_creator_cannot_answer_its_reviewer(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)
    creator = _agent("drafter")
    with store.transaction(server._drafts_db()):
        server._drafts_db().execute(
            "UPDATE drafts SET created_by = ? WHERE id = ?", (creator.id, draft_id)
        )

    token = auth.current_principal.set(creator)
    try:
        [item] = server.claim_curation_work("question")["items"]
        with pytest.raises(ValueError, match="you created this draft"):
            server.release_curation_work(
                [item["id"]], "answered", answer="No.", evidence=[EVIDENCE]
            )
    finally:
        auth.current_principal.reset(token)


def test_applying_the_answered_draft_resolves_its_question_gap(
    curated_app, monkeypatch
):
    client, entity_id = curated_app
    _automatic()
    _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)
    with store.transaction(server._db()):
        unrelated = store.create_knowledge_gap(server._db(), "Unrelated question.")

    assert (
        _answer(client, draft_id, "No, they are separate screens.").status_code == 200
    )
    draft_review_runs.wait_all()

    gaps = {row["id"]: row for row in store.list_knowledge_gaps(server._db())}
    [asked] = [row for row in gaps.values() if row["draft_id"] == draft_id]
    assert asked["resolved_at"] is not None
    assert asked["resolved_by"] == draft_review_settings.load().reviewer_id
    assert gaps[unrelated]["resolved_at"] is None


def test_answer_requires_a_current_waiting_question(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)

    other = _answer(client, draft_id, "No.", run_id="drv_older")
    assert other.status_code == 400
    assert "asked again" in other.json()["detail"]
    assert _answer(client, draft_id, "").status_code == 400
    with store.transaction(server._drafts_db()):
        server._drafts_db().execute(
            "UPDATE drafts SET revision = revision + 1 WHERE id = ?", (draft_id,)
        )
    stale = _answer(client, draft_id, "No.")
    assert stale.status_code == 400
    assert "changed after the reviewer asked" in stale.json()["detail"]


def test_advisory_questions_do_not_wait_for_an_answer(curated_app, monkeypatch):
    client, entity_id = curated_app
    set_review_controls(mode="review-only")
    _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)
    assessment = server.get_draft(draft_id)["review_assessment"]
    assert assessment["label"] == "needs_context"
    assert assessment["application"] == "unapplied"

    response = _answer(client, draft_id, "No.")

    assert response.status_code == 400
    assert "not waiting" in response.json()["detail"]
    assert store.list_knowledge_gaps(server._db()) == []


def _failing_provider(monkeypatch):
    def model(context):
        raise ai.ModelError("Fixture provider outage")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)


def _latest(draft_id):
    draft_review_runs.wait_all()
    return draft_review_store.latest(server._drafts_db(), draft_id)


def _finished(run):
    return datetime.fromisoformat(run.finished_at)


def _due(run):
    return _finished(run) + draft_review_runs.RETRY_BACKOFF * (1 << run.retries)


def test_sweep_retries_a_provider_failure_after_backoff(curated_app, monkeypatch):
    _automatic()
    _failing_provider(monkeypatch)
    draft_id = _draft()
    failed = _latest(draft_id)
    assert (failed.status, failed.attempt, failed.retries) == ("failed", 2, 0)
    due = _finished(failed) + draft_review_runs.RETRY_BACKOFF
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())

    assert draft_review_runs.sweep(due - timedelta(seconds=1)) == []
    assert draft_review_runs.sweep(due) == [draft_id]

    retried = _latest(draft_id)
    assert (retried.attempt, retried.retries) == (1, 1)
    assert retried.previous_failure == "Fixture provider outage"
    assert retried.application == "applied"
    assert server.get_draft(draft_id)["status"] == "approved"


def test_sweep_leaves_a_failure_older_than_the_retry_window_to_the_backlog(
    curated_app, monkeypatch
):
    client, _ = curated_app
    _automatic()
    _failing_provider(monkeypatch)
    draft_id = _draft()
    failed = _latest(draft_id)

    assert draft_review_runs.sweep(_finished(failed) + timedelta(days=1)) == []
    assert _latest(draft_id).run_id == failed.run_id
    assert client.get("/api/draft-review/backlog").json()["draft_ids"] == [draft_id]


def test_sweep_waits_for_credentials_without_recording_runs(curated_app, monkeypatch):
    _automatic()
    _failing_provider(monkeypatch)
    draft_id = _draft()
    failed = _latest(draft_id)
    monkeypatch.delenv("OPENAI_API_KEY")

    assert draft_review_runs.sweep(_due(failed)) == []
    assert _latest(draft_id).run_id == failed.run_id


def test_sweep_stops_after_the_last_attempt(curated_app, monkeypatch):
    _automatic()
    _failing_provider(monkeypatch)
    draft_id = _draft()
    for _ in range(draft_review_runs.MAX_RETRIES):
        assert draft_review_runs.sweep(_due(_latest(draft_id))) == [draft_id]
    exhausted = _latest(draft_id)
    assert exhausted.retries == draft_review_runs.MAX_RETRIES
    assert exhausted.attempt == 2
    assert draft_review_runs.sweep(_finished(exhausted) + timedelta(days=30)) == []
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_sweep_recovers_restarts_and_configuration_failures(curated_app):
    interrupted = _draft()
    conn = server._drafts_db()
    with store.transaction(conn):
        run = draft_review_store.new(
            interrupted, "review-and-apply", server.get_draft(interrupted)["revision"]
        )
        draft_review_store.save(conn, run)
    draft_review_store.mark_orphaned(conn)
    _automatic()
    reviewer = draft_review_runs.draft_review_settings.load().reviewer_id
    set_review_controls(reviewer_id="local-admin")
    misconfigured = _draft()
    assert "active real writer" in _latest(misconfigured).detail
    set_review_controls(reviewer_id=reviewer)

    later = datetime.fromisoformat(_latest(misconfigured).finished_at) + timedelta(
        hours=1
    )
    assert sorted(draft_review_runs.sweep(later)) == sorted(
        [interrupted, misconfigured]
    )
    draft_review_runs.wait_all()
    assert server.get_draft(interrupted)["status"] == "approved"
    assert server.get_draft(misconfigured)["status"] == "approved"


def test_sweep_leaves_settled_and_unreviewed_drafts_alone(curated_app, monkeypatch):
    client, entity_id = curated_app
    submitted_while_off = _draft()
    _automatic()
    _asks_then_approves(monkeypatch)
    waiting_for_person = _ingested_draft(client, monkeypatch, entity_id)
    far_future = datetime.fromisoformat("2100-01-01T00:00:00.000Z")

    assert draft_review_runs.sweep(far_future) == []
    assert _latest(submitted_while_off) is None
    assert _latest(waiting_for_person).application == "needs_human"
    set_review_controls(mode="off")
    _failing_provider(monkeypatch)
    assert draft_review_runs.sweep(far_future) == []


def test_backlog_is_offered_and_reviewed_once_when_switched_on(
    curated_app, monkeypatch
):
    client, entity_id = curated_app
    submitted_while_off = _draft()
    alias_only = _ingest_aliases_only(client, monkeypatch, entity_id)
    set_review_controls(mode="review-only")
    advisory = _draft()
    assert _latest(advisory).status == "completed"
    assert client.get("/api/draft-review/backlog").json()["draft_ids"] == [
        submitted_while_off
    ]

    _automatic()
    offered = client.get("/api/draft-review/backlog").json()["draft_ids"]
    assert sorted(offered) == sorted([submitted_while_off, advisory])
    assert alias_only not in offered
    response = client.post("/api/draft-review/backlog")

    assert response.json()["job"]["remaining"] == len(offered)
    draft_review_runs.wait_backlog()
    assert server.get_draft(submitted_while_off)["status"] == "approved"
    assert server.get_draft(advisory)["status"] == "approved"
    assert server.get_draft(alias_only)["status"] == "submitted"
    backlog = client.get("/api/draft-review/backlog").json()
    assert backlog["draft_ids"] == []
    assert backlog["job"]["status"] == "finished"
    assert backlog["job"]["reviewed"] == 2


def test_backlog_review_is_refused_while_review_is_off(curated_app):
    client, _ = curated_app
    submitted = _draft()

    response = client.post("/api/draft-review/backlog")

    assert response.status_code == 400
    assert _latest(submitted) is None


def _ingest_aliases_only(client, monkeypatch, entity_id):
    alias = alias_suggestions.Proposal(
        entity_id=entity_id,
        alias="SSO",
        quote="Single sign-on (SSO)",
        reason="The abbreviation is defined in parentheses.",
        ambiguity="",
    )
    emission = _emit_input(
        ops=[_op("alias_suggestion", alias.model_dump(exclude_none=True))],
        ledger=[
            _ledger_row(
                "SSO", "new", matched=[entity_id], considered=[], note="abbreviation"
            )
        ],
    )
    run_ingest = ingest_loop.run_ingest
    monkeypatch.setattr(
        ingest,
        "run_ingest",
        lambda text, *, config: run_ingest(
            text,
            client=FakeAnthropic(
                _reconcile_then_adjacency()
                + [_message([_tool_use(EMIT_TOOL, emission)])]
            ),
            substrate=FakeSubstrate(),
            config=dataclasses.replace(
                config,
                provider="claude",
                limits=config.limits.model_copy(update={"thinking": False}),
                trace_log_path=None,
            ),
        ),
    )
    result = client.post("/ingest", json={"text": TEXT}).json()
    assert result["draft_id"] == result["alias_draft_id"]
    return result["draft_id"]


def test_sweep_does_not_supersede_a_run_that_finished_after_selection(
    curated_app, monkeypatch
):
    _automatic()
    _failing_provider(monkeypatch)
    draft_id = _draft()
    selected = _latest(draft_id)
    retry_due = draft_review_runs._retry_due
    interleaved = []

    def selection_then_manual_rerun(run, now):
        due = retry_due(run, now)
        if due and not interleaved:
            interleaved.append(run.run_id)
            _asks_then_approves(monkeypatch)
            token = auth.current_principal.set(auth.LOCAL_ADMIN)
            try:
                server.request_draft_review(draft_id, rerun=True)
            finally:
                auth.current_principal.reset(token)
            draft_review_runs.wait_all()
        return due

    monkeypatch.setattr(draft_review_runs, "_retry_due", selection_then_manual_rerun)

    assert draft_review_runs.sweep(_due(selected)) == []

    assert interleaved == [selected.run_id]
    latest = _latest(draft_id)
    assert latest.application == "needs_human"
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_question_survives_a_failure_after_it_was_recorded(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    contexts = _asks_then_approves(monkeypatch)

    def gaps_unavailable(text):
        raise RuntimeError("substrate unavailable")

    monkeypatch.setattr(draft_review_runs, "_report_gap", gaps_unavailable)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)

    run = _latest(draft_id)
    assert (run.status, run.application) == ("completed", "needs_human")
    assert len(contexts) == 1
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_question_survives_a_restart_after_it_was_recorded(curated_app, monkeypatch):
    client, entity_id = curated_app
    _automatic()
    _asks_then_approves(monkeypatch)
    draft_id = _ingested_draft(client, monkeypatch, entity_id)
    conn = server._drafts_db()
    in_flight = _latest(draft_id).model_copy(update={"status": "running"})
    with store.transaction(conn):
        draft_review_store.save(conn, in_flight)

    draft_review_store.mark_orphaned(conn)

    recovered = _latest(draft_id)
    assert (recovered.status, recovered.application) == ("completed", "needs_human")
    far_future = datetime.fromisoformat("2100-01-01T00:00:00.000Z")
    assert draft_review_runs.sweep(far_future) == []
    assert _answer(client, draft_id, "No.").status_code == 200
