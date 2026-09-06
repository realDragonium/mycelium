"""Validated, independently revisioned product settings in the prompts database."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import TYPE_CHECKING, Annotated, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from . import auth, github_credentials, guidelines, prompt_store, store
from .model_settings import Conflict, Unavailable

if TYPE_CHECKING:
    from .docgen.destinations import DestinationConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS product_settings (
    section TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK(revision > 0),
    body_json TEXT NOT NULL
);
"""
MIGRATION = "product-settings-v1"


class SettingsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class RequestLimits(SettingsModel):
    max_tokens: int = Field(default=8000, gt=0)
    max_retries: int = Field(default=4, ge=0)
    request_timeout_s: float = Field(default=120.0, gt=0)


class LoopLimits(RequestLimits):
    op_cap: int = Field(default=150, gt=0)
    wall_clock_s: float = Field(default=1200.0, gt=0)
    thinking: bool = True


class AskSettings(LoopLimits):
    kind: Literal["ask"] = "ask"
    op_cap: int = Field(default=25, gt=0)
    wall_clock_s: float = Field(default=90.0, gt=0)
    request_timeout_s: float = Field(default=75.0, gt=0)
    thinking: bool = False
    cache: bool = True
    recon_k: int = Field(default=8, gt=0)


class IngestSettings(LoopLimits):
    kind: Literal["ingest"] = "ingest"
    op_cap: int = Field(default=50, gt=0)
    wall_clock_s: float = Field(default=120.0, gt=0)
    request_timeout_s: float = Field(default=90.0, gt=0)
    max_input_chars: int = Field(default=20000, gt=0)


class ResearchSettings(LoopLimits):
    kind: Literal["research"] = "research"
    max_topic_chars: int = Field(default=2000, gt=0)


class DocgenSettings(LoopLimits):
    kind: Literal["docgen"] = "docgen"
    wall_clock_s: float = Field(default=900.0, gt=0)
    max_tokens: int = Field(default=12000, gt=0)
    max_prompt_chars: int = Field(default=2000, gt=0)
    recon_k: int = Field(default=30, gt=0)


class ReviewSettings(RequestLimits):
    kind: Literal["draft_review"] = "draft_review"
    max_tokens: int = Field(default=6000, gt=0)
    max_retries: int = Field(default=0, ge=0)
    request_timeout_s: float = Field(default=90.0, gt=0)


class ConcurrencySettings(SettingsModel):
    kind: Literal["concurrency"] = "concurrency"
    model_loops: int = Field(default=2, gt=0)
    documentation_runs: int = Field(default=2, gt=0)
    research_runs: int = Field(default=2, gt=0)


class SourceSettings(SettingsModel):
    name: str = Field(min_length=1, max_length=200)
    owner: str = Field(min_length=1, max_length=200)
    repo: str = Field(min_length=1, max_length=200)
    ref: str | None = Field(default=None, max_length=200)
    binding: str | None = Field(default=None, min_length=1, max_length=200)
    host: str = Field(default="github.com", max_length=200)

    @model_validator(mode="after")
    def validate_coordinates(self) -> SourceSettings:
        from .research.sources import (
            _HOST_RE,
            _OWNER_REPO_RE,
            _REF_RE,
            SourceError,
            _validate,
        )

        try:
            _validate(self.name, "owner", self.owner, _OWNER_REPO_RE)
            _validate(self.name, "repo", self.repo, _OWNER_REPO_RE)
            _validate(self.name, "host", self.host, _HOST_RE)
            if self.ref:
                _validate(self.name, "ref", self.ref, _REF_RE)
        except SourceError:
            raise ValueError(
                "Source repository, reference, or host is invalid."
            ) from None
        return self


