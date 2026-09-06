"""Deployment-owned GitHub credential bindings; tokens remain in the environment."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from . import prompt_store
from .model_settings import Unavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS github_credential_bindings (
    name TEXT PRIMARY KEY,
    body_json TEXT NOT NULL
);
"""


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    host: str = "github.com"
    token_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=200)

    @model_validator(mode="after")
    def valid_host(self) -> Binding:
        from .docgen.destinations import DestinationError
        from .docgen.github_destination import _validate_host

        try:
            _validate_host("credential binding", self.host)
        except DestinationError:
            raise ValueError("Credential binding host is invalid.") from None
        return self


class Choice(BaseModel):
    name: str
    host: str
    available: bool


BINDINGS = TypeAdapter(dict[str, Binding])


def load(
    conn: sqlite3.Connection | None = None, *, env: Mapping[str, str] | None = None
) -> dict[str, Binding]:
    result: dict[str, Binding] = {}
    try:
        if conn is not None or prompt_store.is_configured():
            db = conn if conn is not None else prompt_store.connection()
            for row in db.execute(
                "SELECT name, body_json FROM github_credential_bindings"
            ):
                result[row["name"]] = Binding.model_validate_json(row["body_json"])
        environment = os.environ if env is None else env
        raw = environment.get("MYCELIUM_GITHUB_CREDENTIALS")
        if raw:
            result.update(BINDINGS.validate_json(raw))
        return result
    except (sqlite3.Error, ValidationError, RuntimeError, ValueError):
        raise Unavailable(
            "GitHub credential bindings cannot be read. Check deployment configuration."
        ) from None


def resolve(name: str, conn: sqlite3.Connection | None = None) -> Binding:
    binding = load(conn).get(name)
    if binding is None:
        raise ValueError(
            "GitHub credential binding is unavailable. Choose a configured binding."
        )
    return binding


def choices() -> list[Choice]:
    return [
        Choice(
            name=name,
            host=binding.host,
            available=bool(os.environ.get(binding.token_env)),
        )
        for name, binding in sorted(load().items())
    ]


def import_binding(conn: sqlite3.Connection, host: str, token_env: str) -> str:
    binding = Binding(host=host, token_env=token_env)
    digest = hashlib.sha256(binding.model_dump_json().encode()).hexdigest()[:12]
    name = "imported-" + digest
    conn.execute(
        "INSERT OR IGNORE INTO github_credential_bindings VALUES (?, ?)",
        (name, binding.model_dump_json()),
    )
    return name
