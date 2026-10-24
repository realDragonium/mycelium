"""Statements no document of a profile cites: listed and dismissed per
profile, placed by the planner in existing or new documents, and planned for
by the server itself under a profile's planning policy."""

from __future__ import annotations

import json

import pytest

from mycelium import (
    ai,
    doc_plans,
    doc_runs,
    docs_store,
    document_maintenance,
    documentation_planning,
    product_settings,
    store,
)
from mycelium.documentation_planning import Proposal, ProposedItem
from product_settings_helpers import set_product


@pytest.fixture
def client(tmp_path, monkeypatch):
    from test_prompt_texts import _app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    prompts: list[str] = []

    def runner(prompt, *, guideline_set, document_type):
        prompts.append(prompt)
        return {
            "outcome": "document_written",
            "slug": "written",
            "title": "Written",
            "body": "# Written\n",
            "statement_ids": [],
        }

    doc_runs.RUNNER = runner
    try:
        with _app(tmp_path, monkeypatch) as client:
            client.run_prompts = prompts
            yield client
    finally:
        documentation_planning.wait_all()
        doc_runs.wait_all()
        doc_runs.RUNNER = None


def _profile(**slots: str) -> None:
    from mycelium import guidelines, prompt_store

    for slot, text in {"guidance": "Plain words.", "how-to": "Steps.", **slots}.items():
        prompt_store.save(
            prompt_store.connection(),
            type=guidelines.TYPE,
            name=f"public/{slot}",
            text=text,
        )


def _statements(*texts: str) -> list[str]:
    from mycelium import server

    with store.transaction(server._db()):
        return [
            store.create_statement(server._db(), "capability", text) for text in texts
        ]


def _document(cites: list[str]) -> str:
    from mycelium import server

    return docs_store.upsert_document(
        server._drafts_db(),
        slug="sign-in",
        title="Sign in",
        body="# Sign in\n\nHow members sign in to a workspace.\n",
        guideline_set="public",
        document_type="how-to",
        statement_ids=cites,
    )


def _answer(monkeypatch, *items: dict[str, object]) -> list[str]:
    prompts: list[str] = []

    def call(task, config):
        prompts.append(task.prompt)
        proposal = Proposal(items=[ProposedItem.model_validate(i) for i in items])
        return proposal, ai.Usage(input_tokens=10, output_tokens=5)

    monkeypatch.setattr(documentation_planning, "_call", call)
    return prompts


def _item(**values: object) -> dict[str, object]:
    return {
        "action": "create",
        "title": "Invoices",
        "document_type": "how-to",
        "rationale": "Admins handle invoices.",
        "priority": "high",
        **values,
    }


def test_uncovered_statements_are_listed_dismissed_and_placed(client, monkeypatch):
    _profile()
    sign_in, sso, invoices, internal = _statements(
        "members sign in with email",
        "members can sign in with sso",
        "admins can export invoices",
        "the export worker runs nightly",
    )
    document = _document([sign_in])

    plan = client.get("/api/documentation/plans/public").json()
    assert plan["uncovered_statements"] == 3
    assert {row["id"] for row in plan["uncovered"]} == {sso, invoices, internal}

    dismissed = client.post(
        f"/api/documentation/plans/public/uncovered/{internal}/dismiss"
    )
    assert dismissed.status_code == 200, dismissed.text
    plan = client.get("/api/documentation/plans/public").json()
    assert (plan["uncovered_statements"], plan["dismissed_statements"]) == (2, 1)
    assert plan["dismissed"] == 0
    health = client.get("/api/knowledge-health").json()
    assert health["uncovered_by_profile"]["public"] == 2

    prompts = _answer(
        monkeypatch,
        _item(
            action="update",
            title="Sign in",
            document_id=document,
            statement_ids=[sso],
        ),
        _item(statement_ids=[invoices]),
    )
    assert client.post("/api/documentation/plans/public").status_code == 200
    documentation_planning.wait_all()

    sent = json.loads(prompts[0])
    assert {row["id"] for row in sent["uncovered_statements"]} == {sso, invoices}
    assert sent["existing_documents"][0]["summary"] == (
        "How members sign in to a workspace."
    )
    plan = client.get("/api/documentation/plans/public").json()
    update, create = plan["items"]
    approved = client.post(
        "/api/documentation/plan-items/approve",
        json={"item_ids": [update["id"], create["id"]]},
    ).json()
    assert [entry["error"] for entry in approved] == [None, None]
    doc_runs.wait_all()
    brief = approved[0]["run"]["prompt"]
    assert brief.startswith("Add to this document: Sign in")
    assert f"- {sso}: 'members can sign in with sso'" in brief
    assert sign_in not in brief
    assert approved[0]["run"]["target_document_id"] == document


def test_a_plan_offers_statements_no_plan_was_offered_first(client, monkeypatch):
    _profile()
    set_product(product_settings.DocumentationPlanningSettings(max_uncovered=1))
    statements = set(_statements("members sign in", "admins export invoices"))
    prompts = _answer(monkeypatch)

    offered = []
    for _ in range(2):
        assert client.post("/api/documentation/plans/public").status_code == 200
        documentation_planning.wait_all()
        [row] = json.loads(prompts[-1])["uncovered_statements"]
        offered.append(row["id"])

    assert set(offered) == statements


def _sweep() -> list[str]:
    started = document_maintenance.sweep()
    documentation_planning.wait_all()
    return started


def _plans() -> list[dict[str, object]]:
    from mycelium import server

    return [
        dict(row)
        for row in server._drafts_db().execute(
            "SELECT automatic, outcome FROM documentation_plans "
            "WHERE kind = 'model' ORDER BY created_at, rowid"
        )
    ]


def test_automatic_planning_proposes_waits_and_writes(client, monkeypatch):
    from mycelium import server

    _profile(planning="propose")
    set_product(
        product_settings.DocumentationPlanningSettings(
            replan_hint_statements=3, approve_batch=2
        )
    )
    first, second, third = _statements(
        "members sign in", "admins export invoices", "owners delete workspaces"
    )
    _statements("owners rename workspaces")
    _answer(
        monkeypatch,
        *(
            _item(title=title, statement_ids=[sid])
            for title, sid in (
                ("Sign in", first),
                ("Export", second),
                ("Delete", third),
            )
        ),
    )

    assert _sweep() == []
    assert _plans() == [{"automatic": 1, "outcome": "planned"}]
    items = client.get("/api/documentation/plans/public").json()["items"]
    assert [item["state"] for item in items] == ["proposed"] * 3
    _sweep()
    assert len(_plans()) == 1, "proposed items wait for a person"

    _profile(planning="write")
    started = _sweep()
    doc_runs.wait_all()

    assert len(started) == 2
    states = [
        item["state"]
        for item in client.get("/api/documentation/plans/public").json()["items"]
    ]
    assert states == ["approved", "approved", "proposed"]
    started = _sweep()
    doc_runs.wait_all()
    assert len(started) == 1
    # Every statement was offered to a plan, so nothing triggers another.
    assert _sweep() == [] and len(_plans()) == 1
    assert doc_plans.offered(server._drafts_db(), "public") >= {first, second, third}
