"""Domain errors shared across application boundaries."""


class Conflict(ValueError):
    """An operation conflicts with the current state."""

    code: str | None = None
