import sqlite3

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, drafts_store, server, store


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    server._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


def _principal(role="writer"):
    principal = auth.Principal(id=f"{role}-1", name=role, role=role, type="human")
    return auth.current_principal.set(principal)


def _submitted_entity_draft():
    token = _principal("drafter")
    session = auth.current_session_id.set("review-test")
    try:
        queued = server.upsert_entity(name="Reviewed", description="ready")
        server.submit_draft(queued["draft_id"])
        return queued["draft_id"]
    finally:
        auth.current_session_id.reset(session)
        auth.current_principal.reset(token)


def _accepted_review(draft_id):
    evidence = server.inspect_draft_review(draft_id)
    return server.record_draft_review(
        draft_id=draft_id,
        outcome="accepted",
        rationale="The operation matches the merged change.",
        draft_revision=evidence["draft_revision"],
        knowledge_preconditions=evidence["knowledge_preconditions"],
    )


def test_review_contract_refines_records_and_applies_when_enabled(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
            op = evidence["draft"]["ops"][0]
            revised = server.revise_draft_operation(
                draft_id,
                op["operation_ref"],
                {"name": "Reviewed", "description": "refined"},
                expected_revision=evidence["draft_revision"],
            )
            evidence = server.inspect_draft_review(draft_id)
            assert evidence["draft_revision"] == revised["revision"]
            review = server.record_draft_review(
                draft_id,
                "refined",
                "Corrected the description.",
                evidence["draft_revision"],
                evidence["knowledge_preconditions"],
            )
            result = server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)

        assert result["applied"] == 1
        assert server.get_draft(draft_id)["status"] == "approved"
        assert server.list_entities()["entities"][0]["description"] == "refined"


def test_reviewed_apply_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MYCELIUM_REVIEWED_APPLY", raising=False)
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            review = _accepted_review(draft_id)
            with pytest.raises(ValueError, match="disabled"):
                server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)


def test_review_rejects_stale_draft_and_unresolved_flag(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
            op = evidence["draft"]["ops"][0]
            server.revise_draft_operation(
                draft_id,
                op["operation_ref"],
                {"name": "Reviewed", "description": "new"},
            )
            with pytest.raises(drafts_store.StaleDraftRevisionError):
                server.record_draft_review(
                    draft_id,
                    "accepted",
                    "stale",
                    evidence["draft_revision"],
                    evidence["knowledge_preconditions"],
                )

            conn = server._drafts_db()
            with store.transaction(conn):
                drafts_store.add_op(
                    conn,
                    draft_id=draft_id,
                    kind="flag",
                    payload={"reason": "missing context"},
                    created_by="drafter-1",
                )
            evidence = server.inspect_draft_review(draft_id)
            assert evidence["operation_findings"][0]["finding"] == "unresolved_flag"
            with pytest.raises(ValueError, match="unresolved"):
                server.record_draft_review(
                    draft_id,
                    "accepted",
                    "cannot accept",
                    evidence["draft_revision"],
                    evidence["knowledge_preconditions"],
                )
        finally:
            auth.current_principal.reset(token)


def test_inspection_refuses_obsolete_operations_and_correction_is_versioned(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
            added = server.append_draft_correction(
                draft_id,
                "upsert_entity",
                {"name": "Omitted", "description": "added during review"},
                expected_revision=evidence["draft_revision"],
            )
            assert added["operation_ref"].startswith("op_")
            assert added["revision"] == evidence["draft_revision"] + 1

            conn = server._drafts_db()
            with store.transaction(conn):
                drafts_store.add_op(
                    conn,
                    draft_id=draft_id,
                    kind="retired_mutation",
                    payload={},
                    created_by="legacy",
                )
            evidence = server.inspect_draft_review(draft_id)
            assert evidence["operation_findings"][-1]["finding"] == "obsolete_tool"
            with pytest.raises(ValueError, match="unresolved"):
                server.record_draft_review(
                    draft_id,
                    "accepted",
                    "obsolete operations cannot pass",
                    evidence["draft_revision"],
                    evidence["knowledge_preconditions"],
                )
        finally:
            auth.current_principal.reset(token)


def test_apply_rechecks_affected_knowledge_and_real_tool_role(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    with _app(tmp_path, monkeypatch):
        entity_id = server.upsert_entity("Existing", "before")["entity_id"]
        token = _principal("drafter")
        session = auth.current_session_id.set("delete-test")
        try:
            queued = server.delete_entity(id=entity_id)
            server.submit_draft(queued["draft_id"])
        finally:
            auth.current_session_id.reset(session)
            auth.current_principal.reset(token)

        writer = _principal("writer")
        try:
            review = _accepted_review(queued["draft_id"])
            with store.transaction(store.substrate_connection()):
                store.update_entity_description(
                    store.substrate_connection(), entity_id, "changed"
                )
            with pytest.raises(ValueError, match="knowledge changed"):
                server.apply_reviewed_draft(queued["draft_id"], review["review_id"])

            evidence = server.inspect_draft_review(queued["draft_id"])
            review = server.record_draft_review(
                queued["draft_id"],
                "accepted",
                "delete is intended",
                evidence["draft_revision"],
                evidence["knowledge_preconditions"],
            )
            with pytest.raises(RuntimeError, match="requires the admin role"):
                server.apply_reviewed_draft(queued["draft_id"], review["review_id"])
            failure = (
                server._drafts_db()
                .execute(
                    "SELECT status, failure FROM draft_applications "
                    "WHERE draft_id = ? ORDER BY claimed_at DESC LIMIT 1",
                    (queued["draft_id"],),
                )
                .fetchone()
            )
            assert failure["status"] == "failed"
            assert "requires the admin role" in failure["failure"]
        finally:
            auth.current_principal.reset(writer)


def test_commit_before_finalization_recovers_without_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        review = _accepted_review(draft_id)
        original = drafts_store.set_decision
        calls = 0

        def fail_once(conn, target, *, decision, by):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("finalization failed")
            return original(conn, target, decision=decision, by=by)

        monkeypatch.setattr(drafts_store, "set_decision", fail_once)
        try:
            with pytest.raises(sqlite3.OperationalError, match="finalization"):
                server.apply_reviewed_draft(draft_id, review["review_id"])
            recovered = server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)

        assert recovered["recovered"] is True
        assert recovered["applied"] == 1
        assert server.list_entities()["total"] == 1


def test_active_claim_blocks_manual_apply_and_edits(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            review = _accepted_review(draft_id)
            with store.transaction(server._drafts_db()):
                drafts_store.claim_application(
                    server._drafts_db(),
                    draft_id=draft_id,
                    review_id=review["review_id"],
                    claimed_by="writer-1",
                )
            with pytest.raises(drafts_store.ActiveApplicationError):
                server.apply_draft(draft_id)
            op = server.get_draft(draft_id)["ops"][0]
            with pytest.raises(drafts_store.ActiveApplicationError):
                server.strike_draft_operation(draft_id, op["operation_ref"])
        finally:
            auth.current_principal.reset(token)
