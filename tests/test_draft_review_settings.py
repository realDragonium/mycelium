import json
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from mycelium import (
    auth,
    backup,
    draft_review_model,
    draft_review_runs,
    draft_review_store,
    drafts_store,
    model_settings,
    prompt_store,
    server,
    store,
)
from mycelium import (
    draft_review_settings as settings,
)
from test_backup import _seed_substrate
from test_internal_draft_review import (
    _assessment,
    _draft,
    _request,
    _result,
    _set_review_controls,
    _set_review_model,
)
from test_internal_draft_review import running_app as running_app


@pytest.fixture
def configured_app(running_app, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-claude-key")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODEL", "gpt-fixture")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_PROVIDER", "openai")
    _set_review_model("gpt-fixture")
    return running_app


def _body(client, **changes):
    current = client.get("/api/draft-review/settings").json()
    return {
        **{
            key: current[key]
            for key in (
                "application_enabled",
                "mode",
                "provider",
                "model",
                "reviewer_id",
                "revision",
                "model_revision",
            )
        },
        **changes,
    }


def test_save_persists_and_environment_cannot_override(configured_app, monkeypatch):
    client, reviewer = configured_app
    initial = client.get("/api/draft-review/settings").json()
    assert initial["source"] == "saved"
    assert initial["revision"] == 2
    assert initial["reviewer_id"] == reviewer
    assert initial["ready"] is True
    assert initial["application_enabled"] is False
    body = _body(client, mode="review-only", provider="claude", model="claude-fixture")
    response = client.patch("/api/draft-review/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 3
    assert response.json()["source"] == "saved"
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODEL", "changed-environment")
    path = prompt_store.connection().execute("PRAGMA database_list").fetchone()[2]
    conn = prompt_store.connect(path)
    try:
        reopened = settings.load(conn)
        assert reopened.model == "claude-fixture"
        assert reopened.mode == "review-only"
    finally:
        conn.close()
    assert client.patch("/api/draft-review/settings", json=body).status_code == 409
    same = client.patch("/api/draft-review/settings", json=_body(client))
    assert same.json()["revision"] == 3
    assert "fixture-openai-key" not in response.text
    assert "fixture-claude-key" not in response.text


@pytest.mark.parametrize("role", ["reader", "drafter", "writer", "admin"])
def test_only_real_admin_can_configure(configured_app, role):
    client, _ = configured_app
    conn = server._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(conn, user_id=user, name="Fixture", scope=role)
    headers = {"Authorization": f"Bearer {raw}"}
    view = client.get("/api/draft-review/settings", headers=headers).json()
    assert view["can_configure"] == (role == "admin")
    assert bool(view["reviewers"]) == (role == "admin")
    response = client.patch(
        "/api/draft-review/settings", json=_body(client), headers=headers
    )
    assert response.status_code == (200 if role == "admin" else 403)


def test_scoped_admin_token_cannot_configure(configured_app):
    client, _ = configured_app
    with store.transaction(server._auth_db()):
        user = auth.create_user(
            server._auth_db(), name="Admin", role="admin", type="service"
        )
        raw, _ = auth.issue_token(
            server._auth_db(), user_id=user, name="Scoped", scope="writer"
        )
    response = client.patch(
        "/api/draft-review/settings",
        json=_body(client),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403


def test_off_can_be_saved_without_setup(configured_app, monkeypatch):
    client, _ = configured_app
    monkeypatch.delenv("OPENAI_API_KEY")
    body = _body(client, mode="review-only", model="", reviewer_id="")
    assert client.patch("/api/draft-review/settings", json=body).status_code == 400
    response = client.patch("/api/draft-review/settings", json={**body, "mode": "off"})
    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert len(response.json()["issues"]) == 3
    assert settings.load().mode == "off"


def test_corruption_fails_closed_and_is_not_environment_fallback(
    configured_app, monkeypatch
):
    client, _ = configured_app
    assert (
        client.patch("/api/draft-review/settings", json=_body(client)).status_code
        == 200
    )
    prompt_store.connection().execute(
        "UPDATE draft_review_settings SET body_json = '{bad'"
    )
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    view = client.get("/api/draft-review/settings")
    assert view.status_code == 200
    assert view.json()["configuration_error"]
    assert view.json()["ready"] is False
    with pytest.raises(settings.Unavailable, match="cannot be read"):
        settings.load()
    draft_id = _draft()
    assert _result(draft_id) is None


@pytest.mark.parametrize(
    "change", ["off-on", "gate-off-on", "model", "provider", "reviewer", "review-only"]
)
def test_any_settings_generation_change_prevents_old_automatic_action(
    configured_app, monkeypatch, change
):
    client, _ = configured_app
    draft_id = _draft()
    _set_review_controls(application_enabled=True)
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, mode="review-and-apply")
        ).status_code
        == 200
    )

    def model(context):
        current = settings.load()
        changes = {"mode": "review-only"}
        if change == "off-on":
            settings.save(
                settings.SaveSettings(
                    **{**current.model_dump(exclude={"source"}), "mode": "off"}
                ),
                auth.LOCAL_ADMIN,
            )
            changes = {"mode": "review-and-apply"}
        elif change == "gate-off-on":
            settings.save(
                settings.SaveSettings(
                    **{
                        **current.model_dump(exclude={"source"}),
                        "application_enabled": False,
                    }
                ),
                auth.LOCAL_ADMIN,
            )
            changes = {"application_enabled": True}
        elif change == "model":
            changes = {"model": "gpt-new"}
        elif change == "provider":
            changes = {"provider": "claude", "model": "claude-new"}
        elif change == "reviewer":
            with store.transaction(server._auth_db()):
                other = auth.create_user(
                    server._auth_db(), name="Other", role="writer", type="service"
                )
            changes = {"reviewer_id": other}
        settings.save(
            settings.SaveSettings(
                **{**settings.load().model_dump(exclude={"source"}), **changes}
            ),
            auth.LOCAL_ADMIN,
        )
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "completed", result
    assert result["application"] == "unapplied"
    assert result["settings_revision"] == 4
    assert drafts_store.list_reviews(server._drafts_db(), draft_id) == []
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_queued_runs_keep_admitted_provider_model_and_reviewer(
    configured_app, monkeypatch
):
    client, reviewer = configured_app
    executor = ThreadPoolExecutor(max_workers=1)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(context, *, model, provider, limits):
        calls.append((model, provider, limits.max_tokens))
        entered.set()
        assert release.wait(5)
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "_executor", executor)
    monkeypatch.setattr(draft_review_runs, "RUNNER", None)
    monkeypatch.setattr(draft_review_model, "assess", model)
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, mode="review-and-apply")
        ).status_code
        == 200
    )
    _set_review_controls(application_enabled=True)
    try:
        first = _draft()
        assert entered.wait(5)
        second = _draft()
        from mycelium import product_settings
        from product_settings_helpers import set_product

        set_product(product_settings.ReviewSettings(max_tokens=1000))
        assert (
            client.patch(
                "/api/draft-review/settings",
                json=_body(client, provider="claude", model="claude-new"),
            ).status_code
            == 200
        )
    finally:
        release.set()
        draft_review_runs.wait_all()
        executor.shutdown()
    assert calls == [("gpt-fixture", "openai", 6000), ("gpt-fixture", "openai", 6000)]
    for draft_id in (first, second):
        result = _result(draft_id)
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-fixture"
        assert result["reviewer_id"] == reviewer
        assert result["application"] == "unapplied"


