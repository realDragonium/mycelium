"""Saved model configuration for isolated workflow tests."""

from mycelium import (
    auth,
    draft_review_settings,
    model_settings,
    product_settings,
    prompt_store,
    store,
)
from mycelium.ai import Provider
from mycelium.draft_review_store import AutoApply, Mode


def offer_models(provider: Provider, *models: str) -> None:
    """Add `models` to the catalog, as an admin does before choosing them."""
    if not prompt_store.is_configured():
        conn = prompt_store.connect(":memory:")
        prompt_store.migrate(conn)
        prompt_store.use_connection(conn)
    db = prompt_store.connection()
    current = product_settings.editable(product_settings.ModelCatalogSettings(), db)
    assert isinstance(current.settings, product_settings.ModelCatalogSettings)
    offered = current.settings.models(provider)
    added = offered + tuple(m for m in dict.fromkeys(models) if m and m not in offered)
    product_settings.save(
        product_settings.SaveSettings(
            revision=current.revision,
            settings=current.settings.model_copy(update={provider: added}),
        ),
        auth.LOCAL_ADMIN,
    )


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
    if claude_model:
        offer_models("claude", claude_model)
    if openai_model:
        offer_models("openai", openai_model)
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
    alias_decisions: bool | None = None,
    answer_questions: bool | None = None,
    reject_refused: bool | None = None,
    auto_apply: AutoApply | None = None,
) -> None:
    db = prompt_store.connection()
    current = draft_review_settings.load_controls(db)
    controls = draft_review_settings.Controls(
        mode=current.mode if mode is None else mode,
        reviewer_id=current.reviewer_id if reviewer_id is None else reviewer_id,
        application_enabled=current.application_enabled
        if application_enabled is None
        else application_enabled,
        alias_decisions=current.alias_decisions
        if alias_decisions is None
        else alias_decisions,
        answer_questions=current.answer_questions
        if answer_questions is None
        else answer_questions,
        reject_refused=current.reject_refused
        if reject_refused is None
        else reject_refused,
        auto_apply=current.auto_apply if auto_apply is None else auto_apply,
    )
    with store.write_lock(), prompt_store._writing(db):
        db.execute(
            "UPDATE draft_review_settings SET revision = revision + 1, body_json = ?",
            (controls.model_dump_json(),),
        )


def assume_configured_models(monkeypatch) -> None:
    """Treat every action nobody configured as configured with the Claude
    model it ran on before the catalog, as on an upgraded instance. A fresh
    server then saves those models and offers them in its catalog."""
    monkeypatch.setattr(model_settings, "defaults", model_settings.former_default)