class DestinationSettings(SettingsModel):
    name: str = Field(min_length=1, max_length=200)
    path_template: str = Field(min_length=1, max_length=1000)
    owner: str = Field(min_length=1, max_length=200)
    repo: str = Field(min_length=1, max_length=200)
    base_branch: str = Field(min_length=1, max_length=200)
    binding: str = Field(min_length=1, max_length=200)

    def destination(self, conn: sqlite3.Connection | None = None) -> DestinationConfig:
        from .docgen.destinations import DestinationConfig

        binding = github_credentials.resolve(self.binding, conn)
        return DestinationConfig(
            self.name,
            "github",
            self.path_template,
            {
                **self.model_dump(exclude={"name", "path_template", "binding"}),
                **binding.model_dump(),
            },
        )

    @model_validator(mode="after")
    def validate_coordinates(self) -> DestinationSettings:
        from .docgen.destinations import (
            DestinationConfig,
            DestinationError,
            _validate_path_template,
        )
        from .docgen.github_destination import parse_config

        try:
            _validate_path_template(self.name, self.path_template)
            parse_config(
                DestinationConfig(
                    self.name,
                    "github",
                    self.path_template,
                    {
                        "owner": self.owner,
                        "repo": self.repo,
                        "base_branch": self.base_branch,
                        "token_env": "BINDING",
                    },
                )
            )
        except DestinationError:
            raise ValueError(
                "Destination repository, branch, or path template is invalid."
            ) from None
        return self


class DocumentationSettings(SettingsModel):
    kind: Literal["documentation"] = "documentation"
    guideline_set: str = Field(default="kb-authoring", min_length=1, max_length=200)
    destinations: tuple[DestinationSettings, ...] = Field(default=(), strict=False)

    @model_validator(mode="after")
    def unique_names(self) -> DocumentationSettings:
        if len({item.name for item in self.destinations}) != len(self.destinations):
            raise ValueError("Destination names must be unique.")
        return self


class SourcesSettings(SettingsModel):
    kind: Literal["sources"] = "sources"
    sources: tuple[SourceSettings, ...] = Field(default=(), strict=False)

    @model_validator(mode="after")
    def unique_names(self) -> SourcesSettings:
        if len({item.name for item in self.sources}) != len(self.sources):
            raise ValueError("Source names must be unique.")
        return self


Section = Literal[
    "ask",
    "ingest",
    "research",
    "docgen",
    "draft_review",
    "concurrency",
    "documentation",
    "sources",
]
Body = Annotated[
    AskSettings
    | IngestSettings
    | ResearchSettings
    | DocgenSettings
    | ReviewSettings
    | ConcurrencySettings
    | DocumentationSettings
    | SourcesSettings,
    Field(discriminator="kind"),
]
BODY = TypeAdapter(Body)
DEFAULTS: tuple[Body, ...] = (
    AskSettings(),
    IngestSettings(),
    ResearchSettings(),
    DocgenSettings(),
    ReviewSettings(),
    ConcurrencySettings(),
    DocumentationSettings(),
    SourcesSettings(),
)


class Snapshot(SettingsModel):
    revision: int = Field(ge=0)
    settings: Body
    configuration_error: str | None = None


class SaveSettings(SettingsModel):
    revision: int = Field(ge=0)
    settings: Body


class SettingsView(SettingsModel):
    can_configure: bool
    sections: list[Snapshot]
    github_bindings: list[github_credentials.Choice]
    github_configuration_error: str | None = None
    guideline_sets: list[str]


T = TypeVar(
    "T",
    bound=AskSettings
    | IngestSettings
    | ResearchSettings
    | DocgenSettings
    | ReviewSettings
    | ConcurrencySettings
    | DocumentationSettings
    | SourcesSettings,
)


def get(model: type[T], *, conn: sqlite3.Connection | None = None) -> T:
    default = model()
    if not prompt_store.is_configured() and conn is None:
        return default
    db = conn if conn is not None else prompt_store.connection()
    try:
        section = default.kind
        row = db.execute(
            "SELECT body_json FROM product_settings WHERE section = ?", (section,)
        ).fetchone()
        if row is None:
            return default
        loaded = BODY.validate_json(row["body_json"])
        if not isinstance(loaded, model):
            raise ValueError("Product settings section mismatch.")
        return loaded
    except (sqlite3.Error, ValidationError, RuntimeError, ValueError):
        raise Unavailable(
            "Saved product settings cannot be read; the action is disabled."
        ) from None


