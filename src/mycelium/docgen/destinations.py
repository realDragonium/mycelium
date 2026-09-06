"""Configured delivery destinations for generated documents.

A destination is a reviewable place a generated document can be submitted to.
Administrators configure repositories, branches, and path templates in saved
settings. Explicit environment mappings are accepted by the legacy import parser.

The generic configuration carries destination-specific settings without
interpreting them. Each implementation validates and uses its own settings.
"""

from __future__ import annotations

import json
import sqlite3
import string
import threading
from dataclasses import dataclass
from typing import Mapping, Protocol, cast

from .schema import CurrentDocument


class DestinationError(RuntimeError):
    """Raised for config or delivery failures. Messages are ALWAYS pre-scrubbed."""


_ALLOWED_FIELDS = frozenset({"slug", "guideline_set", "document_type"})
_CONFIG_FIELDS = frozenset({"type", "path_template", "config"})


@dataclass(frozen=True)
class DestinationConfig:
    name: str
    type: str
    path_template: str
    settings: object


@dataclass(frozen=True)
class DeliveryDocument:
    id: str
    slug: str
    title: str
    body: str
    guideline_set: str
    document_type: str
    statement_ids: tuple[str, ...]
    delivered_path: str | None = None
    delivered_content_revision: str | None = None
    revision_source_content_revision: str | None = None


@dataclass(frozen=True)
class Delivery:
    destination: str
    path: str
    reference: str
    content_revision: str

    def serialize(self) -> dict[str, str]:
        return {
            "destination": self.destination,
            "path": self.path,
            "reference": self.reference,
            "content_revision": self.content_revision,
        }


class DestinationBackend(Protocol):
    def parse_config(self, destination: DestinationConfig) -> object: ...

    def validate_config_secrets(
        self, destination: DestinationConfig, credentials: list[str]
    ) -> None: ...

    def coordinates(self, destination: DestinationConfig) -> dict[str, str]: ...

    def deliver(
        self,
        destination: DestinationConfig,
        document: DeliveryDocument,
        env: Mapping[str, str] | None = None,
    ) -> Delivery: ...

    def read(
        self,
        destination: DestinationConfig,
        path: str,
        document_id: str,
        slug: str,
        env: Mapping[str, str] | None = None,
    ) -> CurrentDocument: ...


def load_destinations(
    env: Mapping[str, str] | None = None,
) -> dict[str, DestinationConfig]:
    if env is None:
        from .. import product_settings

        settings = product_settings.get(product_settings.DocumentationSettings)
        return {item.name: item.destination() for item in settings.destinations}
    e = env
    raw = e.get("MYCELIUM_DOC_DESTINATIONS")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DestinationError(
            f"MYCELIUM_DOC_DESTINATIONS is not valid JSON: {exc.msg}"
        ) from None
    if not isinstance(parsed, dict):
        raise DestinationError(
            "MYCELIUM_DOC_DESTINATIONS must be a JSON object keyed by destination name"
        )

    secrets = _configured_credentials(parsed, e)
    configured: dict[str, DestinationConfig] = {}
    for raw_name, entry in parsed.items():
        name = str(raw_name)
        try:
            config = _load_destination(name, entry)
            _backend(config).validate_config_secrets(config, secrets)
        except DestinationError as exc:
            raise DestinationError(_scrub(str(exc), secrets)) from None
        configured[name] = config
    return configured


def _configured_credentials(
    parsed: dict[object, object], env: Mapping[str, str]
) -> list[str]:
    credentials: list[str] = []
    for entry in parsed.values():
        if not isinstance(entry, dict):
            continue
        settings = entry.get("config")
        if not isinstance(settings, dict):
            continue
        token_env = settings.get("token_env")
        if isinstance(token_env, str) and token_env in env:
            credentials.append(env[token_env])
    return credentials


def _load_destination(name: str, entry: object) -> DestinationConfig:
    if not isinstance(entry, dict):
        raise DestinationError(f"destination {name!r} must be a JSON object")
    if set(entry) - _CONFIG_FIELDS:
        raise DestinationError(f"destination {name!r} contains an unknown field")

    destination_type = _optional_config_string(name, entry, "type", "github")
    path_template = _required_string(name, entry, "path_template")
    if "config" not in entry:
        raise DestinationError(
            f"destination {name!r} is missing required field 'config'"
        )
    _validate_path_template(name, path_template)
    config = DestinationConfig(
        name=name,
        type=destination_type,
        path_template=path_template,
        settings=entry["config"],
    )
    _backend(config).parse_config(config)
    return config


def get_destination(
    name: str, env: Mapping[str, str] | None = None
) -> DestinationConfig:
    configured = load_destinations(env)
    try:
        return configured[name]
    except KeyError:
        names = ", ".join(sorted(configured)) or "(none)"
        raise DestinationError(
            f"unknown destination; configured destinations: {names}"
        ) from None


def render_path(config: DestinationConfig, document: DeliveryDocument) -> str:
    try:
        path = config.path_template.format(
            slug=document.slug,
            guideline_set=document.guideline_set,
            document_type=document.document_type,
        )
    except (KeyError, ValueError) as exc:
        raise DestinationError(
            f"destination {config.name!r} could not render its path template: {exc}"
        ) from None
    _validate_rendered_path(config.name, path)
    return path


