"""A writer or admin agent deciding drafts over MCP: approve, approve with
corrections, reject, ask, and reopen, whatever the review setting."""

import pytest

from mycelium import (
    auth,
    auth_store,
    draft_review_store,
    drafts_store,
    embed,
    server,
    store,
)
from mycelium.server import runtime

AGENT = auth.Principal(id="agent-1", name="Agent", role="admin", type="service")
EVIDENCE = {
    "kind": "code",
    "path": "app/invoices/export.py",
    "lines": "10-24",
    "excerpt": "def export_invoices(workspace): ...",
    "claim": "Workspace admins can export invoices.",
}


@pytest.fixture(autouse=True)
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    server.init(tmp_path)
    token = auth.current_principal.set(AGENT)
    try:
        yield AGENT
    finally:
        auth.current_principal.reset(token)


def _draft(op="upsert_statement", payload=None, *, by="drafter-1"):
    conn = server._drafts_db()
    with store.transaction(conn):
        draft_id = drafts_store.create_draft(conn, created_by=by, session_id=None)
        drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind=op,
            payload=payload
            or {
                "kind": "capability",
                "text": "A workspace admin exports invoices.",
                "links": [],
            },
            created_by=by,
        )
        drafts_store.set_submitted(conn, draft_id)
    return draft_id


def _revision(draft_id):
    return server.get_draft(draft_id)["revision"]


def _texts():
    return {row["text"] for row in store.list_statements(store.substrate_connection())}


def test_approving_applies_the_draft_and_logs_the_agent_as_decider():
    draft_id = _draft()

    result = server.review_draft(
        draft_id,
        "approve",
        _revision(draft_id),
        reason="The export handler allows workspace admins.",
        evidence=[EVIDENCE],
    )

    draft = server.get_draft(draft_id)
    assert result["status"] == "approved" and result["applied"] == 1
    assert (draft["status"], draft["decided_by"]) == ("approved", "agent-1")
    [decision] = draft["decisions"]
    assert decision["action"] == "approved"
    assert decision["decided_by"] == "agent-1"
    assert decision["reason"] == "The export handler allows workspace admins."
    assert decision["evidence"][0]["path"] == "app/invoices/export.py"
    assert "A workspace admin exports invoices." in _texts()


def test_approving_with_corrections_applies_the_corrected_draft():
    draft_id = _draft()
    [op] = server.get_draft(draft_id)["ops"]
    correction = {
        "action": "edit",
        "operation_ref": op["operation_ref"],
        "statement": None,
        "text": "A workspace owner exports invoices.",
        "kind": None,
        "description": None,
        "link": None,
        "tool_name": None,
        "payload_json": None,
        "reason": "Only owners pass the export permission check.",
    }

    server.review_draft(
        draft_id,
        "approve_with_corrections",
        _revision(draft_id),
        corrections=[correction],
    )

    draft = server.get_draft(draft_id)
    assert draft["status"] == "approved"
    assert draft["decisions"][0]["corrections"] == [correction]
    assert "A workspace owner exports invoices." in _texts()
    assert "A workspace admin exports invoices." not in _texts()


def test_rejecting_then_reopening_lets_the_draft_be_decided_again():
    draft_id = _draft()
    with pytest.raises(ValueError, match="reject needs a reason"):
        server.review_draft(draft_id, "reject", _revision(draft_id))

    server.review_draft(
        draft_id, "reject", _revision(draft_id), reason="Not what the code does."
    )
    assert server.get_draft(draft_id)["status"] == "rejected"

    server.reopen_draft(draft_id, "The export check was read wrongly.")
    reopened = server.get_draft(draft_id)
    assert (reopened["status"], reopened["decided_by"]) == ("submitted", None)

    server.review_draft(draft_id, "approve", _revision(draft_id))
    actions = [d["action"] for d in server.get_draft(draft_id)["decisions"]]
    assert actions == ["rejected", "reopened", "approved"]


