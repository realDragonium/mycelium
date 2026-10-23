"""List prices for estimating what a model run cost.

An estimate, not a bill: first-party standard-tier list rates for prompts
within each model's base context tier. Claude cache writes are the 5-minute
rate, 1.25x input; OpenAI reports no cache writes, and a model without a
cached-input discount lists its input rate. Long-context surcharges, batch and
priority tiers, and SDK retries of a timed-out attempt are not counted. A model
missing here has no estimate rather than a guessed one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Provider, Usage


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25

    def cost_usd(self, usage: Usage) -> float:
        return round(
            (
                usage.input_tokens * self.input
                + usage.output_tokens * self.output
                + usage.cache_read_input_tokens * self.cache_read
                + usage.cache_creation_input_tokens * self.cache_write
            )
            / 1_000_000,
            6,
        )


_CLAUDE: dict[str, Price] = {
    "claude-fable-5-1": Price(10.0, 50.0, 0.25),
    "claude-fable-5": Price(10.0, 50.0, 1.0),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-5": Price(5.0, 25.0, 0.50),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50),
    "claude-opus-4-7": Price(5.0, 25.0, 0.50),
    "claude-opus-4-6": Price(5.0, 25.0, 0.50),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01),
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10),
}


_OPENAI: dict[str, Price] = {
    "gpt-6-astra": Price(10.0, 50.0, 1.0),
    "gpt-6.1-sol": Price(2.0, 10.0, 0.10),
    "gpt-6-sol": Price(2.0, 10.0, 0.20),
    "gpt-6-luna": Price(0.10, 0.50, 0.01),
    "gpt-5.6-sol": Price(4.0, 20.0, 0.40),
    "gpt-5.6-terra": Price(2.0, 12.0, 0.20),
    "gpt-5.6-luna": Price(0.20, 1.20, 0.02),
    "gpt-5.5": Price(5.0, 30.0, 0.50),
    "gpt-5.5-pro": Price(30.0, 180.0, 30.0),
    "gpt-5.4": Price(2.50, 15.0, 0.25),
    "gpt-5.4-pro": Price(30.0, 180.0, 30.0),
    "gpt-5.4-mini": Price(0.75, 4.50, 0.075),
    "gpt-5.4-nano": Price(0.20, 1.25, 0.02),
    "gpt-5.2": Price(1.75, 14.0, 0.175),
    "gpt-5.2-pro": Price(21.0, 168.0, 21.0),
    "gpt-5.1": Price(1.25, 10.0, 0.125),
    "gpt-5": Price(1.25, 10.0, 0.125),
    "gpt-5-mini": Price(0.25, 2.0, 0.025),
    "gpt-5-nano": Price(0.05, 0.40, 0.005),
    "gpt-5-pro": Price(15.0, 120.0, 15.0),
    "gpt-4.1": Price(2.0, 8.0, 0.50),
    "gpt-4.1-mini": Price(0.40, 1.60, 0.10),
    "gpt-4.1-nano": Price(0.10, 0.40, 0.025),
    "gpt-4o": Price(2.50, 10.0, 1.25),
    "gpt-4o-mini": Price(0.15, 0.60, 0.075),
    "o3": Price(2.0, 8.0, 0.50),
    "o3-pro": Price(20.0, 80.0, 20.0),
    "o4-mini": Price(1.10, 4.40, 0.275),
}


def price(provider: Provider, model: str) -> Price | None:
    return (_CLAUDE if provider == "claude" else _OPENAI).get(model)
