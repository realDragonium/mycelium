import json
from contextlib import contextmanager

import pytest

from mycelium import ai, auth, drafts_store, model_settings, prompt_store, server, store
from mycelium import alias_suggestions as aliases
from mycelium.ingest.draft import InProcessDraftEmitter
from test_reviewed_application import _app


@contextmanager
def vocabulary(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch) as client:
        token = auth.current_principal.set(auth.LOCAL_ADMIN)
        try:
            entity_id = server.upsert_entity(
                name="Single sign-on", description="Federated authentication"
            )["entity_id"]
            with store.transaction(server._db()):
                statement_id = store.create_statement(
                    server._db(),
                    "state",
                    "Single sign-on (SSO) is enabled for administrators",
                )
            yield client, entity_id, statement_id
        finally:
            auth.current_principal.reset(token)


def proposal(entity_id, statement_id=None):
    return aliases.Proposal(
        entity_id=entity_id,
        alias="SSO",
        quote="Single sign-on (SSO)",
        reason="The abbreviation is explicitly defined in parentheses.",
        ambiguity="",
        statement_id=statement_id,
    )


def queue(entity_id, statement_id, *, extra=False):
    source = store.get_statement(server._db(), statement_id)["text"]
    suggestion = aliases.prepare(
        server._db(), proposal(entity_id, statement_id), source
    )
    db = server._drafts_db()
    with store.transaction(db):
        draft_id = drafts_store.create_draft(
            db, created_by=auth.LOCAL_ADMIN.id, session_id=None, title="Aliases"
        )
        drafts_store.add_op(
            db,
            draft_id=draft_id,
            kind=aliases.KIND,
            payload=suggestion.model_dump(mode="json"),
            created_by=auth.LOCAL_ADMIN.id,
        )
        if extra:
            drafts_store.add_op(
                db,
                draft_id=draft_id,
                kind="upsert_entity",
                payload={"name": "Unrelated", "description": "Unrelated knowledge"},
                created_by=auth.LOCAL_ADMIN.id,
            )
        drafts_store.set_submitted(db, draft_id)
    return aliases.list_entries()[0]


def decide(entry, action="accept", **kwargs):
    return aliases.review(
        entry.draft_id,
        entry.operation_ref,
        aliases.ReviewRequest(
            action=action, expected_revision=entry.revision, **kwargs
        ),
        auth.LOCAL_ADMIN,
    )


def test_accept_only_alias_then_replay_never_recreates_removed_alias(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id, extra=True)
        with pytest.raises(ValueError, match="individually"):
            server.apply_draft(entry.draft_id)
        accepted = decide(entry)
        assert accepted.suggestion.status == "accepted"
        assert store.get_name_by_text(server._db(), "SSO")["entity_id"] == entity_id
        assert store.get_name_by_text(server._db(), "Unrelated") is None
        server.delete_name(store.get_name_by_text(server._db(), "SSO")["id"])
        result = server.apply_draft(entry.draft_id)
        assert result["applied"] == 1
        assert store.get_name_by_text(server._db(), "SSO") is None
        assert store.get_name_by_text(server._db(), "Unrelated") is not None


