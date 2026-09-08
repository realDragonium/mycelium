"""Repository-scoped App connections; backups restore them disconnected."""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import github_app, prompt_store, store

SCHEMA = """
CREATE TABLE IF NOT EXISTS github_app_connections (
    name TEXT PRIMARY KEY,
    body_json TEXT NOT NULL
);
"""
PREFIX = "github-app:"


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    app_id: int = Field(gt=0)
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    repo: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    host: Literal["github.com"] = "github.com"
    enabled: bool = True

    @property
    def name(self) -> str:
        return f"{PREFIX}{self.app_id}:{self.installation_id}:{self.repository_id}"

    def require_target(self, owner: str, repo: str) -> None:
        if (self.owner.lower(), self.repo.lower()) != (owner.lower(), repo.lower()):
            raise github_app.GitHubError(
                "The connection belongs to a different repository. Connect the intended repository separately."
            )


def load(conn: sqlite3.Connection | None = None) -> dict[str, Connection]:
    if conn is None and not prompt_store.is_configured():
        return {}
    db = conn if conn is not None else prompt_store.connection()
    result = {}
    for row in db.execute("SELECT name, body_json FROM github_app_connections"):
        connection = Connection.model_validate_json(row["body_json"])
        if connection.name != row["name"]:
            raise github_app.GitHubError("A saved GitHub connection is invalid.")
        result[connection.name] = connection
    return result


def resolve(name: str, conn: sqlite3.Connection | None = None) -> Connection:
    connection = load(conn).get(name)
    if connection is None:
        raise github_app.GitHubError(
            "The saved GitHub connection is unavailable. Connect GitHub again."
        )
    return connection


def save(connection: Connection) -> None:
    db = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(db):
        previous = load(db).get(connection.name)
        if previous is not None:
            previous.require_target(connection.owner, connection.repo)
        db.execute(
            "INSERT INTO github_app_connections VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET body_json=excluded.body_json",
            (connection.name, connection.model_dump_json()),
        )


def disconnect(name: str) -> None:
    db = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(db):
        connection = resolve(name, db).model_copy(update={"enabled": False})
        db.execute(
            "UPDATE github_app_connections SET body_json=? WHERE name=?",
            (connection.model_dump_json(), name),
        )


def access_token(name: str, owner: str, repo: str) -> str:
    connection = resolve(name)
    connection.require_target(owner, repo)
    if not connection.enabled:
        raise github_app.GitHubError(
            "This GitHub repository is disconnected. An administrator must reconnect it before publishing."
        )
    config = github_app.AppConfig.load()
    if config.app_id != connection.app_id:
        raise github_app.GitHubError(
            "This connection belongs to another GitHub App. Restore its App configuration before publishing."
        )
    with github_app.client() as transport:
        api = github_app.GitHubClient(transport, config)
        token = api.installation_token(
            connection.installation_id, connection.repository_id
        )
        api.verify_repository(token, connection.repository_id, owner, repo)
        return token
