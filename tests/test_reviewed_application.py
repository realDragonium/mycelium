import json
import sqlite3
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, drafts_store, server, store


@contextmanager
def _app(tmp_path, monkeypatch, *, application_enabled=False):
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

    with TestClient(app) as client:
        from settings_helpers import set_review_controls

        if application_enabled:
            set_review_controls(application_enabled=True)
        yield client


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
    with _app(tmp_path, monkeypatch, application_enabled=True):
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
            inspection = server.inspect_draft_review(draft_id)
        finally:
            auth.current_principal.reset(token)

        assert result["applied"] == 1
        assert server.get_draft(draft_id)["status"] == "approved"
        assert server.list_entities()["entities"][0]["description"] == "refined"
        assert inspection["reviews"][0]["review_id"] == review["review_id"]
        assert (
            inspection["applications"][0]["application_id"] == result["application_id"]
        )


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


def test_rejected_review_finalizes_draft(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
            review = server.record_draft_review(
                draft_id,
                "rejected",
                "The proposal is not supported by the source.",
                evidence["draft_revision"],
                evidence["knowledge_preconditions"],
            )
        finally:
            auth.current_principal.reset(token)
        assert review["outcome"] == "rejected"
        assert server.get_draft(draft_id)["status"] == "rejected"


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


def test_inspection_tracks_name_owner_and_rejects_nested_batch_fields(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch):
        entity_id = server.upsert_entity("Named", "before")["entity_id"]
        name_id = store.get_names_by_entity(store.substrate_connection(), entity_id)[0][
            "id"
        ]
        conn = server._drafts_db()
        with store.transaction(conn):
            draft_id = drafts_store.create_draft(
                conn, created_by="drafter-1", session_id=None
            )
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="delete_name",
                payload={"name_id": name_id},
                created_by="drafter-1",
            )
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="upsert_statements",
                payload={
                    "statements": [
                        {"id": "stm_existing", "kind": "state", "text": "it exists"}
                    ]
                },
                created_by="drafter-1",
            )
            drafts_store.set_submitted(conn, draft_id)
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
        finally:
            auth.current_principal.reset(token)

        assert evidence["knowledge_preconditions"][0]["id"] == entity_id
        assert "statements[0].id" in evidence["operation_findings"][0]["finding"]


def test_inspection_rejects_dangling_operation_references(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        draft_id = _submitted_entity_draft()
        conn = server._drafts_db()
        with store.transaction(conn):
            producer_seq = drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="upsert_statements",
                payload={"statements": [{"kind": "state", "text": "one"}]},
                created_by="drafter-1",
            )
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="add_links",
                payload={
                    "links": [
                        {
                            "from_id": f"@{producer_seq}:99",
                            "to_id": "stm_target",
                            "link_type": "requires",
                        }
                    ]
                },
                created_by="drafter-1",
            )
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
        finally:
            auth.current_principal.reset(token)
        assert evidence["operation_findings"][-1]["finding"].startswith(
            "unresolved_operation_reference"
        )


def test_statement_text_captures_name_resolution_precondition(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        entity_id = server.upsert_entity("Mycelium", "system")["entity_id"]
        conn = server._drafts_db()
        with store.transaction(conn):
            draft_id = drafts_store.create_draft(
                conn, created_by="drafter-1", session_id=None
            )
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="upsert_statement",
                payload={
                    "kind": "state",
                    "text": "Mycelium is available",
                    "links": [],
                },
                created_by="drafter-1",
            )
            drafts_store.set_submitted(conn, draft_id)
        token = _principal()
        try:
            evidence = server.inspect_draft_review(draft_id)
        finally:
            auth.current_principal.reset(token)
        assert evidence["knowledge_preconditions"][0]["id"] == entity_id


def test_apply_rechecks_affected_knowledge_and_real_tool_role(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
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
                    "WHERE draft_id = ? ORDER BY rowid DESC LIMIT 1",
                    (queued["draft_id"],),
                )
                .fetchone()
            )
            assert failure["status"] == "failed"
            assert "requires the admin role" in failure["failure"]
        finally:
            auth.current_principal.reset(writer)


