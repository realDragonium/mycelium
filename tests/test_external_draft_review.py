"""Draft review done by an outside agent through the agent task queue."""

import json

import pytest

from mycelium import (
    agent_tasks,
    auth,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    embed,
    model_settings,
    server,
    store,
)
from mycelium.server import runtime
from review_helpers import correction
from settings_helpers import set_review_controls
from test_reviewed_application import _principal


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """A server with no provider key whose draft review runs on an external
    agent, and the principal id of a writer agent that may claim reviews."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    server.init(tmp_path)
    current = model_settings.get("draft_review")
    model_settings.save(
        "draft_review",
        model_settings.SaveSelection(
            provider=current.provider,
            claude_model="",
            openai_model="",
            external_agent=True,
            revision=current.revision,
        ),
        auth.LOCAL_ADMIN,
    )
    set_review_controls(
        mode="review-and-apply", application_enabled=True, auto_apply="with_corrections"
    )
    with store.transaction(runtime._auth_db()):
        agent_id = auth.create_user(
            runtime._auth_db(), name="Agent", role="writer", type="service"
        )
    yield agent_id
    draft_review_runs.wait_all()


def _as(principal_id):
    principal = auth.resolve_session_user(runtime._auth_db(), principal_id)
    assert principal is not None
    return auth.current_principal.set(principal)


def _draft():
    token = _principal("drafter")
    try:
        draft_id = server.upsert_entity(name="Invoices", description="Billing records")[
            "draft_id"
        ]
        server.submit_draft(draft_id)
        return draft_id
    finally:
        auth.current_principal.reset(token)


def _claim(principal_id):
    token = _as(principal_id)
    try:
        return server.claim_agent_task("draft_review")
    finally:
        auth.current_principal.reset(token)


def _submit(principal_id, task_id, label, corrections=(), questions=()):
    token = _as(principal_id)
    try:
        return server.submit_agent_task(
            task_id,
            {
                "parts": [
                    {
                        "label": label,
                        "rationale": "Judged against the supplied knowledge.",
                        "questions": list(questions),
                        "corrections": [c.model_dump() for c in corrections],
                        "contradictions": [],
                    }
                ]
            },
        )
    finally:
        auth.current_principal.reset(token)


def _gaps():
    return [
        row["text"]
        for row in store.list_knowledge_gaps(store.substrate_connection(), "open")
    ]


def test_an_agent_corrects_and_the_draft_is_applied_as_reviewed(agent):
    draft_id = _draft()
    waiting = server.get_draft(draft_id)["review_assessment"]
    assert (waiting["status"], waiting["provider"]) == ("running", "agent")

    [task] = _claim(agent).tasks
    assert task.brief is not None
    assert json.loads(str(task.brief["input"]))["draft"]["id"] == draft_id
    assert task.brief["parts"] == 1
    submitted = _submit(
        agent,
        task.id,
        "changes_suggested",
        [
            correction(
                "edit",
                operation_ref=server.get_draft(draft_id)["ops"][0]["operation_ref"],
                description="Billing records of a workspace",
            )
        ],
    )

    assert submitted.status == "accepted", submitted
    result = server.get_draft(draft_id)
    assert result["status"] == "approved"
    review = result["review_assessment"]
    assert (review["application"], review["reviewer_id"]) == ("applied", agent)
    [reviewed] = drafts_store.list_reviews(server._drafts_db(), draft_id)
    assert (reviewed["outcome"], reviewed["reviewed_by"]) == ("refined", agent)
    [entity] = server.list_entities()["entities"]
    assert entity["description"] == "Billing records of a workspace"


def test_a_rejection_and_a_question_take_the_internal_reviewers_path(agent):
    rejected, asked = _draft(), _draft()
    first, second = _claim(agent).tasks + _claim(agent).tasks

    assert _submit(agent, first.id, "reject").status == "accepted"
    assert server.get_draft(rejected)["status"] == "rejected"
    assert (
        _submit(
            agent, second.id, "needs_context", questions=["Is this the same record?"]
        ).status
        == "accepted"
    )
    waiting = server.get_draft(asked)
    assert waiting["status"] == "submitted"
    assert waiting["review_assessment"]["application"] == "needs_human"
    gaps = _gaps()
    assert any(rejected in gap and "external agent" in gap for gap in gaps)
    assert any(asked in gap and "Is this the same record?" in gap for gap in gaps)


def test_review_only_leaves_the_decision_to_a_person(agent):
    set_review_controls(mode="review-only")
    draft_id = _draft()
    [task] = _claim(agent).tasks

    assert _submit(agent, task.id, "good").status == "accepted"
    result = server.get_draft(draft_id)
    assert result["status"] == "submitted"
    assert result["review_assessment"]["application"] == "unapplied"
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []


def test_a_drafter_is_never_given_its_own_draft(agent):
    _draft()
    creator = auth.Principal(id="drafter-1", name="d", role="writer", type="human")
    token = auth.current_principal.set(creator)
    try:
        batch = server.claim_agent_task("draft_review")
    finally:
        auth.current_principal.reset(token)

    assert batch.tasks == []
    assert batch.note is not None and "a draft you created" in batch.note
    assert len(_claim(agent).tasks) == 1


def test_a_malformed_verdict_is_refused_with_findings(agent):
    draft_id = _draft()
    [task] = _claim(agent).tasks

    refused = _submit(agent, task.id, "changes_suggested")
    assert refused.status == "refused"
    assert "requires corrections" in refused.findings[0].problem
    assert refused.retries_left == agent_tasks.RETRIES
    assert server.get_draft(draft_id)["review_assessment"]["status"] == "running"


def test_held_corrections_wait_in_the_backlog_for_an_agent(agent):
    set_review_controls(auto_apply="clean")
    draft_id = _draft()
    [task] = _claim(agent).tasks
    op = server.get_draft(draft_id)["ops"][0]["operation_ref"]
    _submit(
        agent,
        task.id,
        "changes_suggested",
        [correction("edit", operation_ref=op, description="Billing records")],
    )
    assert server.get_draft(draft_id)["review_assessment"]["application"] == "held"

    assert draft_review_runs.backlog() == [draft_id]
    draft_review_runs.start(draft_id, rerun=True)
    [again] = _claim(agent).tasks
    assert again.brief is not None
    earlier = again.brief["earlier_review"]
    assert isinstance(earlier, dict) and earlier["application"] == "held"


def test_a_waiting_review_survives_a_restart(agent):
    draft_id = _draft()
    conn = server._drafts_db()
    draft_review_store.mark_orphaned(conn, waiting=agent_tasks.open_subjects(conn))

    assert server.get_draft(draft_id)["review_assessment"]["status"] == "running"


def test_the_review_form_saves_external_agent_with_no_model_or_reviewer(agent):
    from mycelium import draft_review_settings

    current = draft_review_settings.load()
    saved = draft_review_settings.save(
        draft_review_settings.SaveSettings(
            mode="review-and-apply",
            provider="openai",
            model="",
            reviewer_id="",
            external_agent=True,
            revision=current.revision,
            model_revision=current.model_revision,
        ),
        auth.LOCAL_ADMIN,
    )

    assert (saved.external_agent, saved.mode) == (True, "review-and-apply")
    assert draft_review_settings.view(auth.LOCAL_ADMIN).ready


def test_a_draft_whose_reviews_fail_twice_is_rejected(agent):
    draft_id = _draft()
    for _ in range(2):
        [task] = _claim(agent).tasks
        for _ in range(agent_tasks.RETRIES):
            assert _submit(agent, task.id, "changes_suggested").status == "refused"
        assert _submit(agent, task.id, "changes_suggested").status == "failed"

    assert server.get_draft(draft_id)["status"] == "rejected"
