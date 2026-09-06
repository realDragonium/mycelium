import json

import pytest

from mycelium import draft_review_settings, model_settings, prompt_store
from test_reviewed_application import _app


@pytest.fixture
def settings_db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


def test_upgrade_import_is_once_and_missing_rows_do_not_revive_environment(
    settings_db, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_INGEST_MODEL", "legacy-claude")
    monkeypatch.setenv("MYCELIUM_ASK_PROVIDER", "openai")
    monkeypatch.setenv("MYCELIUM_ASK_OPENAI_MODEL", "legacy-gpt")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_USER_ID", "legacy-reviewer")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    prompt_store.initialize_settings(settings_db)
    assert model_settings.get("ask", conn=settings_db).model == "legacy-gpt"
    assert model_settings.get("research", conn=settings_db).model == "legacy-claude"
    controls = draft_review_settings.load_controls(settings_db)
    assert controls.mode == "review-and-apply"
    assert controls.reviewer_id == "legacy-reviewer"
    assert controls.application_enabled
    monkeypatch.setenv("MYCELIUM_ASK_OPENAI_MODEL", "changed")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "off")
    prompt_store.initialize_settings(settings_db)
    assert model_settings.get("ask", conn=settings_db).model == "legacy-gpt"
    assert draft_review_settings.load_controls(settings_db) == controls
    settings_db.execute("DELETE FROM model_settings")
    settings_db.execute("DELETE FROM draft_review_settings")
    prompt_store.initialize_settings(settings_db)
    assert (
        model_settings.get("ask", conn=settings_db).model
        == model_settings.defaults("ask").claude_model
    )
    assert draft_review_settings.load_controls(settings_db).mode == "off"
    assert not draft_review_settings.load_controls(settings_db).application_enabled


def test_upgrade_preserves_saved_values_and_only_adds_missing_gate(
    settings_db, monkeypatch
):
    settings_db.execute(
        "INSERT INTO model_settings VALUES ('ask', 7, ?)",
        (
            model_settings.Selection(
                provider="claude", claude_model="saved", openai_model=""
            ).model_dump_json(),
        ),
    )
    settings_db.execute(
        "INSERT INTO draft_review_settings VALUES (1, 4, ?)",
        (json.dumps({"mode": "review-only", "reviewer_id": "saved-reviewer"}),),
    )
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ignored")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    prompt_store.initialize_settings(settings_db)
    assert model_settings.get("ask", conn=settings_db).model == "saved"
    assert model_settings.get("ask", conn=settings_db).revision == 7
    controls = draft_review_settings.load_controls(settings_db)
    assert controls.mode == "review-only"
    assert controls.reviewer_id == "saved-reviewer"
    assert controls.application_enabled
    assert controls.revision == 5


@pytest.mark.parametrize("corrupt", [False, True])
def test_invalid_import_or_saved_data_remains_fail_closed_and_editable(
    settings_db, monkeypatch, corrupt
):
    monkeypatch.setenv("MYCELIUM_ASK_PROVIDER", "invalid")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "invalid")
    if corrupt:
        settings_db.execute("INSERT INTO model_settings VALUES ('ask', 7, '{bad')")
        settings_db.execute("INSERT INTO draft_review_settings VALUES (1, 4, '{bad')")
    prompt_store.initialize_settings(settings_db)
    with pytest.raises(model_settings.Unavailable):
        model_settings.get("ask", conn=settings_db)
    with pytest.raises(model_settings.Unavailable):
        draft_review_settings.load_controls(settings_db)
    editable, error = model_settings.editable("ask", conn=settings_db)
    assert error
    assert editable.revision == (7 if corrupt else 1)
    controls, error = draft_review_settings.editable_controls(settings_db)
    assert error
    assert controls.revision == (4 if corrupt else 1)
    prompt_store.initialize_settings(settings_db)
    assert draft_review_settings.editable_controls(settings_db)[1]


def test_fresh_and_restored_settings_disable_future_environment_import(
    settings_db, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ambient-model")
    prompt_store.initialize_settings(settings_db, import_environment=False)
    prompt_store.initialize_settings(settings_db)
    assert draft_review_settings.load_controls(settings_db).mode == "off"
    assert not draft_review_settings.load_controls(settings_db).application_enabled
    assert (
        model_settings.get("ask", conn=settings_db).model
        == model_settings.defaults("ask").claude_model
    )
    assert settings_db.execute(
        "SELECT 1 FROM instance_settings_migrations WHERE name = 'environment-import-disabled'"
    ).fetchone()


def test_fresh_server_ignores_legacy_environment_in_existing_empty_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ambient-model")
    with _app(tmp_path, monkeypatch):
        assert draft_review_settings.load().mode == "off"
        assert not draft_review_settings.load().application_enabled
        assert (
            model_settings.get("ask").model
            == model_settings.defaults("ask").claude_model
        )


def test_server_upgrade_imports_environment_for_preexisting_prompts_database(
    tmp_path, monkeypatch
):
    conn = prompt_store.connect(tmp_path / "mycelium-prompts.db")
    prompt_store.migrate(conn)
    conn.close()
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "legacy-model")
    with _app(tmp_path, monkeypatch):
        assert model_settings.get("ask").model == "legacy-model"
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "changed-model")
    with _app(tmp_path, monkeypatch):
        assert model_settings.get("ask").model == "legacy-model"


@pytest.mark.parametrize(
    "failure_point", ["prepare_settings", "migrate", "initialize_settings"]
)
def test_interrupted_fresh_startup_cannot_become_environment_upgrade(
    tmp_path, monkeypatch, failure_point
):
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ambient-model")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")
    original = getattr(prompt_store, failure_point)

    def fail(*args, **kwargs):
        raise RuntimeError("Interrupted startup")

    monkeypatch.setattr(prompt_store, failure_point, fail)
    with pytest.raises(RuntimeError, match="Interrupted startup"):
        with _app(tmp_path, monkeypatch):
            pass
    monkeypatch.setattr(prompt_store, failure_point, original)
    with _app(tmp_path, monkeypatch):
        assert (
            model_settings.get("ask").model
            == model_settings.defaults("ask").claude_model
        )
        assert draft_review_settings.load().mode == "off"
        assert not draft_review_settings.load().application_enabled


def test_interrupted_restore_never_imports_target_environment(tmp_path, monkeypatch):
    from mycelium import backup
    from test_backup import _seed_substrate

    source = tmp_path / "source"
    source.mkdir()
    _seed_substrate(source)
    archive = tmp_path / "legacy.tar.gz"
    backup.export_substrate(source, archive)
    target = tmp_path / "target"
    monkeypatch.setenv("MYCELIUM_ASK_MODEL", "ambient-model")
    monkeypatch.setenv("MYCELIUM_DRAFT_REVIEW_MODE", "review-and-apply")
    monkeypatch.setenv("MYCELIUM_REVIEWED_APPLY", "on")

    def fail(*args, **kwargs):
        raise RuntimeError("Interrupted restore")

    monkeypatch.setattr(backup, "_load_data_jsonl", fail)
    with pytest.raises(RuntimeError, match="Interrupted restore"):
        backup.import_substrate(archive, target)
    with _app(target, monkeypatch):
        assert (
            model_settings.get("ask").model
            == model_settings.defaults("ask").claude_model
        )
        assert draft_review_settings.load().mode == "off"
        assert not draft_review_settings.load().application_enabled
