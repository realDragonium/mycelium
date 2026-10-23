import json
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from mycelium import (
    ai,
    ai_usage,
    auth,
    draft_review_model,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    embed,
    product_settings,
    server,
    store,
    timestamps,
)
from mycelium.draft_review_store import Assessment, Correction
from mycelium.server import draft_review, runtime
from product_settings_helpers import set_product
from settings_helpers import save_model
from settings_helpers import set_review_controls as _set_review_controls
from test_reviewed_application import _app, _principal


def _assessment(label="good", corrections=(), contradictions=()):
    return Assessment(
        label=label,
        rationale="Supported by supplied facts.",
        questions=["What evidence establishes the changed behavior?"]
        if label == "needs_context"
        else [],
        corrections=list(corrections),
        contradictions=list(contradictions),
    )


def _set_review_model(model):
    save_model("draft_review", openai_model=model)


@pytest.fixture
def running_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "off")
    monkeypatch.delenv("MYCELIUM_REVIEWED_APPLY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())
    with _app(tmp_path, monkeypatch) as client:
        with store.transaction(runtime._auth_db()):
            reviewer = auth.create_user(
                runtime._auth_db(), name="Reviewer", role="writer", type="service"
            )
        _set_review_controls(reviewer_id=reviewer)
        _set_review_model("gpt-fixture")
        yield client, reviewer
        draft_review_runs.wait_all()


@pytest.fixture
def review_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    server.init(tmp_path)
    with store.transaction(runtime._auth_db()):
        reviewer = auth.create_user(
            runtime._auth_db(), name="Reviewer", role="writer", type="service"
        )
    _set_review_controls(reviewer_id=reviewer)
    _set_review_model("gpt-fixture")
    yield
    draft_review_runs.wait_all()


def _draft(*, submit=True):
    token = _principal("drafter")
    try:
        queued = server.upsert_entity(
            name="Review subject", description="Supplied fact"
        )
        draft_id = queued["draft_id"]
        current = server.get_draft(draft_id)
        server.set_draft_review_evidence(
            draft_id,
            "The subject exists and its description is Supplied fact.",
            current["revision"],
        )
        if submit:
            server.submit_draft(draft_id)
        return draft_id
    finally:
        auth.current_principal.reset(token)


def _request(draft_id, *, rerun=False):
    token = _principal()
    try:
        return server.request_draft_review(draft_id, rerun)
    finally:
        auth.current_principal.reset(token)


def _result(draft_id):
    draft_review_runs.wait_all()
    return server.get_draft(draft_id)["review_assessment"]


@pytest.mark.parametrize(
    "label", ["good", "changes_suggested", "reject", "needs_context"]
)
def test_review_only_is_advisory(running_app, monkeypatch, label):
    _set_review_controls(mode="review-only")
    corrections = (
        [
            Correction(
                action="append",
                operation_ref=None,
                tool_name="upsert_entity",
                payload_json='{"name":"Omitted subject","description":"Supplied omission"}',
                reason="Document the omission.",
            )
        ]
        if label == "changes_suggested"
        else []
    )
    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment(label, corrections)
    )
    draft_id = _draft()
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert result["label"] == label
    assert result["application"] == "unapplied"
    draft = server.get_draft(draft_id)
    assert draft["status"] == "submitted"
    assert len(draft["ops"]) == 1
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    assert server.list_entities()["entities"] == []
    assert result["corrections"] == [c.model_dump() for c in corrections]


def test_both_submission_paths_trigger_and_off_is_default(running_app, monkeypatch):
    client, _ = running_app
    draft_id = _draft()
    assert server.get_draft(draft_id)["review_assessment"] is None
    with pytest.raises(ValueError, match="off"):
        _request(draft_id)
    next_id = _draft(submit=False)
    _set_review_controls(mode="review-only")
    response = client.post(f"/api/drafts/{next_id}/submit")
    assert response.status_code == 200
    result = _result(next_id)
    assert result["label"] == "good"
    listed = client.get("/api/drafts?status=all").json()["drafts"]
    assert next(d for d in listed if d["id"] == next_id)["review_assessment"] == {
        "run_id": result["run_id"],
        "status": "completed",
        "label": "good",
        "application": result["application"],
        "stale": False,
    }