def test_stale_vocabulary_requires_explicit_refresh_and_source_drift_cannot_refresh(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        server.upsert_name(text="Sign-on service", entity_id=entity_id)
        with pytest.raises(aliases.Conflict, match="changed"):
            decide(entry)
        refreshed = decide(entry, "refresh")
        assert refreshed.revision > entry.revision
        with pytest.raises(drafts_store.StaleDraftRevisionError):
            decide(entry)
        with store.transaction(server._db()):
            store.update_statement_text(
                server._db(), statement_id, "The supporting definition was removed"
            )
        with pytest.raises(aliases.Conflict, match="supporting statement changed"):
            decide(refreshed, "refresh")
        rejected = decide(refreshed, "reject")
        assert (
            rejected.suggestion.evidence.text
            == "Single sign-on (SSO) is enabled for administrators"
        )
        assert [event.action for event in rejected.suggestion.history] == [
            "refreshed",
            "rejected",
        ]


def test_retarget_preserves_evidence_and_accepts_current_target(tmp_path, monkeypatch):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        other = server.upsert_entity(
            name="Organization sign-on", description="Organization authentication"
        )["entity_id"]
        entry = queue(entity_id, statement_id)
        retargeted = decide(entry, "retarget", entity_id=other)
        assert retargeted.suggestion.evidence == entry.suggestion.evidence
        assert retargeted.suggestion.history[0].action == "retargeted"
        decide(retargeted)
        assert store.get_name_by_text(server._db(), "SSO")["entity_id"] == other


def test_alias_evidence_cannot_be_fabricated(tmp_path, monkeypatch):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        with pytest.raises(ValueError, match="quote"):
            aliases.prepare(server._db(), proposal(entity_id), "Unrelated source")
        with pytest.raises(ValueError, match="alias must occur"):
            aliases.prepare(
                server._db(),
                proposal(entity_id).model_copy(update={"alias": "Imaginary"}),
                "Single sign-on (SSO)",
            )


def test_generic_revision_and_service_accounts_cannot_certify_suggestions(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        payload = entry.suggestion.model_copy(update={"status": "accepted"}).model_dump(
            mode="json"
        )
        with pytest.raises(ValueError, match="review screen"):
            server.revise_draft_operation(
                entry.draft_id, entry.operation_ref, payload, entry.revision
            )
        with pytest.raises(ValueError, match="review screen"):
            server.strike_draft_operation(
                entry.draft_id, entry.operation_ref, entry.revision
            )
        service = auth.Principal(
            id="reviewer", name="Reviewer", role="writer", type="service"
        )
        with pytest.raises(auth.RoleRequired, match="human"):
            aliases.review(
                entry.draft_id,
                entry.operation_ref,
                aliases.ReviewRequest(
                    action="accept", expected_revision=entry.revision
                ),
                service,
            )
        assert aliases.list_entries()[0].suggestion.status == "pending"


def test_acceptance_receipt_recovers_without_reapplying_after_draft_write_failure(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        # Simulate termination after the substrate transaction committed but before draft finalization.
        aliases._accept(
            entry.draft_id, entry.operation_ref, entry.suggestion, auth.LOCAL_ADMIN
        )
        server.delete_name(store.get_name_by_text(server._db(), "SSO")["id"])
        with pytest.raises(aliases.Conflict, match="committed"):
            decide(entry, "reject")
        accepted = decide(entry)
        assert accepted.suggestion.status == "accepted"
        assert store.get_name_by_text(server._db(), "SSO") is None
        assert accepted.suggestion.history[-1].actor_id == auth.LOCAL_ADMIN.id


def test_manual_scan_uses_independent_model_and_rejects_external_evidence(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (client, entity_id, statement_id):
        model_settings.save(
            "alias_discovery",
            model_settings.SaveSelection(
                revision=model_settings.get("alias_discovery").revision,
                provider="openai",
                openai_model="gpt-fixture",
                claude_model="claude-fixture",
                openai_reasoning_effort="high",
            ),
            auth.LOCAL_ADMIN,
        )
        prompt_store.save(
            prompt_store.connection(),
            type="doctrine",
            name="alias_discovery",
            text="Look for explicit equivalence.",
        )
        seen = []

        def fake_structured(task, config):
            seen.append((task, config))
            return aliases.Discovery(suggestions=[proposal(entity_id, statement_id)])

        monkeypatch.setattr(ai, "structured", fake_structured)
        response = client.post(
            "/api/alias-suggestions/scan", json={"statement_ids": [statement_id]}
        )
        assert response.status_code == 200, response.text
        entry = aliases.Entry.model_validate(response.json()["suggestions"][0])
        assert entry.suggestion.prompt.version == 1
        assert "Look for explicit equivalence." in seen[0][0].system
        assert (
            "Every suggestion requires an individual human decision"
            in seen[0][0].system
        )
        assert entry.suggestion.status == "pending"
        assert entry.suggestion.model == "gpt-fixture"
        assert seen[0][1].provider == "openai"
        assert seen[0][1].reasoning_effort == "high"
        assert json.loads(seen[0][0].prompt)["statements"][statement_id]
        assert store.get_name_by_text(server._db(), "SSO") is None
        response = client.post(
            f"/api/alias-suggestions/{entry.draft_id}/{entry.operation_ref}/review",
            json={"action": "reject", "expected_revision": entry.revision},
        )
        assert response.status_code == 200, response.text
        assert response.json()["suggestion"]["status"] == "rejected"
        monkeypatch.setattr(
            ai,
            "structured",
            lambda task, config: aliases.Discovery(
                suggestions=[proposal(entity_id, "stm_outside")]
            ),
        )
        response = client.post(
            "/api/alias-suggestions/scan", json={"statement_ids": [statement_id]}
        )
        assert response.status_code == 400
        assert "outside" in response.json()["detail"]


def test_ingest_emitter_queues_non_replaying_human_suggestion(tmp_path, monkeypatch):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, _):
        emitter = InProcessDraftEmitter(server)
        assert aliases.KIND in emitter.valid_kinds()
        draft_id = emitter.create(title="Ingest")
        emitter.add_op(
            draft_id,
            aliases.KIND,
            proposal(entity_id).model_dump(),
            source_text="Single sign-on (SSO) is required for administrators",
        )
        entry = aliases.list_entries()[0]
        assert entry.suggestion.status == "pending"
        assert entry.suggestion.evidence.quote == "Single sign-on (SSO)"
        assert (
            entry.suggestion.evidence.text
            == "Single sign-on (SSO) is required for administrators"
        )
        with pytest.raises(ValueError, match="individually"):
            server.apply_draft(draft_id)


@pytest.mark.parametrize(
    "quote,queued", [("Single sign-on (SSO)", True), ("Invented name (SSO)", False)]
)
def test_ingest_validates_alias_quote_against_actual_input(quote, queued):
    from mycelium.ingest.config import IngestConfig
    from mycelium.ingest.loop import run_ingest
    from mycelium.ingest.tools import EMIT_TOOL
    from test_ingest import (
        _DEFAULT_KINDS,
        FakeAnthropic,
        FakeEmitter,
        FakeSubstrate,
        _emit_input,
        _ledger_row,
        _message,
        _op,
        _reconcile_then_adjacency,
        _tool_use,
    )

    payload = (
        proposal("ent_existing")
        .model_copy(update={"quote": quote})
        .model_dump(exclude_none=True)
    )
    emission = _emit_input(
        ops=[_op("alias_suggestion", payload)],
        ledger=[
            _ledger_row(
                "Single sign-on (SSO)",
                "new",
                matched=["ent_existing"],
                considered=["stm_existing"],
                note="Explicit abbreviation",
            )
        ],
    )
    emitter = FakeEmitter(valid_kinds=_DEFAULT_KINDS | {"alias_suggestion"})
    result = run_ingest(
        "Single sign-on (SSO) is enabled",
        client=FakeAnthropic(
            _reconcile_then_adjacency() + [_message([_tool_use(EMIT_TOOL, emission)])]
        ),
        substrate=FakeSubstrate(),
        emitter=emitter,
        config=IngestConfig(thinking=False, trace_log_path=None),
    )
    assert bool(emitter.queued) is queued
    if not queued:
        assert any(
            "quote the input text" in message for message in result.trace["flagged"]
        )


def test_auto_review_remains_advisory_even_if_model_proposes_acceptance(
    tmp_path, monkeypatch
):
    from mycelium import draft_review_runs
    from mycelium.draft_review_store import Assessment
    from settings_helpers import save_model, set_review_controls

    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        with store.transaction(server._auth_db()):
            reviewer_id = auth.create_user(
                server._auth_db(), name="Alias reviewer", role="writer", type="service"
            )
        set_review_controls(
            mode="review-and-apply", application_enabled=True, reviewer_id=reviewer_id
        )
        save_model("draft_review", provider="openai", openai_model="fixture")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture")
        monkeypatch.setattr(
            draft_review_runs,
            "RUNNER",
            lambda context: Assessment(
                label="good",
                rationale="The abbreviation is supported.",
                corrections=[],
                questions=[],
            ),
        )
        entry = queue(entity_id, statement_id, extra=True)
        server.request_draft_review(entry.draft_id)
        draft_review_runs.wait_all()
        reviewed = server.get_draft(entry.draft_id)
        assert reviewed["status"] == "submitted"
        assert reviewed["review_assessment"]["application"] == "unapplied"
        assert "human review" in reviewed["review_assessment"]["detail"]
        assert aliases.list_entries()[0].suggestion.status == "pending"
        assert store.get_name_by_text(server._db(), "SSO") is None
        assert store.get_name_by_text(server._db(), "Unrelated") is None


def test_accepting_an_unrelated_concept_alias_does_not_stale_other_suggestions(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        other = server.upsert_entity(
            name="Continuous integration", description="Build validation"
        )["entity_id"]
        with store.transaction(server._db()):
            second_statement = store.create_statement(
                server._db(), "state", "Continuous integration (CI) runs after a commit"
            )
        first = queue(entity_id, statement_id)
        other_proposal = aliases.Proposal(
            entity_id=other,
            alias="CI",
            quote="Continuous integration (CI)",
            reason="Explicit abbreviation",
            ambiguity="",
            statement_id=second_statement,
        )
        suggestion = aliases.prepare(
            server._db(),
            other_proposal,
            store.get_statement(server._db(), second_statement)["text"],
        )
        with store.transaction(server._drafts_db()):
            other_draft = drafts_store.create_draft(
                server._drafts_db(),
                created_by=auth.LOCAL_ADMIN.id,
                session_id=None,
                title="Independent alias",
            )
            drafts_store.add_op(
                server._drafts_db(),
                draft_id=other_draft,
                kind=aliases.KIND,
                payload=suggestion.model_dump(mode="json"),
                created_by=auth.LOCAL_ADMIN.id,
            )
        other_entry = next(
            entry for entry in aliases.list_entries() if entry.draft_id == other_draft
        )
        decide(first)
        current = next(
            entry for entry in aliases.list_entries() if entry.draft_id == other_draft
        )
        assert current.stale is False
        decide(other_entry)
        assert store.get_name_by_text(server._db(), "CI")["entity_id"] == other


@pytest.mark.parametrize("action", ["reject", "withdraw"])
def test_whole_draft_decisions_cannot_strand_pending_acceptance_receipts(
    tmp_path, monkeypatch, action
):
    with vocabulary(tmp_path, monkeypatch) as (client, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        aliases._accept(
            entry.draft_id, entry.operation_ref, entry.suggestion, auth.LOCAL_ADMIN
        )
        response = client.post(f"/api/drafts/{entry.draft_id}/{action}")
        assert response.status_code == 400, response.text
        assert "individually" in response.json()["detail"]
        refreshed = aliases.list_entries()[0]
        assert refreshed.acceptance_committed
        assert decide(refreshed).suggestion.status == "accepted"


def test_review_record_cannot_close_pending_aliases(tmp_path, monkeypatch):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        inspection = server.inspect_draft_review(entry.draft_id)
        with pytest.raises(ValueError, match="individually"):
            server.record_draft_review(
                entry.draft_id,
                "rejected",
                "Reject proposal",
                inspection["draft_revision"],
                inspection["knowledge_preconditions"],
            )
        assert drafts_store.list_reviews(server._drafts_db(), entry.draft_id) == []
        assert server.get_draft(entry.draft_id)["status"] == "submitted"


def test_conflicting_ownership_is_reported_before_preparation_and_review(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (client, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        other = server.upsert_entity(
            name="Other concept", description="A different meaning"
        )["entity_id"]
        server.upsert_name(text="sso", entity_id=other)
        source = store.get_statement(server._db(), statement_id)["text"]
        with pytest.raises(aliases.Conflict, match="already belongs"):
            aliases.prepare(server._db(), proposal(entity_id, statement_id), source)
        for action in ("accept", "refresh", "retarget"):
            response = client.post(
                f"/api/alias-suggestions/{entry.draft_id}/{entry.operation_ref}/review",
                json={
                    "action": action,
                    "expected_revision": entry.revision,
                    **({"entity_id": entity_id} if action == "retarget" else {}),
                },
            )
            assert response.status_code == 409, response.text
            assert other in response.json()["detail"]
        assert store.get_name_by_text(server._db(), "SSO")["entity_id"] == other
        assert aliases.list_entries()[0].revision == entry.revision
        assert (
            server._db()
            .execute(
                "SELECT 1 FROM reviewed_draft_applications WHERE application_id = ?",
                ("alias:" + entry.operation_ref,),
            )
            .fetchone()
            is None
        )
        retargeted = decide(entry, "retarget", entity_id=other)
        accepted = decide(retargeted)
        assert accepted.suggestion.status == "accepted"
        assert store.get_name_by_text(server._db(), "SSO")["entity_id"] == other


def test_accepting_an_alias_already_added_to_the_same_concept_is_idempotent(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        name_id = server.upsert_name(text="SSO", entity_id=entity_id)["name_id"]
        refreshed = decide(entry, "refresh")
        accepted = decide(refreshed)
        assert accepted.suggestion.status == "accepted"
        assert store.get_name_by_text(server._db(), "SSO")["id"] == name_id


def test_receipt_recovery_preserves_the_original_decision_after_alias_moves(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        other = server.upsert_entity(
            name="Other concept", description="A different meaning"
        )["entity_id"]
        entry = queue(entity_id, statement_id)
        decision = aliases._accept(
            entry.draft_id, entry.operation_ref, entry.suggestion, auth.LOCAL_ADMIN
        )
        name_id = store.get_name_by_text(server._db(), "SSO")["id"]
        server.move_name(name_id=name_id, to_entity_id=other)
        recovered = decide(entry)
        assert recovered.suggestion.history[-1] == decision
        assert store.get_name_by_text(server._db(), "SSO")["entity_id"] == other


def test_scan_preserves_valid_proposals_and_reports_individual_rejections(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (client, entity_id, statement_id):
        server.upsert_name(text="SSO", entity_id=entity_id)
        other = server.upsert_entity(
            name="Continuous integration", description="Build validation"
        )["entity_id"]
        with store.transaction(server._db()):
            second_id = store.create_statement(
                server._db(),
                "state",
                "Continuous integration (CI) validates every commit",
            )
        valid = aliases.Proposal(
            entity_id=other,
            alias="CI",
            quote="Continuous integration (CI)",
            reason="Explicit abbreviation",
            ambiguity="",
            statement_id=second_id,
        )
        monkeypatch.setattr(
            ai,
            "structured",
            lambda task, config: aliases.Discovery(
                suggestions=[
                    proposal(entity_id, statement_id),
                    proposal(other, statement_id),
                    valid.model_copy(update={"quote": "Invented (CI)"}),
                    valid,
                ]
            ),
        )
        response = client.post(
            "/api/alias-suggestions/scan",
            json={"statement_ids": [statement_id, second_id]},
        )
        assert response.status_code == 200, response.text
        result = aliases.ScanResult.model_validate(response.json())
        assert [entry.suggestion.proposal.alias for entry in result.suggestions] == [
            "CI"
        ]
        assert len(result.skipped) == 3
        assert "already an alias" in result.skipped[0].reason
        assert "already belongs" in result.skipped[1].reason
        assert "quote" in result.skipped[2].reason
        assert result.skipped[1].proposal.entity_id == other
        assert store.get_name_by_text(server._db(), "CI") is None
        assert (
            len(
                drafts_store.list_ops(
                    server._drafts_db(), result.suggestions[0].draft_id
                )
            )
            == 1
        )


def test_scan_skips_changed_source_without_losing_other_proposals(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        with store.transaction(server._db()):
            second_id = store.create_statement(
                server._db(), "state", "Single sign-on (SSO) is required"
            )

        def respond(task, config):
            with store.transaction(server._db()):
                store.update_statement_text(
                    server._db(), statement_id, "The old abbreviation is removed"
                )
            return aliases.Discovery(
                suggestions=[
                    proposal(entity_id, statement_id),
                    proposal(entity_id, second_id),
                ]
            )

        monkeypatch.setattr(ai, "structured", respond)
        result = aliases.scan(
            aliases.ScanRequest(statement_ids=[statement_id, second_id]),
            auth.LOCAL_ADMIN,
        )
        assert len(result.suggestions) == len(result.skipped) == 1
        assert result.suggestions[0].suggestion.evidence.statement_id == second_id
        assert "supporting statement changed" in result.skipped[0].reason


def test_all_skipped_scan_returns_reasons_without_creating_an_empty_draft(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (client, entity_id, statement_id):
        server.upsert_name(text="SSO", entity_id=entity_id)
        monkeypatch.setattr(
            ai,
            "structured",
            lambda task, config: aliases.Discovery(
                suggestions=[proposal(entity_id, statement_id)]
            ),
        )
        response = client.post(
            "/api/alias-suggestions/scan", json={"statement_ids": [statement_id]}
        )
        assert response.status_code == 200, response.text
        result = aliases.ScanResult.model_validate(response.json())
        assert result.suggestions == []
        assert len(result.skipped) == 1
        assert drafts_store.list_drafts(server._drafts_db(), status="all") == []


def test_unknown_scan_evidence_aborts_before_any_valid_proposal_is_saved(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        monkeypatch.setattr(
            ai,
            "structured",
            lambda task, config: aliases.Discovery(
                suggestions=[
                    proposal(entity_id, statement_id),
                    proposal(entity_id, "stm_outside"),
                ]
            ),
        )
        with pytest.raises(ValueError, match="outside"):
            aliases.scan(
                aliases.ScanRequest(statement_ids=[statement_id]), auth.LOCAL_ADMIN
            )
        assert drafts_store.list_drafts(server._drafts_db(), status="all") == []


def test_pending_filter_does_not_query_statement_examples_for_resolved_aliases(
    tmp_path, monkeypatch
):
    with vocabulary(tmp_path, monkeypatch) as (_, entity_id, statement_id):
        entry = queue(entity_id, statement_id)
        decide(entry, "reject")
        queries = []
        server._db().set_trace_callback(queries.append)
        try:
            assert aliases.list_entries("pending") == []
            assert not any("FROM statements" in query for query in queries)
            assert len(aliases.list_entries("rejected")) == 1
            assert any("FROM statements" in query for query in queries)
        finally:
            server._db().set_trace_callback(None)
