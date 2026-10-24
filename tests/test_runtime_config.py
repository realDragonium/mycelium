import pytest

from mycelium import product_settings
from mycelium.ask.config import AskConfig
from mycelium.docgen.config import DocgenConfig
from mycelium.ingest.config import IngestConfig
from mycelium.ingest.connect import config_from_settings


@pytest.mark.parametrize(
    ("config_type", "settings_type"),
    [
        (AskConfig, product_settings.AskSettings),
        (IngestConfig, product_settings.IngestSettings),
        (DocgenConfig, product_settings.DocgenSettings),
    ],
)
def test_runtime_limits_default_to_the_product_settings(config_type, settings_type):
    assert config_type().limits == settings_type()


@pytest.mark.parametrize(
    ("config_type", "limits"),
    [
        (AskConfig, product_settings.AskSettings(cache=False, recon_k=3)),
        (IngestConfig, product_settings.IngestSettings(max_input_chars=123)),
        (
            DocgenConfig,
            product_settings.DocgenSettings(max_prompt_chars=123, recon_k=3),
        ),
    ],
)
def test_runtime_config_preserves_saved_limits_as_a_component(
    config_type, limits, monkeypatch
):
    def get(settings_type):
        return limits if settings_type is type(limits) else settings_type()

    monkeypatch.setattr(product_settings, "get", get)
    assert config_type.from_env().limits is limits


def test_connect_adapts_its_saved_limits_for_the_ingest_loop(monkeypatch):
    limits = product_settings.ConnectSettings(
        op_cap=7,
        wall_clock_s=30.0,
        max_tokens=1000,
        max_retries=0,
        request_timeout_s=10.0,
        thinking=False,
        max_run_tokens=50_000,
    )
    monkeypatch.setattr(product_settings, "get", lambda _: limits)
    config = config_from_settings()
    assert config.limits.model_dump(exclude={"kind", "max_input_chars"}) == (
        limits.model_dump(
            exclude={
                "kind",
                "batch_size",
                "max_run_tokens",
                "connect_automatically",
                "decide_duplicates",
                "describe_concepts",
                "act_on_gaps",
            }
        )
    )
    assert (
        config.limits.max_input_chars
        == product_settings.IngestSettings().max_input_chars
    )
    assert config.max_run_tokens == limits.max_run_tokens
