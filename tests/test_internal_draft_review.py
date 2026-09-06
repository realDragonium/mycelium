import json
import threading

import httpx
import pytest

from mycelium import (
    auth,
    draft_review_model,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    server,
    store,
)
from mycelium.draft_review_store import Assessment, Correction
from test_reviewed_application import _app, _principal


def _assessment(label="good", corrections=()):
    return Assessment(
        label=label,
        rationale="Supported by supplied facts.",
        questions=["What evidence establishes the changed behavior?"]
        if label == "needs_context"
        else [],
        corrections=list(corrections),
    )


@pytest.fixture
def running_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "off")
    monkeypatch.delenv("MYCELIUM_REVIEWED_APPLY", raising=False)
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())
    with _app(tmp_path, monkeypatch) as client:
        with store.transaction(server._auth_db()):
            reviewer = auth.create_user(
                server._auth_db(), name="Reviewer", role="writer", type="service"
            )
        monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", reviewer)
        yield client, reviewer
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    response = client.post(f"/api/drafts/{next_id}/submit")
    assert response.status_code == 200
    assert _result(next_id)["label"] == "good"
    listed = client.get("/api/drafts?status=all").json()
    assert "review_assessment" in json.dumps(listed)


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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
            monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", change)
        elif change == "demote":
            with store.transaction(server._auth_db()):
                server._auth_db().execute(
                    "UPDATE users SET role = 'drafter' WHERE id = ?", (reviewer,)
                )
        elif change == "same-creator":
            monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", "drafter-1")
        else:
            with store.transaction(server._auth_db()):
                other = auth.create_user(
                    server._auth_db(), name="Other", role="writer", type="service"
                )
            monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", other)
        return _assessment("reject")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    _request(draft_id)
    result = _result(draft_id)
    assert result["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []


def test_review_only_cannot_upgrade_inflight(running_app, monkeypatch):
    draft_id = _draft()

    def model(context):
        monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
        return _assessment("reject")

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    _request(draft_id)
    assert _result(draft_id)["application"] == "unapplied"
    assert server.get_draft(draft_id)["status"] == "submitted"


@pytest.mark.parametrize("label", ["good", "reject", "needs_context"])
def test_automatic_outcomes(running_app, monkeypatch, label):
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment(label))
    draft_id = _draft()
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert (
        result["application"]
        == {"good": "applied", "reject": "rejected", "needs_context": "unapplied"}[
            label
        ]
    )
    assert (
        server.get_draft(draft_id)["status"]
        == {"good": "approved", "reject": "rejected", "needs_context": "submitted"}[
            label
        ]
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert result["application"] == "applied"
    assert result["stale"] is False
    assert result["draft_revision"] == draft["revision"] + 1
    assert server.list_entities()["entities"][0]["description"] == "Corrected fact"


def test_default_application_gate_and_bad_reviewer(running_app, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    draft_id = _draft()
    assert "gate is disabled" in _result(draft_id)["detail"]
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", "local-admin")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    _request(draft_id, rerun=True)
    assert _result(draft_id)["status"] == "completed"


def test_openai_wire_is_fresh_structured_and_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODEL", "fixture-gpt")

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
            draft_review_model.assess("Review evidence", client=client).label == "good"
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODEL", "fixture-gpt")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        with pytest.raises(ValueError):
            draft_review_model.assess("Review evidence", client=client)


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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed", result
    assert "supporting knowledge changed" in result["detail"]
    assert server.get_draft(draft_id)["status"] == "submitted"


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
                "fingerprint": server._fingerprint(
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
        monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed", result
    after = server.get_draft(draft_id)
    assert before["ops"] == after["ops"]
    assert before["revision"] == after["revision"]
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []


def test_source_attach_invalidates_completed_assessment(running_app, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    token = _principal("drafter")
    try:
        with pytest.raises(auth.RoleRequired):
            server.request_draft_review(draft_id)
    finally:
        auth.current_principal.reset(token)
    with store.transaction(server._auth_db()):
        server._auth_db().execute(
            "INSERT INTO users(id, name, role, type, status, created_at) VALUES ('drafter-1', 'Creator', 'writer', 'service', 'active', 'now')"
        )
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", "drafter-1")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert "independent" in result["detail"]


def test_model_failure_and_missing_configuration_are_visible(running_app, monkeypatch):
    draft_id = _draft()
    monkeypatch.setattr(draft_review_runs, "RUNNER", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MYCELIUM_DRAFT_REVIEW_MODEL", raising=False)
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "failed"
    assert "required" in result["detail"]
    assert result["application"] == "unapplied"
    monkeypatch.setattr(
        draft_review_runs, "RUNNER", lambda context: _assessment("needs_context")
    )
    _request(draft_id, rerun=True)
    assert _result(draft_id)["label"] == "needs_context"


@pytest.mark.parametrize("role", ["reader", "drafter", "writer", "admin"])
def test_http_review_uses_real_curator_role(running_app, monkeypatch, role):
    client, _ = running_app
    draft_id = _draft()
    conn = server._auth_db()
    with store.transaction(conn):
        user_id = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(conn, user_id=user_id, name="Fixture", scope=role)
    headers = {"Authorization": f"Bearer {raw}"}
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    settings = client.get("/api/draft-review/settings", headers=headers)
    assert settings.json() == {
        "mode": "review-only",
        "can_review": role in ("writer", "admin"),
    }
    response = client.post(f"/api/drafts/{draft_id}/review", headers=headers)
    assert response.status_code == (200 if role in ("writer", "admin") else 403)
    if response.status_code == 200:
        assert _result(draft_id)["status"] == "completed"
    else:
        assert server.get_draft(draft_id)["review_assessment"] is None


def test_http_review_refuses_off_open_and_terminal_drafts(running_app, monkeypatch):
    client, _ = running_app
    draft_id = _draft()
    assert client.get("/api/draft-review/settings").json() == {
        "mode": "off",
        "can_review": True,
    }
    response = client.post(f"/api/drafts/{draft_id}/review")
    assert response.status_code == 400
    assert "off" in response.json()["detail"]
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
    first = client.post(f"/api/drafts/{draft_id}/review").json()["review"]
    assert _result(draft_id)["application"] == "unapplied"
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
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
        monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-only")
        return result

    monkeypatch.setattr(server, "revise_draft_operation", downgrade)
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
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
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    token = _principal("drafter")
    try:
        server.submit_draft(draft_id)
    finally:
        auth.current_principal.reset(token)
    result = _result(draft_id)
    assert result["application"] == "unapplied", result
    if as_correction:
        assert result["status"] == "failed"
        assert "supported tool_name" in result["detail"]
    else:
        assert result["label"] == "needs_context"
        assert "upsert_link_type" in result["questions"][0]
    assert server.get_draft(draft_id)["status"] == "submitted"
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    assert "Original glossary meaning" in json.dumps(server.list_link_types())
    assert "Uninspected overwrite" not in json.dumps(server.list_link_types())