def test_a_principal_cannot_decide_or_reopen_its_own_draft():
    draft_id = _draft(by="agent-1")

    with pytest.raises(auth.RoleRequired, match="created by you"):
        server.review_draft(draft_id, "approve", _revision(draft_id))
    with pytest.raises(auth.RoleRequired, match="created by you"):
        server.reopen_draft(draft_id, "Try again.")
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_a_drafter_cannot_decide_drafts():
    draft_id = _draft()
    drafter = auth.Principal(id="drafter-2", name="D", role="drafter", type="service")
    token = auth.current_principal.set(drafter)
    try:
        with pytest.raises(auth.RoleRequired):
            server.review_draft(draft_id, "approve", _revision(draft_id))
    finally:
        auth.current_principal.reset(token)


def test_a_draft_changed_since_it_was_read_is_refused():
    draft_id = _draft()
    with pytest.raises(drafts_store.StaleDraftRevisionError, match="read it again"):
        server.review_draft(draft_id, "approve", _revision(draft_id) - 1)
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_newer_knowledge_refuses_approval_and_reopening():
    written = server.upsert_statement(
        kind="state", text="An export runs nightly.", links=[]
    )
    statement_id = written["statement_id"]
    draft_id = _draft(
        "patch_statement", {"id": statement_id, "text": "An export runs hourly."}
    )
    server.patch_statement(id=statement_id, text="An export runs weekly.")

    with pytest.raises(ValueError, match="cannot be approved"):
        server.review_draft(draft_id, "approve", _revision(draft_id))

    conn = server._drafts_db()
    with store.transaction(conn):
        drafts_store.set_decision(conn, draft_id, decision="rejected", by="reviewer")
    with pytest.raises(ValueError, match="cannot be reopened"):
        server.reopen_draft(draft_id, "Reconsider.")
    assert server.get_draft(draft_id)["status"] == "rejected"


def test_asking_a_person_files_a_gap_and_keeps_the_draft_submitted():
    draft_id = _draft()

    server.review_draft(
        draft_id,
        "needs_context",
        _revision(draft_id),
        question="Is the export limited to paid plans?",
    )

    draft = server.get_draft(draft_id)
    assert draft["status"] == "submitted"
    assert draft["decisions"][0]["action"] == "needs_context"
    [gap] = store.list_knowledge_gaps(store.substrate_connection())
    assert gap["draft_id"] == draft_id
    assert "Is the export limited to paid plans?" in gap["text"]


def test_list_drafts_finds_the_drafts_the_reviewer_rejected():
    rejected, held = _draft(), _draft()
    conn = server._drafts_db()
    for draft_id, label, application in (
        (rejected, "reject", "rejected"),
        (held, "changes_suggested", "held"),
    ):
        run = draft_review_store.new(draft_id, "review-and-apply", 1)
        run.status, run.label, run.application = "completed", label, application
        with store.transaction(conn):
            draft_review_store.save(conn, run)
    with store.transaction(conn):
        drafts_store.set_decision(conn, rejected, decision="rejected", by="reviewer")

    by_reviewer = server.list_drafts(status="rejected", application="rejected")
    held_queue = server.list_drafts(status="submitted", label="changes_suggested")

    assert [d["id"] for d in by_reviewer] == [rejected]
    assert [d["id"] for d in held_queue] == [held]
    assert held_queue[0]["review_assessment"]["application"] == "held"


def test_a_person_rejects_and_reopens_in_the_web_app():
    from starlette.requests import Request

    from mycelium.http import drafts as routes

    person = auth.Principal(id="curator-1", name="C", role="writer", type="human")
    request = Request({"type": "http"})
    request.state.principal = person
    draft_id = _draft()

    routes.reject_draft(draft_id, request)
    routes.reopen_draft(draft_id, routes.DraftReopenBody(reason="Wrong call."), request)

    decisions = routes.get_draft_detail(draft_id, request)["draft"]["decisions"]
    assert [(d["action"], d["decided_by"]) for d in decisions] == [
        ("rejected", "curator-1"),
        ("reopened", "curator-1"),
    ]