def test_rerun_concurrency_and_evidence_staleness(running_app, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def model(context):
        calls.append(context)
        entered.set()
        assert release.wait(5)
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    draft_id = _draft()
    _set_review_controls(mode="review-only")
    first = _request(draft_id)
    assert entered.wait(5)
    duplicate = _request(draft_id, rerun=True)
    assert duplicate["run_id"] == first["run_id"]
    token = _principal("drafter")
    try:
        server.set_draft_review_evidence(
            draft_id, "Changed evidence", server.get_draft(draft_id)["revision"]
        )
    finally:
        auth.current_principal.reset(token)
    release.set()
    result = _result(draft_id)
    assert result["stale"] is True
    listed = drafts_store.list_draft_summaries(server._drafts_db())
    assert next(d for d in listed if d["id"] == draft_id)["review_assessment"]["stale"]
    assert result["status"] == "failed"
    assert "changed" in result["detail"]
    assert _request(draft_id)["run_id"] == first["run_id"]
    second = _request(draft_id, rerun=True)
    assert second["run_id"] != first["run_id"]
    assert _result(draft_id)["stale"] is False
    assert len(calls) == 2


@pytest.mark.parametrize(
    "change", ["off", "review-only", "demote", "same-creator", "different-user"]
)
def test_running_review_cannot_retain_mutation_privilege(
    running_app, monkeypatch, change
):
    _, reviewer = running_app
    draft_id = _draft()

    def model(context):
        if change in ("off", "review-only"):
            _set_review_controls(mode=change)
        elif change == "demote":
            with store.transaction(runtime._auth_db()):
                runtime._auth_db().execute(
                    "UPDATE users SET role = 'drafter' WHERE id = ?", (reviewer,)
                )
        elif change == "same-creator":
            _set_review_controls(reviewer_id="drafter-1")
        else:
            with store.transaction(runtime._auth_db()):
                other = auth.create_user(
                    runtime._auth_db(), name="Other", role="writer", type="service"
                )
            _set_review_controls(reviewer_id=other)
        return _assessment("reject")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []


def test_review_only_cannot_upgrade_inflight(running_app, monkeypatch):
    draft_id = _draft()

    def model(context):
        _set_review_controls(mode="review-and-apply")
        return _assessment("reject")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _set_review_controls(mode="review-only")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    assert _result(draft_id)["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"


@pytest.mark.parametrize("label", ["good", "reject"])
def test_automatic_outcomes(running_app, monkeypatch, label):
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment(label))
    draft_id = _draft()
    result = _result(draft_id)
    assert result["status"] == "completed"
    assert result["application"] == ("applied" if label == "good" else "rejected")
    assert server.get_draft(draft_id)["status"] == (
        "approved" if label == "good" else "rejected"
    )


def test_corrections_apply_as_exact_reviewed_revision(running_app, monkeypatch):
    draft_id = _draft()
    draft = server.get_draft(draft_id)
    correction = Correction(
        action="revise",
        operation_ref=draft["ops"][0]["operation_ref"],
        tool_name=None,
        payload_json='{"name":"Review subject","description":"Corrected fact"}',
        reason="Use the corrected supplied description.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert result["application"] == "applied"
    assert result["stale"] is False
    assert result["draft_revision"] == draft["revision"] + 1
    assert server.list_entities()["entities"][0]["description"] == "Corrected fact"


def test_revise_naming_its_own_operation_tool_still_applies(running_app, monkeypatch):
    draft_id = _draft()
    op = server.get_draft(draft_id)["ops"][0]
    correction = Correction(
        action="revise",
        operation_ref=op["operation_ref"],
        tool_name=op["kind"],
        payload_json='{"name":"Review subject","description":"Corrected fact"}',
        reason="Use the corrected supplied description.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    assert _result(draft_id)["application"] == "applied"
    assert server.list_entities()["entities"][0]["description"] == "Corrected fact"


def test_correction_leaving_a_phrasing_finding_fails_naming_it(
    running_app, monkeypatch
):
    draft_id = _draft()
    correction = Correction(
        action="append",
        operation_ref=None,
        tool_name="upsert_statement",
        payload_json=(
            '{"kind":"rule","links":[],'
            '"text":"An invoice is locked because it was exported"}'
        ),
        reason="Add the export rule.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert "still has operation findings" in result["previous_failure"]
    assert "because" in result["previous_failure"]


def test_default_application_gate_and_bad_reviewer(running_app, monkeypatch):
    _set_review_controls(mode="review-and-apply")
    draft_id = _draft()
    assert "gate is disabled" in _result(draft_id)["detail"]
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    _set_review_controls(reviewer_id="local-admin")
    _request(draft_id, rerun=True)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert "active real writer" in result["detail"]


def test_interrupted_runs_are_retryable(running_app, monkeypatch):
    draft_id = _draft()
    conn = server._drafts_db()
    with store.transaction(conn):
        run = draft_review_store.new(
            draft_id, "review-only", server.get_draft(draft_id)["revision"]
        )
        draft_review_store.save(conn, run)
    draft_review_store.mark_orphaned(conn)
    assert _result(draft_id)["status"] == "failed"
    assert "interrupted" in _result(draft_id)["detail"]
    _set_review_controls(mode="review-only")
    _request(draft_id, rerun=True)
    assert _result(draft_id)["status"] == "completed"


def test_openai_wire_is_fresh_structured_and_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")

    def handle(request):
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert body["model"] == "fixture-gpt"
        assert body["store"] is False
        assert body["input"] == [{"role": "user", "content": "Review evidence"}]
        assert body["text"]["format"]["strict"] is True
        schema = body["text"]["format"]["schema"]
        for node in (schema, schema["$defs"]["Correction"]):
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": _assessment().model_dump_json(),
                            }
                        ],
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            draft_review_model.assess(
                "Review evidence", model="fixture-gpt", client=client
            ).label
            == "good"
        )


@pytest.mark.parametrize(
    "response",
    [
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal"}]}],
        },
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}
            ],
        },
    ],
)
def test_openai_incomplete_or_refused_output_is_not_success(monkeypatch, response):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        with pytest.raises(ValueError):
            draft_review_model.assess(
                "Review evidence", model="fixture-gpt", client=client
            )


