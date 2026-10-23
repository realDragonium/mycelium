import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from mycelium import (
    auth,
    auth_store,
    draft_review_store,
    drafts_store,
    embed,
    server,
    store,
)
from mycelium.http.drafts import approve_draft
from mycelium.server import draft_application, runtime


@pytest.fixture
def curator(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    server.init(tmp_path)
    principal = auth.Principal(
        id="curator-1", name="Curator", role="writer", type="human"
    )
    token = auth.current_principal.set(principal)
    request = Request({"type": "http"})
    request.state.principal = principal
    try:
        yield request
    finally:
        auth.current_principal.reset(token)


def _statement_draft(*, submitted=False):
    conn = server._drafts_db()
    with store.transaction(conn):
        draft_id = drafts_store.create_draft(
            conn, created_by="drafter-1", session_id=None
        )
        drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind="upsert_statement",
            payload={"kind": "event", "text": "A user exports invoices.", "links": []},
            created_by="drafter-1",
        )
        drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind="flag",
            payload={"reason": "Check the invoice export."},
            created_by="drafter-1",
        )
        if submitted:
            drafts_store.set_submitted(conn, draft_id)
    return draft_id


@pytest.mark.parametrize("submitted", [False, True])
@pytest.mark.parametrize("interruption", ["before_replay", "after_commit"])
def test_manual_approval_recovers_claim_after_restart(
    curator, tmp_path, monkeypatch, submitted, interruption
):
    draft_id = _statement_draft(submitted=submitted)

    def automated_check(*args, **kwargs):
        raise AssertionError("Manual approval must not run automated review checks")

    monkeypatch.setattr(draft_application, "_reviewed_apply_enabled", automated_check)
    monkeypatch.setattr(
        draft_application, "_review_knowledge_preconditions", automated_check
    )

    target, name = (
        (draft_application, "_apply_claimed_draft")
        if interruption == "before_replay"
        else (drafts_store, "set_decision")
    )
    original = getattr(target, name)

    def interrupt_once(*args, **kwargs):
        monkeypatch.setattr(target, name, original)
        raise RuntimeError("Approval interrupted")

    monkeypatch.setattr(target, name, interrupt_once)
    with pytest.raises(HTTPException) as error:
        approve_draft(draft_id, curator)
    assert error.value.status_code == 400
    conn = server._drafts_db()
    application = drafts_store.active_application(conn, draft_id)
    assert application["status"] == "claimed"
    assert drafts_store.status_for(drafts_store.get_draft(conn, draft_id)) == (
        "submitted" if submitted else "open"
    )
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == (
        0 if interruption == "before_replay" else 1
    )

    server.init(tmp_path)
    conn = server._drafts_db()
    assert drafts_store.active_application(conn, draft_id)["id"] == application["id"]
    assert draft_review_store.latest(conn, draft_id) is None

    if interruption == "after_commit":
        monkeypatch.setattr(draft_application, "_replay_draft_ops", automated_check)
    result = approve_draft(draft_id, curator)

    assert set(result) == {"ok", "applied", "skipped", "results"}
    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["skipped"] == 1
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 1
    draft = drafts_store.get_draft(conn, draft_id)
    assert drafts_store.status_for(draft) == "approved"
    assert draft["decided_by"] == curator.state.principal.id
    [review] = drafts_store.list_reviews(conn, draft_id)
    assert review["rationale"] == "Approved by hand."
    assert review["outcome"] == "accepted"
    assert review["reviewed_by"] == curator.state.principal.id
    assert review["draft_revision"] == draft["revision"]
    assert json.loads(review["preconditions_json"]) == []
    assert json.loads(review["unresolved_json"]) == []
    [finished] = drafts_store.list_applications(conn, draft_id)
    assert finished["status"] == "committed"
    assert finished["id"] == application["id"]
    receipt = (
        server._db()
        .execute(
            "SELECT review_id, result_json FROM reviewed_draft_applications "
            "WHERE application_id = ?",
            (application["id"],),
        )
        .fetchone()
    )
    assert receipt["review_id"] == review["id"]
    assert result == {"ok": True, **json.loads(receipt["result_json"])}


def test_manual_review_rolls_back_when_claim_fails(curator, monkeypatch):
    draft_id = _statement_draft()

    def fail_claim(*args, **kwargs):
        raise RuntimeError("Claim failed")

    monkeypatch.setattr(drafts_store, "claim_application", fail_claim)
    with pytest.raises(HTTPException) as error:
        approve_draft(draft_id, curator)
    assert error.value.status_code == 400
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    assert drafts_store.list_applications(server._drafts_db(), draft_id) == []
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def test_manual_rejection_releases_claim_for_edit_and_retry(curator):
    draft_id = _statement_draft()
    conn = server._drafts_db()
    with store.transaction(conn):
        drafts_store.update_op_payload(
            conn,
            draft_id,
            1,
            {"kind": "event", "text": "A user must log in.", "links": []},
        )

    with pytest.raises(HTTPException) as error:
        approve_draft(draft_id, curator)

    assert error.value.status_code == 422
    assert error.value.detail["rejections"][0]["text"] == "A user must log in."
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
    assert drafts_store.active_application(conn, draft_id) is None
    [failed] = drafts_store.list_applications(conn, draft_id)
    assert failed["status"] == "failed"
    with store.transaction(conn):
        drafts_store.update_op_payload(
            conn,
            draft_id,
            1,
            {"kind": "event", "text": "A user logs in.", "links": []},
        )

    assert approve_draft(draft_id, curator)["ok"] is True
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 1
    assert drafts_store.status_for(drafts_store.get_draft(conn, draft_id)) == "approved"


@pytest.mark.parametrize(
    "rationale", ["Invoice export matches the specification.", "Approved by hand."]
)
def test_manual_approval_conflicts_with_reviewed_claim(curator, rationale):
    draft_id = _statement_draft(submitted=True)
    conn = server._drafts_db()
    with store.transaction(conn):
        review_id = drafts_store.create_review(
            conn,
            draft_id=draft_id,
            outcome="accepted",
            rationale=rationale,
            draft_revision=drafts_store.current_revision(conn, draft_id),
            preconditions=[],
            unresolved_questions=[],
            reviewed_by="reviewer-1",
        )
        drafts_store.claim_application(
            conn, draft_id=draft_id, review_id=review_id, claimed_by="reviewer-1"
        )
    with pytest.raises(HTTPException) as error:
        approve_draft(draft_id, curator)
    assert error.value.status_code == 409
    assert len(drafts_store.list_reviews(conn, draft_id)) == 1
    assert server._db().execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
