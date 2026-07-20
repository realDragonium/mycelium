"""Canonical timestamp for internal data.

One format for everything the system stores about its own substrate and
its working queues — statements, entities, links, knowledge gaps, drafts,
research runs: ISO-8601 UTC, millisecond precision, trailing `Z`
(`2026-07-08T14:30:00.123Z`).

Auth and OAuth deliberately do NOT use this — they keep Python's default
`datetime.isoformat()` (`+00:00` offset, microsecond precision), the format
those tables have always stored and that `oauth_server` parses back.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _fmt(t: datetime) -> str:
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"


def now() -> str:
    """ISO-8601 UTC timestamp with millisecond precision and trailing Z."""
    return _fmt(datetime.now(timezone.utc))


def days_ago(n: int) -> str:
    """A `now()`-format timestamp `n` days in the past. The format sorts
    lexicographically, so `at < days_ago(n)` is a valid age comparison."""
    return _fmt(datetime.now(timezone.utc) - timedelta(days=n))
