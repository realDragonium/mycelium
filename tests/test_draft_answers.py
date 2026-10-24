import json

import pytest

from mycelium import (
    ai,
    auth,
    draft_answers,
    draft_review_runs,
    draft_review_settings,
    embed,
    server,
    store,
)
from mycelium.draft_review_store import Answer, Assessment, ReviewRun
from mycelium.server import runtime
from settings_helpers import save_model, set_review_controls
from test_reviewed_application import _principal


def _assessment(label: str) -> Assessment:
    return Assessment(
        label=label,
        rationale="The relationship needs confirmation."
        if label == "needs_context"
        else "The supplied answer settles the relationship.",
        questions=["Does the workspace export run daily?"]
        if label == "needs_context"
        else [],
        alias_decisions=[],
        corrections=[],
        contradictions=[],
    )


@pytest.fixture
def answer_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    server.init(tmp_path)
    with store.transaction(runtime._auth_db()):
        reviewer = auth.create_user(
            runtime._auth_db(), name="Reviewer", role="writer", type="service"
        )
    set_review_controls(
        mode="review-and-apply",
        application_enabled=True,
        answer_questions=True,
        reviewer_id=reviewer,
        auto_apply="with_corrections",
    )
    save_model("draft_review", openai_model="gpt-fixture")
    yield
    draft_review_runs.wait_all()


def _draft() -> tuple[str, str]:
    token = auth.current_principal.set(auth.LOCAL_ADMIN)
    try:
        statement_id = server.upsert_statement(
            kind="state",
            text="Workspace exports run daily after invoices close.",
            links=[],
            allow_phrasing_violations=True,
        )["statement_id"]
    finally:
        auth.current_principal.reset(token)
    token = _principal("drafter")
    try:
        queued = server.patch_statement(
            statement_id,
            text="Workspace exports run daily after invoice processing.",
            allow_phrasing_violations=True,
        )
        draft_id = queued["draft_id"]
        current = server.set_draft_review_evidence(
            draft_id,
            "The workspace export schedule was verified as daily.",
            queued["revision"],
        )
        current = server.set_operation_evidence(
            draft_id,
            queued["operation_ref"],
            [
                {
                    "kind": "code",
                    "path": "exports/schedule.py",
                    "excerpt": "export cadence = daily",
                    "claim": "The export scheduler uses a daily cadence.",
                }
            ],
            current["revision"],
        )
        server.submit_draft(draft_id)
    finally:
        auth.current_principal.reset(token)
    return draft_id, statement_id


def test_grounded_answer_is_recorded_and_starts_a_fresh_review(
    answer_server, monkeypatch
):
    reviews: list[dict[str, object]] = []

    def review(context: str) -> Assessment:
        parsed = json.loads(context)
        reviews.append(parsed)
        return _assessment(
            "good" if parsed.get("answers_from_curators") else "needs_context"
        )

    prompts: list[dict[str, object]] = []

    def answer(task, config):
        prompts.append(json.loads(task.prompt))
        statement_id = prompts[0]["knowledge_base_statements"][0]["id"]
        return (
            draft_answers.AnswerAttempt(
                answerable=True,
                answer="Yes. The supplied sources establish a daily schedule.",
                sources=[
                    draft_answers.Source(
                        statement_id=statement_id,
                        quote="Workspace exports run daily",
                    ),
                    draft_answers.Source(
                        statement_id="",
                        quote="workspace export schedule was verified as daily",
                    ),
                    draft_answers.Source(
                        statement_id="", quote="export cadence = daily"
                    ),
                ],
                reason="All questions are settled by supplied sources.",
            ),
            ai.Usage(),
        )

    monkeypatch.setattr(draft_review_runs, "RUNNER", review)
    monkeypatch.setattr(draft_answers, "_call", answer)
    draft_id, statement_id = _draft()
    draft_review_runs.wait_all()

    latest = server.get_draft(draft_id)["review_assessment"]
    assert latest["application"] == "applied"
    assert len(reviews) == 2
    [recorded] = latest["answers"]
    assert recorded["answered_by"] == "model:gpt-fixture"
    assert recorded["run_id"] != latest["run_id"]
    assert [item["statement_id"] for item in recorded["evidence"]] == [
        statement_id,
        None,
        None,
    ]
    assert recorded["evidence"][1]["draft_id"] == draft_id
    assert recorded["evidence"][2]["path"] == "exports/schedule.py"
    assert prompts[0]["draft"]["operations"][0]["kind"] == "patch_statement"


@pytest.mark.parametrize(
    "case", ["unknown_statement", "wrong_quote", "no_sources", "not_answerable"]
)
def test_ungrounded_answer_leaves_the_run_waiting(answer_server, monkeypatch, case):
    calls = 0

    def answer(task, config):
        nonlocal calls
        calls += 1
        statement_id = json.loads(task.prompt)["knowledge_base_statements"][0]["id"]
        sources = (
            [draft_answers.Source(statement_id="stm_unknown", quote="daily")]
            if case == "unknown_statement"
            else [
                draft_answers.Source(
                    statement_id=statement_id,
                    quote="This quote was never in the statement.",
                )
            ]
            if case == "wrong_quote"
            else []
        )
        result = draft_answers.AnswerAttempt(
            answerable=case != "not_answerable",
            answer="" if case == "not_answerable" else "Yes.",
            sources=sources,
            reason=(
                "The supplied sources do not settle the question."
                if case == "not_answerable"
                else "Grounded."
            ),
        )
        return result, ai.Usage()

    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment("needs_context")
    )
    monkeypatch.setattr(draft_answers, "_call", answer)
    draft_id, _ = _draft()
    draft_review_runs.wait_all()

    run = server.get_draft(draft_id)["review_assessment"]
    assert calls == 1
    assert run["application"] == "needs_human"
    assert run["answers"] == []
    assert "no grounded answer" in run["detail"]


def test_setting_off_makes_no_answer_call(answer_server, monkeypatch):
    calls = 0

    def answer(task, config):
        nonlocal calls
        calls += 1
        raise AssertionError("answer model must not be called")

    set_review_controls(answer_questions=False)
    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment("needs_context")
    )
    monkeypatch.setattr(draft_answers, "_call", answer)
    draft_id, _ = _draft()
    draft_review_runs.wait_all()

    assert calls == 0
    assert (
        server.get_draft(draft_id)["review_assessment"]["application"] == "needs_human"
    )


@pytest.mark.parametrize("provider,model_answers", [("agent", 0), ("openai", 2)])
def test_external_runs_and_two_model_answers_skip_the_attempt(provider, model_answers):
    run = ReviewRun(
        run_id="drv_answer",
        draft_id="drf_123456789abc",
        status="completed",
        mode="review-and-apply",
        draft_revision=1,
        provider=provider,
        model=None if provider == "agent" else "gpt-fixture",
        application="needs_human",
        questions=["Does the export run daily?"],
        answers=[
            Answer(
                run_id=f"drv_{index}",
                questions=[],
                answer="Earlier answer.",
                answered_by=f"model:model-{index}",
            )
            for index in range(model_answers)
        ],
    )
    settings = draft_review_settings.Snapshot(
        mode="review-and-apply", answer_questions=True, model="gpt-fixture"
    )
    called = False

    def answer(task, config):
        nonlocal called
        called = True
        raise AssertionError("answer model must not be called")

    assert draft_answers.attempt(run, {}, settings, call=answer) is None
    assert called is False