def _supporting_statement():
    token = _principal()
    try:
        result = server.upsert_statement(
            kind="state",
            text="A supporting feature is available.",
            links=[],
            allow_phrasing_violations=True,
        )
        return result["statement_id"]
    finally:
        auth.current_principal.reset(token)


def test_supporting_knowledge_change_blocks_automatic_action(running_app, monkeypatch):
    statement_id = _supporting_statement()
    draft_id = _draft()

    def model(context):
        assert statement_id in context
        server.patch_statement(
            statement_id,
            text="The supporting feature is unavailable.",
            allow_phrasing_violations=True,
        )
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed", result
    assert "supporting knowledge changed" in result["detail"]
    assert result["application"] == "rejected"
    assert server.list_entities()["entities"] == []


def test_authoritative_support_preconditions_survive_later_apply(
    running_app, monkeypatch
):
    statement_id = _supporting_statement()
    draft_id = _draft()
    token = _principal()
    try:
        inspection = server.inspect_draft_review(draft_id)
        conditions = [
            {
                "kind": "statement",
                "id": statement_id,
                "fingerprint": draft_review._fingerprint(
                    server.get_statements([statement_id])
                ),
            }
        ]
        review = server.record_draft_review(
            draft_id, "accepted", "Supported.", inspection["draft_revision"], conditions
        )
        server.patch_statement(
            statement_id,
            text="The supporting feature is unavailable.",
            allow_phrasing_violations=True,
        )
        with pytest.raises(ValueError, match="knowledge changed"):
            server.record_draft_review(
                draft_id,
                "accepted",
                "Supported.",
                inspection["draft_revision"],
                conditions,
            )
        _set_review_controls(application_enabled=True)
        with pytest.raises(ValueError, match="knowledge changed"):
            server.apply_reviewed_draft(draft_id, review["review_id"])
        assert server.get_draft(draft_id)["status"] == "submitted"
    finally:
        auth.current_principal.reset(token)


def test_failed_correction_batch_rolls_back_all_edits(running_app, monkeypatch):
    draft_id = _draft()
    before = server.get_draft(draft_id)
    corrections = [
        Correction(
            action="revise",
            operation_ref=before["ops"][0]["operation_ref"],
            tool_name=None,
            payload_json='{"name":"Edited","description":"Changed description"}',
            reason="Correction.",
        ),
        Correction(
            action="append",
            operation_ref=None,
            tool_name="patch_statement",
            payload_json='{"id":"stm_uninspected","text":"A missing record is changed."}',
            reason="Remove unsupported operation.",
        ),
    ]
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", corrections),
    )
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed", result
    assert result["application"] == "rejected"
    after = server.get_draft(draft_id)
    assert before["ops"] == after["ops"]
    assert before["revision"] == after["revision"]
    assert [
        r["outcome"] for r in drafts_store.list_reviews(server._drafts_db(), draft_id)
    ] == ["rejected"]


