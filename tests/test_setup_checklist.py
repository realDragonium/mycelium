"""The admin's setup checklist and the warning for blocked background work."""

from __future__ import annotations

import pytest

from mycelium import (
    audiences,
    auth,
    model_settings,
    product_settings,
    quarantine,
    server,
    setup_checklist,
    store,
)
from product_settings_helpers import set_product
from settings_helpers import save_model, set_review_controls
from test_reviewed_application import _app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "mycelium.model_settings.claude_configuration_error",
        lambda: "Configure Anthropic credentials on the server.",
    )
    with _app(tmp_path, monkeypatch) as client:
        yield client


def _steps(client) -> dict[str, dict]:
    return {step["id"]: step for step in client.get("/api/setup").json()["steps"]}


def test_a_fresh_instance_lists_what_is_left(client):
    steps = _steps(client)
    assert {key: step["status"] for key, step in steps.items()} == {
        "credentials": "todo",
        "models": "todo",
        "audiences": "todo",
        "profile": "todo",
        "github": "todo",
        "review": "todo",
        "budget": "todo",
    }
    assert "used by Ask" in steps["credentials"]["detail"]
    assert steps["models"]["detail"].startswith("Choose a model for Ask, Ingestion")
    assert (steps["github"]["optional"], steps["github"]["section"]) == (
        True,
        "documentation",
    )


def test_steps_complete_from_saved_settings(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setattr(
        "mycelium.model_settings.claude_configuration_error", lambda: None
    )
    with store.transaction(server._db()):
        statement = store.create_statement(server._db(), "state", "exports are csv")
        store.audience_labels.set_label(
            server._db(),
            statement,
            ["internal-technical"],
            source="curator",
            reason="r",
        )
    audiences.save(
        "external-technical",
        audiences.SaveAudience(
            name="Integrators", scope="external", description="API users.", revision=1
        ),
        auth.LOCAL_ADMIN,
    )
    from test_document_maintenance import _profile

    _profile(None, "external-technical")
    set_review_controls(mode="off")
    set_product(product_settings.AIBudgetSettings(monthly_limit_tokens=5_000_000))
    for action in model_settings.ACTIONS:
        if action != "draft_review":
            save_model(action, claude_model="claude-sonnet-5-5")

    steps = _steps(client)
    assert {key for key, step in steps.items() if step["status"] == "todo"} == {
        "github"
    }
    assert steps["review"]["detail"] == "Draft review: Off."


def test_dismissed_steps_count_as_settled(client):
    for step in ("credentials", "models", "audiences", "profile", "github", "review"):
        assert (
            client.put(f"/api/setup/steps/{step}", json={"dismissed": True}).status_code
            == 200
        )
    view = client.put("/api/setup/steps/budget", json={"dismissed": True}).json()
    assert view["complete"] is True
    assert {step["status"] for step in view["steps"]} == {"dismissed"}

    view = client.put("/api/setup/steps/budget", json={"dismissed": False}).json()
    assert view["complete"] is False


def test_background_work_without_credentials_is_reported_once_per_worker(client):
    save_model("draft_review", provider="openai", openai_model="gpt-5.4")
    set_review_controls(mode="review-only")

    blocked = client.get("/api/setup").json()["blocked"]
    assert [item["worker"] for item in blocked] == [
        "Draft review",
        "Audience labelling",
    ]
    assert "OPENAI_API_KEY" in blocked[0]["reason"]


def test_only_admins_see_the_checklist(client):
    conn = server.runtime._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name="w", role="writer", type="service")
        raw, _ = auth.issue_token(conn, user_id=user, name="t", scope="writer")
    response = client.get("/api/setup", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 403


def test_quarantine_does_not_count_a_destination_as_publishing(monkeypatch):
    destination = product_settings.DestinationSettings(
        name="docs",
        path_template="docs/{slug}.md",
        owner="example",
        repo="handbook",
        base_branch="main",
        binding="github",
    )
    monkeypatch.setattr(
        product_settings,
        "get",
        lambda model, conn=None: product_settings.DocumentationSettings(
            destinations=(destination,)
        ),
    )
    assert setup_checklist._github(None)[0] == "done"

    monkeypatch.setenv(quarantine.ENV, "1")
    assert setup_checklist._github(None) == (
        "todo",
        "Quarantine refuses GitHub delivery, so docs gets nothing.",
    )
