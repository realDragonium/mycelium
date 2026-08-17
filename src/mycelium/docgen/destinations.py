"""Configured delivery destinations for generated documents.

A destination is a reviewable place a generated document can be submitted to.
Destinations are configured through `MYCELIUM_DOC_DESTINATIONS`, a JSON object
keyed by destination name:

    {"knowledge-base": {"type": "github",
                        "path_template": "docs/kb/{slug}.md",
                        "config": {...}}}

The generic configuration carries destination-specific settings without
interpreting them. Each implementation validates and uses its own settings.
"""

from __future__ import annotations

import json
import os
import string
from dataclasses import dataclass
from types import ModuleType
from typing import Mapping


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


def load_destinations(
    env: Mapping[str, str] | None = None,
) -> dict[str, DestinationConfig]:
    e = os.environ if env is None else env
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

    configured: dict[str, DestinationConfig] = {}
    for raw_name, entry in parsed.items():
        name = str(raw_name)
        configured[name] = _load_destination(name, entry)
    return configured


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
            f"unknown destination {name!r}; configured destinations: {names}"
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


def _backend(config: DestinationConfig) -> ModuleType:
    if config.type == "github":
        from . import github_destination

        return github_destination
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