def test_source_attach_invalidates_completed_assessment(running_app, monkeypatch):
    _set_review_controls(mode="review-only")
    draft_id = _draft()
    assert _result(draft_id)["stale"] is False
    token = _principal("drafter")
    try:
        source = {
            "repository": "org/repo",
            "pull_request": 42,
            "merged_commit": "a" * 40,
            "workflow_run_id": 1,
            "workflow_run_attempt": 1,
        }
        server.attach_draft_source(
            draft_id, source, server.get_draft(draft_id)["revision"]
        )
    finally:
        auth.current_principal.reset(token)
    assert server.get_draft(draft_id)["review_assessment"]["stale"] is True


def test_drafter_cannot_request_or_impersonate_reviewer(running_app, monkeypatch):
    draft_id = _draft()
    _set_review_controls(mode="review-only")
    token = _principal("drafter")
    try:
        with pytest.raises(auth.RoleRequired):
            server.request_draft_review(draft_id)
    finally:
        auth.current_principal.reset(token)
    with store.transaction(runtime._auth_db()):
        runtime._auth_db().execute(
            "INSERT INTO users(id, name, role, type, status, created_at) VALUES ('drafter-1', 'Creator', 'writer', 'service', 'active', 'now')"
        )
    _set_review_controls(reviewer_id="drafter-1")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert "independent" in result["detail"]


def test_review_without_credentials_is_refused_before_a_run(running_app, monkeypatch):
    draft_id = _draft()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _set_review_controls(mode="review-only")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _request(draft_id)
    assert _result(draft_id) is None
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment("needs_context")
    )
    _request(draft_id, rerun=True)
    assert _result(draft_id)["label"] == "needs_context"


@pytest.mark.parametrize("role", ["reader", "drafter", "writer", "admin"])
def test_http_review_uses_real_curator_role(running_app, monkeypatch, role):
    client, _ = running_app
    draft_id = _draft()
    conn = runtime._auth_db()
    with store.transaction(conn):
        user_id = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(conn, user_id=user_id, name="Fixture", scope=role)
    headers = {"Authorization": f"Bearer {raw}"}
    _set_review_controls(mode="review-only")
    settings = client.get("/api/draft-review/settings", headers=headers)
    assert settings.json()["mode"] == "review-only"
    assert settings.json()["can_review"] == (role in ("writer", "admin"))
    response = client.post(f"/api/drafts/{draft_id}/review", headers=headers)
    assert response.status_code == (200 if role in ("writer", "admin") else 403)
    if response.status_code == 200:
        assert _result(draft_id)["status"] == "completed"
    else:
        assert server.get_draft(draft_id)["review_assessment"] is None


def test_http_review_refuses_off_open_and_terminal_drafts(running_app, monkeypatch):
    client, _ = running_app
    draft_id = _draft()
    settings = client.get("/api/draft-review/settings").json()
    assert settings["mode"] == "off"
    assert settings["can_review"] is True
    response = client.post(f"/api/drafts/{draft_id}/review")
    assert response.status_code == 400
    assert "off" in response.json()["detail"]
    _set_review_controls(mode="review-only")
    open_id = _draft(submit=False)
    assert client.post(f"/api/drafts/{open_id}/review").status_code == 400
    assert client.post(f"/api/drafts/{draft_id}/reject").status_code == 200
    assert client.post(f"/api/drafts/{draft_id}/review").status_code == 400
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    assert client.get("/api/draft-review/settings").status_code == 401


def test_http_rerun_uses_current_mode_and_fresh_model(running_app, monkeypatch):
    client, _ = running_app
    draft_id = _draft()
    calls = []

    def model(context):
        calls.append(context)
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _set_review_controls(mode="review-only")
    first = client.post(f"/api/drafts/{draft_id}/review").json()["review"]
    assert _result(draft_id)["application"] == "unapplied"
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    second = client.post(f"/api/drafts/{draft_id}/review").json()["review"]
    assert second["run_id"] != first["run_id"]
    result = _result(draft_id)
    assert result["mode"] == "review-and-apply"
    assert result["application"] == "applied", result
    assert len(calls) == 2