def editable(default: Body, conn: sqlite3.Connection) -> Snapshot:
    row = conn.execute(
        "SELECT revision, body_json FROM product_settings WHERE section = ?",
        (default.kind,),
    ).fetchone()
    try:
        body = BODY.validate_json(row["body_json"]) if row else default
        if body.kind != default.kind:
            raise ValueError("section mismatch")
        return Snapshot(revision=row["revision"] if row else 0, settings=body)
    except (ValidationError, RuntimeError, ValueError):
        return Snapshot(
            revision=row["revision"] if row else 0,
            settings=default,
            configuration_error="Saved settings are invalid. Save valid settings to enable this action.",
        )


def view(principal: auth.Principal) -> SettingsView:
    binding_error = None
    try:
        bindings = github_credentials.choices()
    except Unavailable as exc:
        bindings = []
        binding_error = str(exc)
    try:
        db = prompt_store.connection()
        return SettingsView(
            can_configure=principal.is_admin,
            sections=[editable(default, db) for default in DEFAULTS],
            github_bindings=bindings,
            github_configuration_error=binding_error,
            guideline_sets=sorted(guidelines.catalogue(db)),
        )
    except (sqlite3.Error, RuntimeError):
        raise Unavailable("Instance product configuration cannot be read.") from None


def save(request: SaveSettings, principal: auth.Principal) -> Snapshot:
    if not principal.is_admin:
        raise auth.RoleRequired("admin role required")
    validate_secrets(request.settings)
    db = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(db):
        if isinstance(
            request.settings, DocumentationSettings
        ) and request.settings.guideline_set not in guidelines.catalogue(db):
            raise ValueError("Choose an existing guideline set for documentation.")
        current = editable(request.settings, db)
        if current.revision != request.revision:
            raise Conflict("Settings changed; reload before saving.")
        if (
            current.settings == request.settings
            and current.revision
            and not current.configuration_error
        ):
            return current
        db.execute(
            "INSERT INTO product_settings VALUES (?, ?, ?) ON CONFLICT(section) DO UPDATE SET revision = excluded.revision, body_json = excluded.body_json",
            (
                request.settings.kind,
                current.revision + 1,
                request.settings.model_dump_json(),
            ),
        )
        result = Snapshot(revision=current.revision + 1, settings=request.settings)
    if isinstance(request.settings, ConcurrencySettings):
        from . import server

        server._model_loop_budget().changed()
    return result


def validate_secrets(settings: Body, *, conn: sqlite3.Connection | None = None) -> None:
    entries = (
        settings.sources
        if isinstance(settings, SourcesSettings)
        else settings.destinations
        if isinstance(settings, DocumentationSettings)
        else ()
    )
    if not entries:
        return
    bindings = github_credentials.load(conn)
    for item in entries:
        if item.binding and item.binding not in bindings:
            raise ValueError(
                "GitHub credential binding is unavailable. Choose a configured binding."
            )
    credentials = [
        os.environ.get(binding.token_env, "") for binding in bindings.values()
    ]
    if any(secret and secret in settings.model_dump_json() for secret in credentials):
        raise ValueError(
            "Configuration contains a credential. Use credential variable names only."
        )