def deliver_document(
    config: DestinationConfig,
    document: DeliveryDocument,
    env: Mapping[str, str] | None = None,
) -> Delivery:
    implementation = _backend(config)
    return implementation.deliver(config, document, env)


def destination_coordinates(config: DestinationConfig) -> dict[str, str]:
    return _backend(config).coordinates(config)


def read_document(
    config: DestinationConfig,
    path: str,
    document_id: str,
    slug: str,
    env: Mapping[str, str] | None = None,
) -> CurrentDocument:
    return _backend(config).read(config, path, document_id, slug, env)


def _backend(config: DestinationConfig) -> DestinationBackend:
    if config.type == "github":
        from . import github_destination

        return cast(DestinationBackend, github_destination)
    raise DestinationError(f"destination {config.name!r} has an unsupported type")


def _validate_path_template(name: str, template: str) -> None:
    _validate_rendered_path(name, template)
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise DestinationError(
            f"destination {name!r} has an invalid 'path_template' value: {exc}"
        ) from None
    for _, field, format_spec, conversion in parts:
        if field is not None and field not in _ALLOWED_FIELDS:
            raise DestinationError(
                f"destination {name!r} has an invalid 'path_template' value "
                "(unknown field)"
            )
        if format_spec or conversion:
            raise DestinationError(
                f"destination {name!r} has an invalid 'path_template' value "
                "(format specifications and conversions are not supported)"
            )


def _validate_rendered_path(name: str, path: str) -> None:
    if (
        not path.strip()
        or path.startswith(("/", "-"))
        or ".." in path
        or "\\" in path
        or any(ord(character) < 32 for character in path)
    ):
        raise DestinationError(
            f"destination {name!r} has an invalid 'path_template' value "
            "(must stay below the destination root, with no leading '-', '..', "
            "backslashes, or control characters)"
        )


def _required_string(name: str, entry: dict, field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DestinationError(
            f"destination {name!r} is missing required field {field!r}"
        )
    return value


def _optional_config_string(name: str, entry: dict, field: str, default: str) -> str:
    value = entry.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise DestinationError(f"destination {name!r} has an invalid {field!r} value")
    return value


def _scrub(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def target_identity(config: DestinationConfig) -> str:
    return json.dumps(destination_coordinates(config), sort_keys=True)


def require_recorded_target(config: DestinationConfig, recorded: str | None) -> None:
    if recorded != target_identity(config):
        raise DestinationError(
            "The document destination has changed. Use a new destination name to deliver to a different repository or branch."
        )


def bind_legacy_deliveries(conn: sqlite3.Connection) -> None:
    """Pin older delivery records once; unresolved targets remain disabled."""
    rows = conn.execute(
        "SELECT id, delivery_destination FROM generated_documents WHERE delivery_destination IS NOT NULL AND delivery_target IS NULL"
    ).fetchall()
    if not rows:
        return
    try:
        configured = load_destinations()
    except (ValueError, RuntimeError):
        configured = {}
    with conn:
        for row in rows:
            destination = configured.get(row["delivery_destination"])
            conn.execute(
                "UPDATE generated_documents SET delivery_target = ? WHERE id = ?",
                (target_identity(destination) if destination else "{}", row["id"]),
            )


_publication_locks: dict[str, threading.Lock] = {}
_publication_locks_guard = threading.Lock()


def publication_lock(document_id: str) -> threading.Lock:
    with _publication_locks_guard:
        if document_id not in _publication_locks:
            _publication_locks[document_id] = threading.Lock()
        return _publication_locks[document_id]


def publishing_destination(
    row: sqlite3.Row, name: str
) -> tuple[DestinationConfig, str]:
    """Resolve a new target or reuse its recorded coordinates and approved binding."""
    from pydantic import BaseModel, ConfigDict, ValidationError

    from .. import github_credentials, product_settings

    class Coordinates(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        host: str
        owner: str
        repo: str
        base_branch: str

    recorded_name = row["delivery_destination"]
    if recorded_name is not None and recorded_name != name:
        raise DestinationError(
            "This document already has a publishing destination. Use its recorded destination."
        )
    binding_name = row["delivery_binding"]
    if binding_name is not None and recorded_name is not None:
        try:
            coordinates = Coordinates.model_validate_json(
                row["delivery_target"] or "{}"
            )
            binding = github_credentials.resolve(str(binding_name))
            if binding.host != coordinates.host:
                raise DestinationError(
                    "The recorded publishing credential is no longer authorized for this host."
                )
            config = DestinationConfig(
                name=str(recorded_name),
                type="github",
                path_template=str(row["delivery_path"]),
                settings={**coordinates.model_dump(), "token_env": binding.token_env},
            )
            _backend(config).parse_config(config)
            return config, str(binding_name)
        except (ValidationError, ValueError):
            raise DestinationError(
                "The recorded publishing target or credential binding is unavailable."
            ) from None
    settings = product_settings.get(product_settings.DocumentationSettings)
    selected = next((item for item in settings.destinations if item.name == name), None)
    if selected is None:
        raise DestinationError("The publishing destination is unavailable.")
    configured = selected.destination()
    if recorded_name is not None:
        require_recorded_target(configured, row["delivery_target"])
    return configured, selected.binding
