"""Model-produced drafts reach the internal reviewer without a person."""

import dataclasses

import pytest

from mycelium import (
    alias_suggestions,
    auth,
    draft_review_runs,
    ingest,
    research_runs,
    server,
    store,
)
from mycelium.ingest import loop as ingest_loop
from mycelium.ingest.draft import InProcessDraftEmitter
from mycelium.ingest.tools import EMIT_TOOL
from settings_helpers import save_model, set_review_controls
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
from test_internal_draft_review import _assessment
from test_reviewed_application import _app

TEXT = "Single sign-on (SSO) is required in the Admin console."


@pytest.fixture
def curated_app(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_review_runs, "RUNNER", lambda context: _assessment())
    with _app(tmp_path, monkeypatch) as client:
        with store.transaction(server._auth_db()):
            reviewer = auth.create_user(
                server._auth_db(), name="Reviewer", role="writer", type="service"
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
                config, provider="claude", thinking=False, trace_log_path=None
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


def test_research_draft_is_applied_without_a_person(curated_app, tmp_path):
    _automatic()

    def runner(topic, *, source=None):
        emitter = InProcessDraftEmitter(server)
        draft_id = emitter.create(title=f"research: {topic}")
        emitter.add_op(
            draft_id,
            "upsert_entity",
            {"name": "Audit log", "description": "Records administrator actions"},
        )
        return {"outcome": "draft_created", "draft_id": draft_id}

    run_id = research_runs.start_run(
        topic="audit logging",
        source="fixture",
        created_by=None,
        data_dir=tmp_path,
        conn=server._drafts_db(),
        runner=runner,
    )
    research_runs.wait_all()
    draft_review_runs.wait_all()

    from mycelium import research_store

    run = research_store.get_run(server._drafts_db(), run_id)
    assert run is not None and run["outcome"] == "draft_created"
    assert server.get_draft(run["draft_id"])["status"] == "approved"
    assert "Audit log" in _entity_names()
