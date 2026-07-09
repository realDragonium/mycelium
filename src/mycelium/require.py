"""Narrow an Optional to its value, raising if absent.

For invariants the type system can't express: a row read back immediately
after the write that created it, a mapping that must exist by construction.
Replaces bare ``assert x is not None`` — which carries no message and is
stripped entirely under ``python -O`` — with a real, always-on failure that
names what went missing.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def require(value: T | None, what: str) -> T:
    """Return `value` unchanged, or raise `RuntimeError` if it is `None`."""
    if value is None:
        raise RuntimeError(f"{what} unexpectedly missing")
    return value
