from mycelium import agentloop


def test_cost_bills_cached_input_at_claudes_cache_rates() -> None:
    tokens = {
        "input": 1_000_000,
        "output": 100_000,
        "cache_creation": 1_000_000,
        "cache_read": 10_000_000,
    }

    assert agentloop.cost_usd(tokens, 3.0, 15.0) == 3.0 + 3.75 + 3.0 + 1.5