def test_submission_burst_waits_for_workers_and_deduplicates(running_app, monkeypatch):
    client, _ = running_app
    release = threading.Event()
    calls = []

    def model(context):
        calls.append(context)
        assert release.wait(5)
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _set_review_controls(mode="review-only")
    try:
        draft_ids = [_draft() for _ in range(4)]
        for draft_id in draft_ids:
            current = server.get_draft(draft_id)["review_assessment"]
            duplicate = client.post(f"/api/drafts/{draft_id}/review").json()["review"]
            assert duplicate["run_id"] == current["run_id"]
            assert duplicate["status"] == "running"
    finally:
        release.set()
    assert all(_result(identity)["status"] == "completed" for identity in draft_ids)
    assert len(calls) == 4


@pytest.mark.parametrize("label", ["good", "reject"])
def test_interrupted_final_status_recovers_committed_outcome(
    running_app, monkeypatch, label
):
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment(label))
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    draft_id = _draft()
    result = _result(draft_id)
    assert result["status"] == "completed", result
    run = draft_review_store.get(server._drafts_db(), result["run_id"])
    run.status = "running"
    run.application = "unapplied"
    with store.transaction(server._drafts_db()):
        draft_review_store.save(server._drafts_db(), run)
    draft_review_store.mark_orphaned(server._drafts_db())
    recovered = server.get_draft(draft_id)["review_assessment"]
    assert recovered["status"] == "completed"
    assert recovered["application"] == ("applied" if label == "good" else "rejected")


def test_invalid_advisory_correction_is_failed_without_label(running_app, monkeypatch):
    draft_id = _draft()
    correction = Correction(
        action="revise",
        operation_ref="op_nonexistent",
        tool_name=None,
        payload_json='{"name":"Unsupported"}',
        reason="An invalid model reference.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    _set_review_controls(mode="review-only")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert result["label"] is None
    assert "operation_ref" in result["detail"]
    assert len(server.get_draft(draft_id)["ops"]) == 1


@pytest.mark.parametrize(
    ("links", "valid"),
    [
        ([], True),
        ([{"to_id": "stm_existing", "link_type": "supports"}], True),
        ([{"to_id": "stm_existing"}], False),
        ([{"to_id": 123, "link_type": "supports"}], False),
    ],
)
def test_advisory_statement_correction_validates_link_spec(
    running_app, monkeypatch, links, valid
):
    draft_id = _draft()
    correction = Correction(
        action="append",
        operation_ref=None,
        tool_name="upsert_statement",
        payload_json=json.dumps(
            {"kind": "state", "text": "The subject is documented.", "links": links}
        ),
        reason="Document the supplied statement.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    _set_review_controls(mode="review-only")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == ("completed" if valid else "failed"), result
    assert result["label"] == ("changes_suggested" if valid else None)
    assert result["application"] == "unapplied"
    assert len(server.get_draft(draft_id)["ops"]) == 1


def test_configuration_downgrade_during_corrections_rolls_back(
    running_app, monkeypatch
):
    draft_id = _draft()
    before = server.get_draft(draft_id)
    correction = Correction(
        action="revise",
        operation_ref=before["ops"][0]["operation_ref"],
        tool_name=None,
        payload_json='{"name":"Review subject","description":"Corrected fact"}',
        reason="Correct supplied fact.",
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction]),
    )
    original = server.revise_draft_operation

    def downgrade(*args, **kwargs):
        result = original(*args, **kwargs)
        _set_review_controls(mode="review-only")
        return result

    monkeypatch.setattr(server, "revise_draft_operation", downgrade)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert result["application"] == "unapplied"
    after = server.get_draft(draft_id)
    assert after["ops"] == before["ops"]
    assert after["revision"] == before["revision"]
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []


def test_committed_substrate_receipt_survives_failed_finalization(
    running_app, monkeypatch
):
    original = drafts_store.finish_application

    def fail_finalization(conn, application_id, *, status, **kwargs):
        if status == "committed":
            raise RuntimeError("Fixture interruption after substrate commit")
        return original(conn, application_id, status=status, **kwargs)

    monkeypatch.setattr(drafts_store, "finish_application", fail_finalization)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    draft_id = _draft()
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert result["application"] == "applied"
    assert "durable receipt" in result["detail"]
    assert len(server.list_entities()["entities"]) == 1
    monkeypatch.setattr(drafts_store, "finish_application", original)
    token = _principal()
    try:
        server.apply_reviewed_draft(draft_id, result["review_id"])
    finally:
        auth.current_principal.reset(token)
    assert server.get_draft(draft_id)["status"] == "approved"
    assert len(server.list_entities()["entities"]) == 1


def test_http_evidence_requires_creator_and_preserves_revision(running_app):
    client, _ = running_app
    draft_id = _draft()
    before = server.get_draft(draft_id)
    response = client.post(
        "/set-draft-review-evidence",
        json={
            "draft_id": draft_id,
            "evidence": "Replacement by another user",
            "expected_revision": before["revision"],
        },
    )
    assert response.status_code == 403
    after = server.get_draft(draft_id)
    assert after["revision"] == before["revision"]
    assert after["review_evidence"] == before["review_evidence"]


def test_struck_entity_remains_an_authoritative_support_precondition(
    running_app, monkeypatch
):
    token = _principal()
    try:
        entity_id = server.upsert_entity(
            name="Review subject", description="Existing supporting fact"
        )["entity_id"]
    finally:
        auth.current_principal.reset(token)
    draft_id = _draft()
    draft = server.get_draft(draft_id)
    corrections = [
        Correction(
            action="strike",
            operation_ref=draft["ops"][0]["operation_ref"],
            tool_name=None,
            payload_json=None,
            reason="Keep the existing entity.",
        ),
        Correction(
            action="append",
            operation_ref=None,
            tool_name="upsert_entity",
            payload_json='{"name":"Another subject","description":"Supported fact"}',
            reason="Document the omission.",
        ),
    ]
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", corrections),
    )
    original = server.apply_reviewed_draft

    def interrupt(*args, **kwargs):
        raise RuntimeError("Fixture interruption before application")

    monkeypatch.setattr(server, "apply_reviewed_draft", interrupt)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed", result
    assert result["review_id"] is not None
    conditions = result["knowledge_preconditions"]
    assert any(item["id"] == entity_id for item in conditions)
    monkeypatch.setattr(server, "apply_reviewed_draft", original)
    token = _principal()
    try:
        server.upsert_entity(
            name="Review subject", description="Changed supporting fact"
        )
        with pytest.raises(ValueError, match="knowledge changed"):
            server.apply_reviewed_draft(draft_id, result["review_id"])
    finally:
        auth.current_principal.reset(token)
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert len(server.list_entities()["entities"]) == 1


@pytest.mark.parametrize("as_correction", [False, True])
def test_uninspected_glossary_cannot_be_automatically_overwritten(
    running_app, monkeypatch, as_correction
):
    token = _principal()
    try:
        server.upsert_link_type("fixture-relation", "Original glossary meaning")
    finally:
        auth.current_principal.reset(token)
    draft_id = _draft(submit=False)
    if as_correction:
        correction = Correction(
            action="append",
            operation_ref=None,
            tool_name="upsert_link_type",
            payload_json='{"link_type":"fixture-relation","description":"Uninspected overwrite"}',
            reason="Change the glossary.",
        )
        monkeypatch.setattr(
            draft_review_runs,
            "RUNNER",
            lambda context: _assessment("changes_suggested", [correction]),
        )
    else:
        token = _principal("drafter")
        try:
            server.upsert_link_type(
                "fixture-relation", "Uninspected overwrite", draft_id=draft_id
            )
        finally:
            auth.current_principal.reset(token)
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)
    token = _principal("drafter")
    try:
        server.submit_draft(draft_id)
    finally:
        auth.current_principal.reset(token)
    result = _result(draft_id)
    assert result["application"] == "rejected", result
    if as_correction:
        assert "supported tool_name" in result["detail"]
    else:
        assert "upsert_link_type" in result["rationale"]
    assert server.get_draft(draft_id)["status"] == "rejected"
    assert "Original glossary meaning" in json.dumps(server.list_link_types())
    assert "Uninspected overwrite" not in json.dumps(server.list_link_types())


def _gaps():
    return [row["text"] for row in store.list_knowledge_gaps(server._db())]