def test_commit_before_finalization_recovers_without_replay(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        draft_id = _submitted_entity_draft()
        token = _principal()
        review = _accepted_review(draft_id)
        original = drafts_store.set_decision
        calls = 0

        def fail_once(conn, target, *, decision, by, application_id=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("finalization failed")
            return original(
                conn,
                target,
                decision=decision,
                by=by,
                application_id=application_id,
            )

        monkeypatch.setattr(drafts_store, "set_decision", fail_once)
        try:
            with pytest.raises(sqlite3.OperationalError, match="finalization"):
                server.apply_reviewed_draft(draft_id, review["review_id"])
            recovered = server.apply_reviewed_draft(draft_id, review["review_id"])
            repeated = server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)

        assert recovered["recovered"] is True
        assert recovered["applied"] == 1
        assert server.list_entities()["total"] == 1
        assert repeated["application_id"] == recovered["application_id"]
        assert repeated["recovered"] is True
        attempt = (
            server._drafts_db()
            .execute(
                "SELECT failure FROM draft_applications WHERE id = ?",
                (recovered["application_id"],),
            )
            .fetchone()
        )
        assert "finalization failed" in attempt["failure"]


def test_interrupted_claim_with_stale_knowledge_is_failed(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        entity_id = server.upsert_entity("Changing", "before")["entity_id"]
        token = _principal("drafter")
        session = auth.current_session_id.set("stale-claim")
        try:
            queued = server.delete_entity(entity_id)
            server.submit_draft(queued["draft_id"])
        finally:
            auth.current_session_id.reset(session)
            auth.current_principal.reset(token)
        token = _principal("admin")
        try:
            review = _accepted_review(queued["draft_id"])
            with store.transaction(server._drafts_db()):
                application_id = drafts_store.claim_application(
                    server._drafts_db(),
                    draft_id=queued["draft_id"],
                    review_id=review["review_id"],
                    claimed_by="admin-1",
                )
            with store.transaction(store.substrate_connection()):
                store.update_entity_description(
                    store.substrate_connection(), entity_id, "changed"
                )
            with pytest.raises(ValueError, match="knowledge changed"):
                server.apply_reviewed_draft(queued["draft_id"], review["review_id"])
        finally:
            auth.current_principal.reset(token)
        attempt = (
            server._drafts_db()
            .execute(
                "SELECT status, failure FROM draft_applications WHERE id = ?",
                (application_id,),
            )
            .fetchone()
        )
        assert attempt["status"] == "failed"
        assert "knowledge changed" in attempt["failure"]


def test_soft_replay_rejection_rolls_back_and_records_failure(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        conn = server._drafts_db()
        draft_id = drafts_store.create_draft(
            conn, created_by="drafter-1", session_id=None
        )
        drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind="upsert_statement",
            payload={"kind": "state", "text": "A and B", "links": []},
            created_by="drafter-1",
        )
        drafts_store.set_submitted(conn, draft_id)
        token = _principal()
        monkeypatch.setattr(
            server,
            "_phrasing_gate",
            lambda *args: ([], {"rejected": True, "violations": ["test"]}),
        )
        try:
            review = _accepted_review(draft_id)
            with pytest.raises(RuntimeError, match="was rejected"):
                server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)
        assert (
            store.substrate_connection()
            .execute("SELECT COUNT(*) FROM statements")
            .fetchone()[0]
            == 0
        )
        attempt = conn.execute(
            "SELECT status, failure FROM draft_applications WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        assert attempt["status"] == "failed"
        assert "was rejected" in attempt["failure"]


def test_failure_before_substrate_commit_is_durable(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        draft_id = _submitted_entity_draft()
        token = _principal()
        review = _accepted_review(draft_id)
        monkeypatch.setattr(
            server,
            "apply_draft",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                sqlite3.OperationalError("substrate commit failed")
            ),
        )
        try:
            with pytest.raises(sqlite3.OperationalError, match="commit failed"):
                server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)
        attempt = (
            server._drafts_db()
            .execute(
                "SELECT status, failure FROM draft_applications WHERE draft_id = ?",
                (draft_id,),
            )
            .fetchone()
        )
        assert attempt["status"] == "failed"
        assert attempt["failure"] == "substrate commit failed"
        assert server.get_draft(draft_id)["status"] == "submitted"


def test_exception_after_substrate_commit_recovers_same_attempt(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        draft_id = _submitted_entity_draft()
        token = _principal()
        review = _accepted_review(draft_id)
        calls = []

        def commit_then_interrupt(target, *, application_id, review_id, strict):
            calls.append(application_id)
            result = {"applied": 1, "skipped": 0, "results": []}
            with store.transaction(store.substrate_connection()):
                store.substrate_connection().execute(
                    "INSERT INTO reviewed_draft_applications "
                    "(application_id, draft_id, review_id, committed_at, result_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        application_id,
                        target,
                        review_id,
                        "2026-01-01T00:00:00Z",
                        json.dumps(result),
                    ),
                )
            raise KeyboardInterrupt("after commit")

        monkeypatch.setattr(server, "apply_draft", commit_then_interrupt)
        try:
            result = server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)
        assert result["recovered"] is True
        assert len(calls) == 1


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


def test_manual_approval_serializes_against_reviewed_apply(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, application_enabled=True):
        draft_id = _submitted_entity_draft()
        token = _principal()
        try:
            review = _accepted_review(draft_id)
        finally:
            auth.current_principal.reset(token)

        entered = threading.Event()
        release = threading.Event()
        reviewed_started = threading.Event()
        reviewed_finished = threading.Event()
        outcomes = []
        failures: list[BaseException] = []

        def blocking_manual_apply(target):
            entered.set()
            assert release.wait(2)
            return {"applied": 1, "skipped": 0, "results": []}

        monkeypatch.setattr(server, "apply_draft", blocking_manual_apply)

        class Request:
            class state:
                principal = auth.Principal(
                    id="writer-manual",
                    name="manual",
                    role="writer",
                    type="human",
                )

        def manual():
            from mycelium.http import approve_draft

            try:
                outcomes.append(approve_draft(draft_id, Request()))
            except BaseException as exc:
                failures.append(exc)

        def reviewed():
            principal = _principal()
            reviewed_started.set()
            try:
                with pytest.raises(ValueError, match="only submitted"):
                    server.apply_reviewed_draft(draft_id, review["review_id"])
            except BaseException as exc:
                failures.append(exc)
            finally:
                auth.current_principal.reset(principal)
                reviewed_finished.set()

        manual_thread = threading.Thread(target=manual)
        reviewed_thread = threading.Thread(target=reviewed)
        manual_thread.start()
        assert entered.wait(2)
        reviewed_thread.start()
        assert reviewed_started.wait(2)
        assert not reviewed_finished.wait(0.05)
        release.set()
        manual_thread.join(2)
        reviewed_thread.join(2)
        assert not manual_thread.is_alive()
        assert not reviewed_thread.is_alive()
        assert reviewed_finished.is_set()
        assert not failures, failures
        assert outcomes[0]["ok"] is True
