"""Instruction edits reach the real builders and retain per-run versions."""

import json
import sqlite3

import pytest

import test_ask as ask_fixtures
import test_docgen as doc_fixtures
from mycelium import ai, ai_prompts, auth, draft_review_model, prompt_store
from mycelium import documentation_profiles as profiles
from mycelium.draft_review_store import Assessment
from test_prompt_texts import _app


@pytest.fixture
def db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    prompt_store.use_connection(conn)
    yield conn
    prompt_store.reset()
    conn.close()


def save(db: sqlite3.Connection, action: ai_prompts.Action, text: str) -> None:
    prompt_store.save(db, type="doctrine", name=action, text=text)


@pytest.mark.parametrize("action", ai_prompts.ACTIONS)
def test_versions_reset_restore_and_retirement_keep_editor_and_runtime_aligned(
    db, action
):
    original = ai_prompts.editor(action)
    save(db, action, "First behavior")
    captured = ai_prompts.resolve(action)
    save(db, action, "Second behavior")
    assert captured.text == "First behavior"
    assert captured.version == 1
    assert ai_prompts.resolve(action).version == 2
    assert "Second behavior" in ai_prompts.editor(action).preview
    with pytest.raises(profiles.Conflict):
        profiles.save_text(
            "doctrine", action, "Stale edit", auth.LOCAL_ADMIN, revision=1
        )
    profiles.restore_text(
        profiles.RestoreText(type="doctrine", name=action, version=1, revision=2),
        auth.LOCAL_ADMIN,
    )
    assert ai_prompts.resolve(action).text == "First behavior"
    profiles.save_text(
        "doctrine", action, original.default_text, auth.LOCAL_ADMIN, revision=3
    )
    assert ai_prompts.resolve(action).text == original.default_text
    prompt_store.delete(db, type="doctrine", name=action)
    assert ai_prompts.editor(action).current.version == 5
    assert ai_prompts.resolve(action).source != "saved"
    profiles.save_text(
        "doctrine", action, "After retirement", auth.LOCAL_ADMIN, revision=5
    )
    assert ai_prompts.resolve(action).version == 6


def test_editor_api_lists_all_actions_previews_unsaved_text_and_checks_roles(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch) as client:
        assert client.get("/api/ai-instructions").json()["names"] == list(
            ai_prompts.ACTIONS
        )
        for action in ai_prompts.ACTIONS:
            view = client.get(f"/api/ai-instructions/{action}")
            assert view.status_code == 200
            original = view.json()
            preview = client.post(
                f"/api/ai-instructions/{action}/preview",
                json={"text": "UNSAVED {literal} guidance"},
            )
            assert preview.status_code == 200
            assert "UNSAVED {literal} guidance" in preview.json()["preview"]
            assert client.get(f"/api/ai-instructions/{action}").json() == original
            result = client.put(
                "/api/documentation/prompts",
                json={
                    "type": "doctrine",
                    "name": action,
                    "text": "Saved behavior",
                    "revision": original["current"]["version"],
                },
            )
            assert result.status_code == 200
            assert (
                client.get(f"/api/ai-instructions/{action}").json()["current"]["text"]
                == "Saved behavior"
            )
        assert client.get("/api/ai-instructions/unknown").status_code == 422
        from mycelium import http

        reader = auth.Principal(id="reader", name="Reader", role="reader", type="human")
        monkeypatch.setattr(http, "_require_principal", lambda request: reader)
        assert client.get("/api/ai-instructions").json()["can_write"] is False
        assert (
            client.put(
                "/api/documentation/prompts",
                json={
                    "type": "doctrine",
                    "name": "ask",
                    "text": "Denied",
                    "revision": 1,
                },
            ).status_code
            == 403
        )


def test_ask_keeps_one_snapshot_across_turns_and_next_run_uses_edit(db, monkeypatch):
    save(db, "ask", "FIRST ASK INSTRUCTIONS")
    create = ask_fixtures.FakeAnthropic.create

    def changing_create(self, **kwargs):
        save(db, "ask", "LATER ASK INSTRUCTIONS")
        return create(self, **kwargs)

    monkeypatch.setattr(ask_fixtures.FakeAnthropic, "create", changing_create)
    responses = [
        ask_fixtures._message(
            [ask_fixtures._tool_use("search_statements", {"query": "retry"})]
        ),
        ask_fixtures._message(
            [
                ask_fixtures._tool_use(
                    "survey_statements", {"query": "retry", "adjacency_sources": ["s1"]}
                )
            ]
        ),
        ask_fixtures._message(
            [ask_fixtures._tool_use("submit_answer", ask_fixtures._submit_input())]
        ),
    ]
    result, client, _ = ask_fixtures._run(responses)
    assert len(client.calls) >= 3
    for request in client.calls:
        system = json.dumps(request["system"])
        assert "FIRST ASK INSTRUCTIONS" in system
        assert "LATER ASK INSTRUCTIONS" not in system
        assert "ANTI-PREMATURE-CLOSURE" in system
    assert result.trace["prompts"][0]["version"] == 1
    later, client, _ = ask_fixtures._run(responses)
    assert "LATER ASK INSTRUCTIONS" in json.dumps(client.calls[0]["system"])
    assert later.trace["prompts"][0]["version"] > 1


def test_document_writer_and_reviewer_keep_separate_admitted_instructions(db):
    doc_fixtures._save_set(
        db,
        "kb-authoring",
        {"guidance": "Use facts", "exposure": "Public only", "how-to": "Steps"},
    )
    save(db, "docgen", "WRITER INSTRUCTIONS")
    save(db, "document_review", "REVIEWER INSTRUCTIONS")
    writer, reviewer = (
        ai_prompts.resolve("docgen"),
        ai_prompts.resolve("document_review"),
    )
    save(db, "docgen", "LATER WRITER")
    save(db, "document_review", "LATER REVIEWER")
    client = doc_fixtures.FakeAnthropic(
        [doc_fixtures._emit(), doc_fixtures._review_ok()]
    )
    result = doc_fixtures._run(
        client,
        guideline_set="kb-authoring",
        document_type="how-to",
        instructions=writer,
        review_instructions=reviewer,
    )
    assert result.outcome == "document_written"
    assert "WRITER INSTRUCTIONS" in json.dumps(client.calls[0]["system"])
    assert "REVIEWER INSTRUCTIONS" in json.dumps(client.calls[1]["system"])
    assert "WRITER INSTRUCTIONS" not in json.dumps(client.calls[1]["system"])
    assert [item["version"] for item in result.trace["prompts"]] == [1, 1]


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_draft_review_uses_saved_behavior_with_fixed_contract(
    db, monkeypatch, provider
):
    save(db, "draft_review", "Review factual changes without stylistic edits.")
    seen: list[str] = []

    def assess(task, config, *, client=None):
        seen.append(task.system)
        assert config.provider == provider
        return Assessment(
            label="good", rationale="Supported", questions=[], corrections=[]
        )

    monkeypatch.setattr(ai, "structured", assess)
    draft_review_model.assess("Evidence", model="fixture", provider=provider)
    assert "Review factual changes without stylistic edits." in seen[0]
    assert "Only the server may authorize application" in seen[0]


def test_unreadable_legacy_default_keeps_diagnostic(tmp_path):
    path = tmp_path / "instructions.md"
    path.write_bytes(b"\xff")
    snapshot = ai_prompts.resolve("ingest", default_path=str(path))
    assert snapshot.text == ""
    assert "doctrine unreadable" in snapshot.reference().note
