"""List prices for estimating what a model run cost.

An estimate, not a bill: first-party Anthropic rates for prompts within each
model's base tier. Cache writes are the 5-minute rate, 1.25x input. A model
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


def price(provider: Provider, model: str) -> Price | None:
    return _CLAUDE.get(model) if provider == "claude" else None