def _automatic():
    _set_review_controls(mode="review-and-apply")
    _set_review_controls(application_enabled=True)


def test_resolved_contradiction_is_filed_as_gap_after_apply(running_app, monkeypatch):
    statement_id = _supporting_statement()
    correction = Correction(
        action="append",
        operation_ref=None,
        tool_name="replace_text",
        payload_json=json.dumps(
            {"id": statement_id, "text": "A supporting feature is retired."}
        ),
        reason="The draft supersedes this statement.",
    )
    contradiction = draft_review_store.Contradiction(
        statement_id=statement_id, resolution="Marked the feature as retired."
    )
    monkeypatch.setattr(
        draft_review_runs,
        "RUNNER",
        lambda context: _assessment("changes_suggested", [correction], [contradiction]),
    )
    _automatic()
    draft_id = _draft()
    assert _result(draft_id)["application"] == "applied"
    [gap] = _gaps()
    assert draft_id in gap and statement_id in gap
    assert "Marked the feature as retired." in gap
    # Filed after the apply, so the apply does not resolve it.
    [row] = store.list_knowledge_gaps(server._db(), status="open")
    assert (row["draft_id"], row["statement_id"]) == (draft_id, statement_id)


def test_rejected_draft_is_filed_as_gap(running_app, monkeypatch):
    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment("reject")
    )
    _automatic()
    draft_id = _draft()
    assert _result(draft_id)["application"] == "rejected"
    [gap] = _gaps()
    assert draft_id in gap and "Supported by supplied facts." in gap
    [row] = store.list_knowledge_gaps(server._db())
    assert row["draft_id"] == draft_id


def test_draft_failure_is_retried_once_then_rejected(running_app, monkeypatch):
    calls = []

    def model(context):
        calls.append(context)
        raise ValueError("Fixture draft defect")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _automatic()
    draft_id = _draft()
    result = _result(draft_id)
    assert len(calls) == 2
    assert "previous_attempt_failure" not in json.loads(calls[0])
    assert json.loads(calls[1])["previous_attempt_failure"] == "Fixture draft defect"
    assert result["attempt"] == 2
    assert result["application"] == "rejected"
    assert server.get_draft(draft_id)["status"] == "rejected"
    [gap] = _gaps()
    assert "Fixture draft defect" in gap