def _legacy(default: Body, conn: sqlite3.Connection) -> Body:
    if isinstance(default, DocumentationSettings):
        from .docgen.destinations import load_destinations
        from .docgen.github_destination import parse_config

        destinations = []
        for destination in load_destinations(os.environ).values():
            github = parse_config(destination)
            destinations.append(
                DestinationSettings(
                    name=destination.name,
                    path_template=destination.path_template,
                    owner=github.owner,
                    repo=github.repo,
                    base_branch=github.base_branch,
                    binding=github_credentials.import_binding(
                        conn, github.host, github.token_env
                    ),
                )
            )
        return DocumentationSettings(
            guideline_set=os.environ.get("MYCELIUM_DOCGEN_GUIDELINE_SET")
            or default.guideline_set,
            destinations=tuple(destinations),
        )
    if isinstance(default, SourcesSettings):
        from dataclasses import asdict

        from .research.sources import load_sources

        return SourcesSettings(
            sources=tuple(
                SourceSettings.model_validate(
                    {
                        **{
                            key: value
                            for key, value in asdict(source).items()
                            if key != "token_env"
                        },
                        "binding": github_credentials.import_binding(
                            conn, source.host, source.token_env
                        )
                        if source.token_env
                        else None,
                    }
                )
                for source in load_sources(os.environ).values()
            )
        )
    values = default.model_dump()
    concurrency_names = {
        "model_loops": "MYCELIUM_MODEL_LOOP_MAX_CONCURRENT",
        "documentation_runs": "MYCELIUM_DOCGEN_MAX_ACTIVE",
        "research_runs": "MYCELIUM_RESEARCH_MAX_ACTIVE",
    }
    for field, value in values.items():
        if field == "kind":
            continue
        name = (
            concurrency_names[field]
            if isinstance(default, ConcurrencySettings)
            else f"MYCELIUM_{default.kind.upper()}_{field.upper()}"
        )
        raw = os.environ.get(name)
        if raw:
            if isinstance(value, bool):
                values[field] = (
                    raw.lower() == "on"
                    if default.kind == "ask" and field == "thinking"
                    else raw.lower() != "off"
                )
            elif isinstance(value, int):
                values[field] = int(raw)
            elif isinstance(value, float):
                values[field] = float(raw)
    return BODY.validate_python(values)


def initialize(conn: sqlite3.Connection, *, import_environment: bool) -> None:
    if conn.execute(
        "SELECT 1 FROM instance_settings_migrations WHERE name = ?", (MIGRATION,)
    ).fetchone():
        return
    import_environment = (
        import_environment
        and not conn.execute(
            "SELECT 1 FROM instance_settings_migrations WHERE name = 'environment-import-disabled'"
        ).fetchone()
    )
    for default in DEFAULTS:
        try:
            settings = _legacy(default, conn) if import_environment else default
            validate_secrets(settings, conn=conn)
            body = settings.model_dump_json()
        except (ValueError, RuntimeError):
            # Invalid legacy configuration stays disabled without archiving arbitrary
            # environment text, which may contain a mistakenly pasted credential.
            body = json.dumps(
                {"kind": default.kind, "invalid_legacy_configuration": True}
            )
        conn.execute(
            "INSERT OR IGNORE INTO product_settings VALUES (?, 1, ?)",
            (default.kind, body),
        )
    conn.execute(
        "INSERT INTO instance_settings_migrations(name) VALUES (?)", (MIGRATION,)
    )


class Archive(SettingsModel):
    sections: list[Snapshot]
    github_bindings: dict[str, github_credentials.Binding]

    @model_validator(mode="after")
    def validate_sections(self) -> Archive:
        kinds = [item.settings.kind for item in self.sections]
        if len(set(kinds)) != len(kinds):
            raise ValueError("Archive repeats a product settings section.")
        if any(item.revision < 1 or item.configuration_error for item in self.sections):
            raise ValueError("Archive contains invalid product settings.")
        return self


def archive(conn: sqlite3.Connection) -> Archive:
    sections = []
    for row in conn.execute(
        "SELECT section, revision, body_json FROM product_settings ORDER BY section"
    ):
        settings = BODY.validate_json(row["body_json"])
        if settings.kind != row["section"]:
            raise ValueError(
                "Saved product settings section does not match its content."
            )
        sections.append(Snapshot(revision=row["revision"], settings=settings))
    bindings = {
        row["name"]: github_credentials.Binding.model_validate_json(row["body_json"])
        for row in conn.execute(
            "SELECT name, body_json FROM github_credential_bindings"
        )
    }
    return Archive(sections=sections, github_bindings=bindings)


def restore(conn: sqlite3.Connection, archived: Archive) -> None:
    for name, binding in archived.github_bindings.items():
        conn.execute(
            "INSERT INTO github_credential_bindings VALUES (?, ?)",
            (name, binding.model_dump_json()),
        )
    for section in archived.sections:
        conn.execute(
            "INSERT INTO product_settings VALUES (?, ?, ?)",
            (
                section.settings.kind,
                section.revision,
                section.settings.model_dump_json(),
            ),
        )
