"""Saved model configuration for isolated workflow tests."""

from mycelium import auth, draft_review_settings, model_settings, prompt_store, store
from mycelium.ai import Provider
from mycelium.draft_review_store import Mode


def save_model(
    action: model_settings.Action,
    *,
    provider: Provider | None = None,
    claude_model: str | None = None,
    openai_model: str | None = None,
) -> None:
    if not prompt_store.is_configured():
        conn = prompt_store.connect(":memory:")
        prompt_store.migrate(conn)
        prompt_store.use_connection(conn)
    current = model_settings.get(action)
    model_settings.save(
        action,
        model_settings.SaveSelection(
            provider=provider or current.provider,
            claude_model=current.claude_model if claude_model is None else claude_model,
            openai_model=current.openai_model if openai_model is None else openai_model,
            revision=current.revision,
        ),
        auth.LOCAL_ADMIN,
    )


def set_review_controls(
    *,
    mode: Mode | None = None,
    reviewer_id: str | None = None,
    application_enabled: bool | None = None,
) -> None:
    db = prompt_store.connection()
    current = draft_review_settings.load_controls(db)
    controls = draft_review_settings.Controls(
        mode=current.mode if mode is None else mode,
        reviewer_id=current.reviewer_id if reviewer_id is None else reviewer_id,
        application_enabled=current.application_enabled
        if application_enabled is None
        else application_enabled,
    )
    with store.write_lock(), prompt_store._writing(db):
        db.execute(
            "UPDATE draft_review_settings SET revision = revision + 1, body_json = ?",
            (controls.model_dump_json(),),
        )