def test_fresh_rerun_uses_current_settings(configured_app, monkeypatch):
    client, _ = configured_app
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, mode="review-only")
        ).status_code
        == 200
    )
    draft_id = _draft()
    before = _result(draft_id)
    assert (
        client.patch(
            "/api/draft-review/settings",
            json=_body(
                client, mode="review-and-apply", provider="claude", model="claude-new"
            ),
        ).status_code
        == 200
    )
    _set_review_controls(application_enabled=True)
    _request(draft_id, rerun=True)
    after = _result(draft_id)
    assert before["application"] == "unapplied"
    assert after["run_id"] != before["run_id"]
    assert after["provider"] == "claude"
    assert after["model"] == "claude-new"
    assert after["application"] == "applied"


def test_historical_run_metadata_remains_unknown():
    run = draft_review_store.ReviewRun.model_validate(
        {"run_id": "old", "draft_id": "d", "mode": "review-only", "draft_revision": 1}
    )
    assert run.provider is None
    assert run.model is None
    assert run.reviewer_id is None
    assert run.settings_revision is None


def _claude_response(*, stop="end_turn", text=None):
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "model": "claude-fixture",
        "content": [
            {
                "type": "text",
                "text": text if text is not None else _assessment().model_dump_json(),
            }
        ],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_provider_uses_captured_model_and_structured_wire(monkeypatch, provider):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODEL", "wrong-environment")
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == "captured-model"
        if provider == "claude":
            assert request.url.path == "/v1/messages"
            assert payload["output_config"]["format"]["type"] == "json_schema"
            assert payload["max_tokens"] == 6000
            response = _claude_response()
        else:
            assert request.url.path == "/v1/responses"
            assert payload["text"]["format"]["strict"] is True
            assert payload["max_output_tokens"] == 6000
            response = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": _assessment().model_dump_json(),
                            }
                        ],
                    }
                ],
            }
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = draft_review_model.assess(
            "Supplied evidence",
            provider=provider,
            model="captured-model",
            client=client,
        )
    assert result.label == "good"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "failure",
    ["http", "timeout", "truncated", "refused", "invalid", "invalid-semantics"],
)
def test_claude_failures_are_safe_unusable_assessments(monkeypatch, failure):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    secret = "private supplied evidence"

    def handle(request):
        if failure == "http":
            return httpx.Response(500, text=secret)
        if failure == "timeout":
            raise httpx.ReadTimeout(secret)
        if failure == "truncated":
            response = _claude_response(stop="max_tokens")
        elif failure == "refused":
            response = _claude_response(stop="refusal")
        elif failure == "invalid":
            response = _claude_response(text=secret)
        else:
            response = _claude_response(
                text=json.dumps(
                    {
                        "label": "good",
                        "rationale": "Fine",
                        "questions": ["Why?"],
                        "corrections": [],
                    }
                )
            )
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError) as error:
            draft_review_model.assess(
                "Evidence", provider="claude", model="claude-fixture", client=client
            )
    assert secret not in str(error.value)