def test_provider_failure_is_retried_once_and_never_rejects(running_app, monkeypatch):
    calls = []

    def model(context):
        calls.append(context)
        raise ai.ModelError("Fixture provider outage")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _automatic()
    draft_id = _draft()
    result = _result(draft_id)
    assert len(calls) == 2
    assert result["status"] == "failed"
    assert result["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert _gaps() == []


@pytest.mark.parametrize(
    "attempt,retries", [(1, 0), (2, draft_review_runs.MAX_RETRIES)]
)
def test_budget_pause_does_not_fail_rerun_or_reject(
    review_server, monkeypatch, attempt, retries
):
    draft_id = _draft()
    calls = []

    def paused(context):
        calls.append(context)
        raise ai.usage.Paused("Paused: monthly AI budget reached.")

    monkeypatch.setattr(draft_review_runs, "RUNNER", paused)
    _automatic()
    run = draft_review_runs.start(draft_id, attempt=attempt, retries=retries)
    result = _result(draft_id)

    assert len(calls) == 1
    assert result["status"] == "paused"
    assert result["detail"] == "Paused: monthly AI budget reached."
    assert (result["attempt"], result["retries"]) == (attempt, retries)
    assert result["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert draft_review_runs.backlog() == []
    assert _gaps() == []
    draft_review_store.mark_orphaned(server._drafts_db())
    assert draft_review_store.get(server._drafts_db(), run.run_id).status == "paused"


@pytest.mark.parametrize("resume", ["raise-budget", "disable-pausing", "new-month"])
def test_sweep_resumes_paused_reviews_without_retry_limits(
    review_server, monkeypatch, resume
):
    at = datetime(2026, 10, 1, tzinfo=UTC)
    budget = product_settings.AIBudgetSettings(
        monthly_limit_usd=1, pause_background=True
    )
    set_product(budget)
    with store.transaction(server._drafts_db()):
        ai_usage.record(
            server._drafts_db(),
            ai.usage.Call(
                action="draft_review",
                provider="openai",
                model="gpt-fixture",
                usage=ai.Usage(),
                cost_usd=1,
                duration_ms=1,
                ok=True,
                run_id=None,
                draft_id=None,
            ),
            at=timestamps.of(at),
        )
    draft_id = _draft()

    def paused(context):
        raise ai.usage.Paused("Paused: monthly AI budget reached.")

    monkeypatch.setattr(draft_review_runs, "RUNNER", paused)
    _automatic()
    monkeypatch.setattr(timestamps, "now", lambda: timestamps.of(at))
    draft_review_runs.start(
        draft_id,
        attempt=2,
        retries=draft_review_runs.MAX_RETRIES,
        previous_failure="Provider unavailable.",
    )
    paused_run = _result(draft_id)
    later = at + timedelta(days=10)
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())

    assert draft_review_runs.sweep(later) == []
    assert _result(draft_id)["run_id"] == paused_run["run_id"]
    if resume == "raise-budget":
        set_product(budget.model_copy(update={"monthly_limit_usd": 2}))
    elif resume == "disable-pausing":
        set_product(budget.model_copy(update={"pause_background": False}))
    else:
        later = at.replace(month=11)

    assert draft_review_runs.sweep(later) == [draft_id]
    result = _result(draft_id)
    assert result["run_id"] != paused_run["run_id"]
    assert (result["attempt"], result["retries"]) == (2, draft_review_runs.MAX_RETRIES)
    assert result["previous_failure"] == "Provider unavailable."
    assert result["application"] == "applied"


def test_sweep_does_not_resume_a_superseded_paused_run(review_server, monkeypatch):
    draft_id = _draft()

    def paused(context):
        raise ai.usage.Paused("Paused: monthly AI budget reached.")

    monkeypatch.setattr(draft_review_runs, "RUNNER", paused)
    _automatic()
    draft_review_runs.start(draft_id)
    selected = _result(draft_id)
    retry_due = draft_review_runs._retry_due
    interleaved = []

    def selection_then_manual_rerun(run, now):
        due = retry_due(run, now)
        if due and not interleaved:
            interleaved.append(run.run_id)
            monkeypatch.setattr(
                draft_review_runs, "RUNNER", lambda context: _assessment()
            )
            draft_review_runs.start(draft_id, rerun=True)
            draft_review_runs.wait_all()
        return due

    monkeypatch.setattr(draft_review_runs, "_retry_due", selection_then_manual_rerun)

    assert draft_review_runs.sweep() == []
    assert interleaved == [selected["run_id"]]
    assert _result(draft_id)["application"] == "applied"


def test_new_statement_context_includes_its_closest_live_statements(
    running_app, monkeypatch
):
    statement_id = _supporting_statement()
    contexts = []

    def model(context):
        contexts.append(json.loads(context))
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _automatic()
    token = _principal("drafter")
    try:
        queued = server.upsert_statement(
            kind="state",
            text="A supporting feature is available to every company.",
            links=[],
            allow_phrasing_violations=True,
        )
        server.submit_draft(queued["draft_id"])
    finally:
        auth.current_principal.reset(token)
    result = _result(queued["draft_id"])
    [context] = contexts
    assert statement_id in json.dumps(context["existing_knowledge"])
    assert context["link_types"]
    assert any(item["id"] == statement_id for item in result["knowledge_preconditions"])


def test_operation_evidence_reaches_the_reviewer(running_app, monkeypatch):
    contexts = []

    def model(context):
        contexts.append(context)
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    token = _principal("drafter")
    try:
        queued = server.upsert_entity(name="Invoice", description="A bill.")
        server.set_operation_evidence(
            queued["draft_id"],
            queued["operation_ref"],
            [
                {
                    "kind": "code",
                    "path": "billing/invoice.py",
                    "excerpt": "class Invoice(Model):",
                    "claim": "Invoices are a billing model.",
                }
            ],
            queued["revision"],
        )
        _set_review_controls(mode="review-only")
        server.submit_draft(queued["draft_id"])
    finally:
        auth.current_principal.reset(token)
    draft_review_runs.wait_all()

    (context,) = contexts
    (op,) = json.loads(context)["draft"]["ops"]
    assert op["evidence"][0]["excerpt"] == "class Invoice(Model):"
    assert "each operation's evidence" in json.loads(context)["knowledge_scope"]
