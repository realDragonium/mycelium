from mycelium.ai import Usage, pricing


def test_cost_bills_cache_reads_and_writes_at_their_own_rates():
    price = pricing.price("claude", "claude-opus-5-5")
    assert price is not None
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    assert price.cost_usd(usage) == 4.0 + 20.0 + 0.20 + 5.0


def test_a_model_without_a_list_price_has_no_estimate():
    assert pricing.price("claude", "claude-unlisted") is None
    assert pricing.price("openai", "claude-opus-5-5") is None


def test_openai_models_are_estimated_without_cache_writes():
    price = pricing.price("openai", "gpt-5.4")
    assert price is not None
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert price.cost_usd(usage) == 2.50 + 15.0 + 0.25