def test_settings_backup_restore_and_legacy_archive(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _seed_substrate(src)
    conn = prompt_store.connect(src / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    saved = settings.Controls(
        mode="review-only", reviewer_id="reviewer", application_enabled=True
    )
    conn.execute(
        "INSERT INTO draft_review_settings VALUES (1, 8, ?)", (saved.model_dump_json(),)
    )
    conn.close()
    archive = tmp_path / "backup.tar.gz"
    manifest = backup.export_substrate(src, archive)
    assert manifest["includes_draft_review_settings"] is True
    backup.import_substrate(archive, dst)
    restored = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    try:
        assert settings.load_controls(restored) == settings.ControlSnapshot(
            **saved.model_dump(), revision=8, source="saved"
        )
    finally:
        restored.close()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    _seed_substrate(legacy)
    old = tmp_path / "old.tar.gz"
    backup.export_substrate(legacy, old)
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ambient-model")
    backup.import_substrate(old, tmp_path / "old-restored")
    restored = prompt_store.connect(tmp_path / "old-restored" / backup.PROMPTS_DB_NAME)
    try:
        prompt_store.initialize_settings(restored)
        assert settings.load_controls(restored).mode == "off"
        assert not settings.load_controls(restored).application_enabled
        assert (
            model_settings.get("ask", conn=restored).model
            == model_settings.defaults("ask").claude_model
        )
    finally:
        restored.close()


@pytest.mark.parametrize("corrupt", [True, False])
def test_invalid_or_missing_archived_settings_refuse_before_target_changes(
    tmp_path, corrupt
):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)
    staging = tmp_path / "staging"
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    manifest = json.loads((staging / "manifest.json").read_text())
    manifest["includes_draft_review_settings"] = True
    (staging / "manifest.json").write_text(json.dumps(manifest))
    if corrupt:
        (staging / "draft-review-settings.json").write_text('{"mode":"invalid"}')
    backup._make_archive(staging, archive)
    sentinel = src / "keep-me"
    sentinel.write_text("Original target")
    with pytest.raises(ValueError):
        backup.import_substrate(archive, src, force=True)
    assert sentinel.read_text() == "Original target"


def test_corrupt_saved_settings_abort_export(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    conn = prompt_store.connect(src / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    conn.execute("INSERT INTO draft_review_settings VALUES (1, 1, '{invalid')")
    conn.close()
    with pytest.raises(settings.Unavailable):
        backup.export_substrate(src, tmp_path / "snap.tar.gz")


def _model_body(client, action, **changes):
    rows = client.get("/api/model-settings").json()["actions"]
    row = next(row for row in rows if row["action"] == action)
    return {
        **{
            key: row[key]
            for key in ("provider", "claude_model", "openai_model", "revision")
        },
        **changes,
    }


def test_actions_persist_independent_models_and_remember_alternate(
    configured_app, monkeypatch
):
    client, _ = configured_app
    response = client.get("/api/model-settings")
    assert response.status_code == 200
    assert {row["action"] for row in response.json()["actions"]} == set(
        model_settings.ACTIONS
    )
    for index, action in enumerate(model_settings.ACTIONS):
        body = _model_body(
            client,
            action,
            provider="openai",
            claude_model=f"claude-{index}",
            openai_model=f"gpt-{index}",
        )
        saved = client.patch(f"/api/model-settings/{action}", json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["model"] == f"gpt-{index}"
        assert (
            client.patch(f"/api/model-settings/{action}", json=body).status_code == 409
        )
    for index, action in enumerate(model_settings.ACTIONS):
        monkeypatch.setenv(
            "MYCELIUM_" + action.upper() + "_OPENAI_MODEL", "ignored-env"
        )
        assert model_settings.get(action).model == f"gpt-{index}"

    from mycelium.ask.config import AskConfig
    from mycelium.docgen.config import DocgenConfig
    from mycelium.ingest.config import IngestConfig
    from mycelium.research.config import ResearchConfig

    for index, config_type in enumerate(
        (AskConfig, IngestConfig, ResearchConfig, DocgenConfig)
    ):
        configured = config_type.from_env()
        assert configured.provider == "openai"
        assert configured.model == f"gpt-{index}"
    assert DocgenConfig.from_env(provider="claude").model == "claude-3"
    assert settings.load().model == "gpt-4"
    review = client.get("/api/draft-review/settings").json()
    assert review["model"] == "gpt-4"
    assert review["model_revision"] == 3
    assert review["claude_model"] == "claude-4"


def test_review_controls_and_model_save_are_atomic_with_cas(configured_app):
    client, _ = configured_app
    stale = _body(client, mode="review-only", model="stale-model")
    body = _model_body(client, "draft_review", openai_model="new-model")
    assert (
        client.patch("/api/model-settings/draft_review", json=body).status_code == 200
    )
    assert client.patch("/api/draft-review/settings", json=stale).status_code == 409
    view = client.get("/api/draft-review/settings").json()
    assert view["mode"] == "off"
    assert view["revision"] == 2
    assert view["model"] == "new-model"
    assert (
        client.patch(
            "/api/draft-review/settings",
            json=_body(client, provider="claude", model="new-claude"),
        ).status_code
        == 200
    )
    shared = model_settings.get("draft_review")
    assert shared.model == "new-claude"
    assert shared.openai_model == "new-model"
    assert shared.revision == 4


@pytest.mark.parametrize("role", ["reader", "drafter", "writer", "admin"])
def test_model_settings_writes_require_admin(configured_app, role):
    client, _ = configured_app
    with store.transaction(server._auth_db()):
        user = auth.create_user(server._auth_db(), name=role, role=role, type="service")
        raw, _ = auth.issue_token(
            server._auth_db(), user_id=user, name="Fixture", scope=role
        )
    response = client.patch(
        "/api/model-settings/ask",
        json=_model_body(client, "ask"),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == (200 if role == "admin" else 403)


@pytest.mark.parametrize("provider", ["claude", "openai"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_selected_model_required_but_alternate_optional(
    configured_app, provider, blank
):
    client, _ = configured_app
    body = _model_body(client, "docgen")
    body.update(provider=provider, claude_model="", openai_model="")
    selected = "claude_model" if provider == "claude" else "openai_model"
    body[selected] = blank
    before = model_settings.get("docgen")
    response = client.patch("/api/model-settings/docgen", json=body)
    assert response.status_code == 400
    assert model_settings.get("docgen") == before
    body[selected] = "chosen-model"
    assert client.patch("/api/model-settings/docgen", json=body).status_code == 200
    assert model_settings.get("docgen").model == "chosen-model"


def test_empty_legacy_review_model_cannot_create_a_run(configured_app):
    draft_id = _draft()
    _set_review_controls(mode="review-only")
    current = model_settings.get("draft_review")
    selection = model_settings.Selection(
        provider="openai", claude_model=current.claude_model, openai_model=""
    )
    with prompt_store._writing(prompt_store.connection()):
        prompt_store.connection().execute(
            "UPDATE model_settings SET body_json = ? WHERE action = 'draft_review'",
            (selection.model_dump_json(),),
        )
    with pytest.raises(ValueError, match="Choose a model ID"):
        _request(draft_id)
    assert draft_review_store.latest(server._drafts_db(), draft_id) is None


def test_model_setting_change_alone_invalidates_automatic_review(
    configured_app, monkeypatch
):
    client, _ = configured_app
    draft_id = _draft()
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, mode="review-and-apply")
        ).status_code
        == 200
    )
    _set_review_controls(application_enabled=True)

    def model(context):
        current = model_settings.get("draft_review")
        model_settings.save(
            "draft_review",
            model_settings.SaveSelection(
                provider="openai",
                claude_model=current.claude_model,
                openai_model="changed-gpt",
                revision=current.revision,
            ),
            auth.LOCAL_ADMIN,
        )
        return _assessment()

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    _request(draft_id)
    result = _result(draft_id)
    assert result["status"] == "completed"
    assert result["application"] == "unapplied"
    assert result["settings_revision"] == 4
    assert result["model_settings_revision"] == 2
    assert server.get_draft(draft_id)["status"] == "submitted"


def test_all_model_settings_backup_round_trip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    conn = prompt_store.connect(src / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    for index, action in enumerate(model_settings.ACTIONS):
        selection = model_settings.Selection(
            provider="openai",
            claude_model=f"claude-{index}",
            openai_model=f"gpt-{index}",
        )
        conn.execute(
            "INSERT INTO model_settings VALUES (?, ?, ?)",
            (action, index + 1, selection.model_dump_json()),
        )
    conn.close()
    archive = tmp_path / "models.tar.gz"
    manifest = backup.export_substrate(src, archive)
    assert manifest["includes_model_settings"] is True
    dst = tmp_path / "dst"
    backup.import_substrate(archive, dst)
    restored = prompt_store.connect(dst / backup.PROMPTS_DB_NAME)
    try:
        for index, action in enumerate(model_settings.ACTIONS):
            assert model_settings.get(action, conn=restored).model == f"gpt-{index}"
            assert model_settings.get(action, conn=restored).revision == index + 1
    finally:
        restored.close()


def test_corrupt_model_row_fails_closed(configured_app, monkeypatch, tmp_path):
    client, _ = configured_app
    assert (
        client.patch(
            "/api/model-settings/draft_review", json=_model_body(client, "draft_review")
        ).status_code
        == 200
    )
    prompt_store.connection().execute(
        "UPDATE model_settings SET body_json = '{bad' WHERE action = 'draft_review'"
    )
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    rows = client.get("/api/model-settings").json()["actions"]
    assert next(row for row in rows if row["action"] == "draft_review")[
        "configuration_error"
    ]
    assert (
        next(row for row in rows if row["action"] == "ask")["configuration_error"]
        is None
    )
    view = client.get("/api/draft-review/settings")
    assert view.status_code == 200
    assert view.json()["configuration_error"]
    assert view.json()["ready"] is False
    with pytest.raises(model_settings.Unavailable):
        model_settings.get("draft_review")


def test_concurrent_model_saves_have_one_winner(configured_app):
    client, _ = configured_app
    body = _model_body(client, "ask")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda name: (
                    client.patch(
                        "/api/model-settings/ask", json={**body, "claude_model": name}
                    ).status_code
                ),
                ("claude-one", "claude-two"),
            )
        )
    assert sorted(results) == [200, 409]
    assert model_settings.get("ask").revision == 2


@pytest.mark.parametrize("missing", [True, False])
def test_model_archive_validation_precedes_replacement(tmp_path, missing):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)
    staging = tmp_path / "staging"
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    manifest = json.loads((staging / "manifest.json").read_text())
    manifest["includes_model_settings"] = True
    (staging / "manifest.json").write_text(json.dumps(manifest))
    if not missing:
        (staging / "model-settings.json").write_text('[{"action":"unknown"}]')
    backup._make_archive(staging, archive)
    sentinel = src / "keep-model-target"
    sentinel.write_text("Original")
    with pytest.raises(ValueError):
        backup.import_substrate(archive, src, force=True)
    assert sentinel.read_text() == "Original"


def test_backup_controls_and_models_share_one_snapshot(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _seed_substrate(src)
    path = src / backup.PROMPTS_DB_NAME
    conn = prompt_store.connect(path)
    prompt_store.migrate(conn)
    before = model_settings.Selection(
        provider="openai", claude_model="", openai_model="before"
    )
    conn.execute(
        "INSERT INTO model_settings VALUES ('draft_review', 1, ?)",
        (before.model_dump_json(),),
    )
    conn.execute(
        "INSERT INTO draft_review_settings VALUES (1, 1, ?)",
        (settings.Controls(mode="off").model_dump_json(),),
    )
    conn.close()
    original = backup._archive_review_settings

    def concurrent_save(reader, out_path):
        writer = prompt_store.connect(path)
        try:
            with prompt_store._writing(writer):
                writer.execute(
                    "UPDATE draft_review_settings SET revision = 2, body_json = ?",
                    (settings.Controls(mode="review-and-apply").model_dump_json(),),
                )
                writer.execute(
                    "UPDATE model_settings SET revision = 2, body_json = ?",
                    (
                        model_settings.Selection(
                            provider="claude",
                            claude_model="after",
                            openai_model="before",
                        ).model_dump_json(),
                    ),
                )
        finally:
            writer.close()
        return original(reader, out_path)

    monkeypatch.setattr(backup, "_archive_review_settings", concurrent_save)
    archive = tmp_path / "snapshot.tar.gz"
    backup.export_substrate(src, archive)
    staging = tmp_path / "staging"
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    assert (
        json.loads((staging / "draft-review-settings.json").read_text())["revision"]
        == 1
    )
    assert json.loads((staging / "model-settings.json").read_text())[0]["revision"] == 1


@pytest.mark.parametrize("source", ["invalid-provider", "saved"])
def test_invalid_action_settings_are_explicitly_repairable(
    configured_app, monkeypatch, source
):
    client, _ = configured_app
    if source == "invalid-provider":
        prompt_store.connection().execute(
            "UPDATE model_settings SET body_json = ? WHERE action = 'ask'",
            (
                json.dumps(
                    {
                        "provider": "invalid-provider",
                        "claude_model": "",
                        "openai_model": "",
                    }
                ),
            ),
        )
    else:
        assert (
            client.patch(
                "/api/model-settings/ask", json=_model_body(client, "ask")
            ).status_code
            == 200
        )
        prompt_store.connection().execute(
            "UPDATE model_settings SET body_json = '{bad' WHERE action = 'ask'"
        )
    rows = client.get("/api/model-settings").json()["actions"]
    broken = next(row for row in rows if row["action"] == "ask")
    assert broken["configuration_error"]
    assert broken["claude_model"] == broken["openai_model"] == ""
    with pytest.raises(model_settings.Unavailable):
        model_settings.get("ask")
    body = _model_body(
        client,
        "ask",
        provider="openai",
        claude_model="repaired-claude",
        openai_model="repaired-gpt",
    )
    saved = client.patch("/api/model-settings/ask", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["configuration_error"] is None
    assert model_settings.get("ask").model == "repaired-gpt"
    assert client.patch("/api/model-settings/ask", json=body).status_code == 409


@pytest.mark.parametrize("broken", ["controls", "model", "both"])
def test_off_save_repairs_review_setup_without_credentials(
    configured_app, monkeypatch, broken
):
    client, _ = configured_app
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, mode="review-and-apply")
        ).status_code
        == 200
    )
    if broken in ("controls", "both"):
        prompt_store.connection().execute(
            "UPDATE draft_review_settings SET body_json = '{bad'"
        )
    if broken in ("model", "both"):
        prompt_store.connection().execute(
            "UPDATE model_settings SET body_json = '{bad' WHERE action = 'draft_review'"
        )
    monkeypatch.delenv("OPENAI_API_KEY")
    view = client.get("/api/draft-review/settings").json()
    assert view["configuration_error"]
    assert view["ready"] is False
    with pytest.raises(settings.Unavailable):
        settings.load()
    response = client.patch(
        "/api/draft-review/settings",
        json=_body(client, mode="off", model="", reviewer_id=""),
    )
    assert response.status_code == 200, response.text
    assert response.json()["configuration_error"] is None
    assert settings.load().mode == "off"


def test_manual_application_permission_is_independent_of_automatic_review_setup(
    configured_app,
):
    from test_reviewed_application import _accepted_review, _principal

    client, _ = configured_app
    draft_id = _draft()
    assert (
        client.patch(
            "/api/draft-review/settings",
            json=_body(
                client, mode="off", application_enabled=True, model="", reviewer_id=""
            ),
        ).status_code
        == 200
    )
    prompt_store.connection().execute(
        "UPDATE model_settings SET body_json = '{bad' WHERE action = 'draft_review'"
    )
    token = _principal()
    try:
        review = _accepted_review(draft_id)
        result = server.apply_reviewed_draft(draft_id, review["review_id"])
    finally:
        auth.current_principal.reset(token)
    assert result["applied"] == 1


def test_manual_application_checks_permission_after_waiting_for_write_lock(
    configured_app, monkeypatch
):
    from test_reviewed_application import _accepted_review, _principal

    client, _ = configured_app
    draft_id = _draft()
    assert (
        client.patch(
            "/api/draft-review/settings", json=_body(client, application_enabled=True)
        ).status_code
        == 200
    )
    token = _principal()
    try:
        review = _accepted_review(draft_id)
    finally:
        auth.current_principal.reset(token)
    waiting = threading.Event()
    original = server._identified_principal

    def identified():
        waiting.set()
        return original()

    monkeypatch.setattr(server, "_identified_principal", identified)

    def apply():
        token = _principal()
        try:
            return server.apply_reviewed_draft(draft_id, review["review_id"])
        finally:
            auth.current_principal.reset(token)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store.write_lock():
            result = executor.submit(apply)
            assert waiting.wait(5)
            current = settings.load()
            settings.save(
                settings.SaveSettings(
                    **{
                        **current.model_dump(exclude={"source"}),
                        "application_enabled": False,
                    }
                ),
                auth.LOCAL_ADMIN,
            )
        with pytest.raises(ValueError, match="disabled"):
            result.result(timeout=5)
    assert server.get_draft(draft_id)["status"] == "submitted"
