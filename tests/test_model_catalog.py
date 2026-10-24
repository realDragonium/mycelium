"""The admin's model catalog: the only models an action can be set to."""

import pytest

from mycelium import auth, model_settings, product_settings, prompt_store
from mycelium.docgen.config import model_choices
from settings_helpers import offer_models, save_model


@pytest.fixture
def settings_db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    prompt_store.use_connection(conn)
    yield conn
    conn.close()


def _save_catalog(**models: tuple[str, ...]) -> product_settings.Snapshot:
    current = product_settings.editable(
        product_settings.ModelCatalogSettings(), prompt_store.connection()
    )
    return product_settings.save(
        product_settings.SaveSettings(
            revision=current.revision,
            settings=current.settings.model_copy(update=models),
        ),
        auth.LOCAL_ADMIN,
    )


def test_a_fresh_instance_has_no_models_and_says_what_to_choose(settings_db):
    prompt_store.initialize_settings(settings_db, import_environment=False)

    assert model_settings.catalog() == {"claude": (), "openai": ()}
    assert {model_settings.get(action).model for action in model_settings.ACTIONS} == {
        ""
    }
    assert (
        model_settings.credentials_error("docgen")
        == "Choose a Claude model for document generation in AI settings."
    )
    with pytest.raises(ValueError, match="Choose a Claude model for Ask"):
        model_settings.require("ask")
    claude, openai = model_choices()
    assert (claude["available"], claude["reason"]) == (
        False,
        "Choose a Claude model for document generation in AI settings.",
    )
    assert openai["reason"] == (
        "Choose an OpenAI model for document generation in AI settings."
    )


def test_an_action_can_only_be_set_to_a_catalog_model(settings_db):
    with pytest.raises(ValueError, match="not in the Claude model catalog"):
        model_settings.save(
            "ask",
            model_settings.SaveSelection(
                provider="claude",
                claude_model="claude-sonnet-5-5",
                openai_model="",
                revision=0,
            ),
            auth.LOCAL_ADMIN,
        )

    save_model("ask", claude_model="claude-sonnet-5-5")

    assert model_settings.get("ask").model == "claude-sonnet-5-5"


def test_removing_a_model_in_use_is_refused_naming_its_actions(settings_db):
    save_model("ask", claude_model="claude-sonnet-5-5")
    save_model("connect", claude_model="claude-sonnet-5-5")
    save_model(
        "docgen",
        provider="openai",
        claude_model="claude-opus-5-5",
        openai_model="gpt-5.4",
    )
    offer_models("claude", "claude-haiku-5-5")

    with pytest.raises(ValueError) as refused:
        _save_catalog(claude=("claude-opus-5-5", "claude-haiku-5-5"))
    assert str(refused.value) == (
        "'claude-sonnet-5-5' is used by Ask, Connecting statements. "
        "Choose another model for them first."
    )
    # Documentation offers both providers when generating, so its Claude
    # model stays in use while it runs on OpenAI.
    with pytest.raises(ValueError, match="'claude-opus-5-5' is used by Document"):
        _save_catalog(claude=("claude-sonnet-5-5",))

    saved = _save_catalog(claude=("claude-opus-5-5", "claude-sonnet-5-5"))
    assert model_settings.catalog()["claude"] == (
        "claude-opus-5-5",
        "claude-sonnet-5-5",
    )
    assert saved.revision > 0


@pytest.mark.parametrize(
    "models, message",
    [
        ({"claude": ("claude-sonnet-5-5", "claude-sonnet-5-5")}, "more than once"),
        ({"claude": ("gpt-5.4",)}, "model ID for OpenAI"),
        ({"openai": (" ",)}, "at least 1 character"),
    ],
)
def test_the_catalog_refuses_ids_it_could_not_offer(models, message):
    with pytest.raises(ValueError, match=message):
        product_settings.ModelCatalogSettings(**models)


def test_the_catalog_marks_models_without_a_list_price(settings_db):
    offer_models("openai", "gpt-5.4", "acme-large")

    assert [
        (entry.model, entry.priced)
        for entry in model_settings.catalog_view()
        if entry.provider == "openai"
    ] == [("gpt-5.4", True), ("acme-large", False)]
