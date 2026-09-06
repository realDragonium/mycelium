"""Versioned documentation profiles and editable loop instructions.

Profiles retain the existing guideline-set rows. Their revision includes retired
slots, so retiring and restoring a text never makes a stale editor current again.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import auth, guidelines, prompt_store, store

INSTRUCTIONS = ("ingest", "research", "docgen")


class Conflict(ValueError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _part(value: str) -> str:
    if not value.strip() or value != value.strip() or "/" in value:
        raise ValueError(
            "Names must be nonblank, without slashes or surrounding spaces."
        )
    return value


class Template(Model):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = _part(value)
        if value in guidelines.NON_TYPE_SLOTS:
            raise ValueError("guidance and exposure are reserved names.")
        return value

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Template text is required.")
        return value


class ProfileBody(Model):
    guidance: str = ""
    exposure: str = ""
    templates: tuple[Template, ...] = ()

    @model_validator(mode="after")
    def unique_templates(self) -> ProfileBody:
        if len({item.name for item in self.templates}) != len(self.templates):
            raise ValueError("Template names must be unique.")
        return self


class SaveProfile(ProfileBody):
    revision: str


class RevisionRequest(Model):
    revision: str


class Profile(ProfileBody):
    name: str
    revision: str
    retired: bool
    ready: bool
    issues: tuple[str, ...]
    retired_templates: tuple[str, ...]


class Profiles(Model):
    profiles: tuple[Profile, ...]
    can_write: bool
    can_retire: bool
    default_profile: str | None


class TextVersion(Model):
    id: str
    type: str
    name: str
    text: str
    version: int
    deleted: bool
    created_at: str
    created_by: str | None


class SaveText(Model):
    type: str
    name: str
    text: str
    revision: int = Field(ge=0)


class RestoreText(Model):
    type: str
    name: str
    version: int = Field(gt=0)
    revision: int = Field(ge=0)


@dataclass(frozen=True)
class PromptReference:
    id: str
    version: int


@dataclass(frozen=True)
class PromptRevision:
    id: str
    version: int
    text: str


@dataclass(frozen=True)
class TemplateSnapshot:
    name: str
    prompt: PromptRevision


@dataclass(frozen=True)
class ProfileSnapshot:
    name: str
    guidance: PromptRevision | None
    exposure: PromptRevision | None
    templates: tuple[TemplateSnapshot, ...]


@dataclass(frozen=True)
class CatalogueSnapshot:
    profiles: tuple[ProfileSnapshot, ...]

    def catalogue(self) -> dict[str, list[str]]:
        return {
            profile.name: [template.name for template in profile.templates]
            for profile in self.profiles
        }

    def _selected(
        self, set_name: str, document_type: str
    ) -> tuple[PromptRevision | None, PromptRevision | None, PromptRevision | None]:
        profile = next((item for item in self.profiles if item.name == set_name), None)
        if profile is None:
            return None, None, None
        template = next(
            (item.prompt for item in profile.templates if item.name == document_type),
            None,
        )
        return profile.guidance, profile.exposure, template

    def texts(
        self, set_name: str, document_type: str
    ) -> tuple[str | None, str | None, str | None]:
        guidance, exposure, template = self._selected(set_name, document_type)
        return (
            guidance.text if guidance else None,
            exposure.text if exposure else None,
            template.text if template else None,
        )

    def references(
        self, set_name: str, document_type: str
    ) -> dict[str, PromptReference]:
        return {
            slot: PromptReference(prompt.id, prompt.version)
            for slot, prompt in zip(
                ("guidance", "exposure", document_type),
                self._selected(set_name, document_type),
                strict=True,
            )
            if prompt is not None
        }


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM prompt_texts p WHERE type = ? AND version = "
            "(SELECT MAX(version) FROM prompt_texts WHERE type = p.type AND name = p.name) "
            "ORDER BY name",
            (guidelines.TYPE,),
        ).fetchall()
    )


def capture(conn: sqlite3.Connection | None = None) -> CatalogueSnapshot:
    """Capture all guideline texts and versions in one SQLite read snapshot."""
    db = conn if conn is not None else prompt_store.connection()
    grouped: dict[str, dict[str, PromptRevision]] = {}
    for row in _rows(db):
        if row["deleted"]:
            continue
        name, separator, slot = str(row["name"]).partition("/")
        if not separator or not name or not slot:
            continue
        grouped.setdefault(name, {})[slot] = PromptRevision(
            str(row["id"]), int(row["version"]), str(row["text"])
        )
    return CatalogueSnapshot(
        tuple(
            ProfileSnapshot(
                name,
                slots.get("guidance"),
                slots.get("exposure"),
                tuple(
                    TemplateSnapshot(slot, prompt)
                    for slot, prompt in sorted(slots.items())
                    if slot not in guidelines.NON_TYPE_SLOTS
                ),
            )
            for name, slots in sorted(grouped.items())
        )
    )


def _revision(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return ""
    return hashlib.sha256(
        "\n".join(
            f"{row['name']}:{row['id']}:{row['version']}" for row in rows
        ).encode()
    ).hexdigest()


def _profile(name: str, rows: list[sqlite3.Row]) -> Profile:
    live = {
        str(row["name"]).partition("/")[2]: str(row["text"])
        for row in rows
        if not row["deleted"]
    }
    templates: list[Template] = []
    issues: list[str] = []
    for slot, text in live.items():
        if slot in guidelines.NON_TYPE_SLOTS:
            continue
        try:
            templates.append(Template(name=slot, text=text))
        except ValueError:
            issues.append(
                f"The stored template name or text for '{slot}' needs repair."
            )
    if not templates:
        issues.append(
            "Add a template before generating documentation with this profile."
        )
    if not live.get("guidance", "").strip():
        issues.append("No writing guidance is configured.")
    if not live.get("exposure", "").strip():
        issues.append("No disclosure rules are configured; exposure will be unchecked.")
    return Profile(
        name=name,
        revision=_revision(rows),
        guidance=live.get("guidance", ""),
        exposure=live.get("exposure", ""),
        templates=tuple(templates),
        retired=bool(rows) and not live,
        ready=bool(templates) and not any("needs repair" in issue for issue in issues),
        issues=tuple(issues),
        retired_templates=tuple(
            str(row["name"]).partition("/")[2]
            for row in rows
            if row["deleted"]
            and str(row["name"]).partition("/")[2] not in guidelines.NON_TYPE_SLOTS
        ),
    )


def read(name: str, conn: sqlite3.Connection | None = None) -> Profile:
    _part(name)
    db = conn if conn is not None else prompt_store.connection()
    return _profile(
        name, [row for row in _rows(db) if str(row["name"]).partition("/")[0] == name]
    )


def _default(conn: sqlite3.Connection) -> str | None:
    from . import product_settings

    row = conn.execute(
        "SELECT body_json FROM product_settings WHERE section = 'documentation'"
    ).fetchone()
    if row is None:
        return product_settings.DocumentationSettings().guideline_set
    return product_settings.DocumentationSettings.model_validate_json(
        row["body_json"]
    ).guideline_set


def view(principal: auth.Principal) -> Profiles:
    conn = prompt_store.connection()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in _rows(conn):
        grouped.setdefault(str(row["name"]).partition("/")[0], []).append(row)
    return Profiles(
        profiles=tuple(_profile(name, rows) for name, rows in sorted(grouped.items())),
        can_write=auth.principal_has_real_role(principal, "writer"),
        can_retire=principal.is_admin,
        default_profile=_default(conn),
    )


def _actor(principal: auth.Principal) -> str | None:
    # Local stdio has no authenticated actor, matching existing prompt history.
    return (
        None
        if principal.synthetic and auth.current_principal.get() is None
        else principal.id
    )


def _authorize(principal: auth.Principal, role: auth.Role = "writer") -> None:
    if not auth.principal_has_real_role(principal, role):
        raise auth.RoleRequired(f"{role} role required")


def _protect_default(
    conn: sqlite3.Connection, name: str, remaining: dict[str, str]
) -> None:
    if _default(conn) == name and not any(
        slot not in guidelines.NON_TYPE_SLOTS for slot in remaining
    ):
        raise ValueError(
            "Choose another default profile before retiring this profile or its last template."
        )


def save(name: str, request: SaveProfile, principal: auth.Principal) -> Profile:
    _authorize(principal)
    _part(name)
    desired = {item.name: item.text for item in request.templates}
    if request.guidance.strip():
        desired["guidance"] = request.guidance
    if request.exposure.strip():
        desired["exposure"] = request.exposure
    if not desired:
        raise ValueError(
            "Add guidance or a template to create a profile; use Retire to remove one."
        )
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        rows = [
            row for row in _rows(conn) if str(row["name"]).partition("/")[0] == name
        ]
        if _revision(rows) != request.revision:
            raise Conflict("This profile changed. Reload before saving.")
        live = {
            str(row["name"]).partition("/")[2]: str(row["text"])
            for row in rows
            if not row["deleted"]
        }
        if live.keys() - desired.keys():
            _authorize(principal, "admin")
            _protect_default(conn, name, desired)
        for row in rows:
            if not row["deleted"] and str(row["name"]).partition("/")[2] not in desired:
                prompt_store._append(
                    conn,
                    type=guidelines.TYPE,
                    name=str(row["name"]),
                    text="",
                    deleted=1,
                    created_by=_actor(principal),
                )
        for slot, text in sorted(desired.items()):
            if live.get(slot) == text:
                continue
            prompt_store._append(
                conn,
                type=guidelines.TYPE,
                name=guidelines.row_name(slot, name),
                text=text,
                deleted=0,
                created_by=_actor(principal),
            )
        return read(name, conn)


def retire(name: str, revision: str, principal: auth.Principal) -> Profile:
    _authorize(principal, "admin")
    _part(name)
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        current = read(name, conn)
        if current.revision != revision:
            raise Conflict("This profile changed. Reload before retiring.")
        _protect_default(conn, name, {})
        for row in _rows(conn):
            if str(row["name"]).partition("/")[0] == name and not row["deleted"]:
                prompt_store._append(
                    conn,
                    type=guidelines.TYPE,
                    name=row["name"],
                    text="",
                    deleted=1,
                    created_by=_actor(principal),
                )
        return read(name, conn)


def validate_key(type: str, name: str) -> tuple[str, str]:
    type, name = prompt_store._key(type, name)
    if type == guidelines.TYPE:
        profile, separator, slot = name.partition("/")
        if not separator:
            raise ValueError(
                "Guideline names must use profile/template, profile/guidance or profile/exposure."
            )
        _part(profile)
        _part(slot)
    return type, name


def text_version(row: sqlite3.Row) -> TextVersion:
    return TextVersion(
        id=str(row["id"]),
        type=str(row["type"]),
        name=str(row["name"]),
        text=str(row["text"]),
        version=int(row["version"]),
        deleted=bool(row["deleted"]),
        created_at=str(row["created_at"]),
        created_by=str(row["created_by"]) if row["created_by"] is not None else None,
    )


def save_text(
    type: str,
    name: str,
    text: str,
    principal: auth.Principal,
    *,
    revision: int | None = None,
) -> TextVersion:
    _authorize(principal)
    type, name = validate_key(type, name)
    if not text.strip():
        raise ValueError("Text is required.")
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        history = prompt_store.history(conn, type, name)
        current = history[0] if history else None
        if revision is not None and revision != (
            int(current["version"]) if current else 0
        ):
            raise Conflict("This text changed. Reload before saving.")
        if current is not None and not current["deleted"] and current["text"] == text:
            return text_version(current)
        return text_version(
            prompt_store._append(
                conn,
                type=type,
                name=name,
                text=text,
                deleted=0,
                created_by=_actor(principal),
            )
        )


def retire_text(
    type: str,
    name: str,
    principal: auth.Principal,
    *,
    expected_version: int | None = None,
) -> bool:
    _authorize(principal, "admin")
    type, name = validate_key(type, name)
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        history = prompt_store.history(conn, type, name)
        current = history[0] if history else None
        if expected_version is not None and expected_version != (
            int(current["version"]) if current else 0
        ):
            raise Conflict("This text changed. Reload before retiring.")
        if current is None or current["deleted"]:
            return False
        if type == guidelines.TYPE:
            profile, _, slot = name.partition("/")
            remaining = {
                str(row["name"]).partition("/")[2]: str(row["text"])
                for row in _rows(conn)
                if not row["deleted"]
                and str(row["name"]).partition("/")[0] == profile
                and row["name"] != name
            }
            _protect_default(conn, profile, remaining)
        prompt_store._append(
            conn, type=type, name=name, text="", deleted=1, created_by=_actor(principal)
        )
        return True


def restore_text(request: RestoreText, principal: auth.Principal) -> TextVersion:
    _authorize(principal)
    type, name = validate_key(request.type, request.name)
    conn = prompt_store.connection()
    # Historical rows are immutable; the CAS in save_text protects the current head.
    row = conn.execute(
        "SELECT * FROM prompt_texts WHERE type = ? AND name = ? AND version = ?",
        (type, name, request.version),
    ).fetchone()
    if row is None or row["deleted"]:
        raise ValueError("Choose a saved text version to restore.")
    return save_text(type, name, str(row["text"]), principal, revision=request.revision)


def editable_key(type: str, name: str) -> None:
    if type != guidelines.TYPE and (type != "doctrine" or name not in INSTRUCTIONS):
        raise ValueError(
            "This editor supports documentation profiles and the existing loop instructions."
        )


def seed_starters(conn: sqlite3.Connection) -> None:
    """Bootstrap one user-owned starter set; history, even retired, takes precedence."""
    with store.write_lock(), prompt_store._writing(conn):
        if conn.execute(
            "SELECT 1 FROM prompt_texts WHERE type = ? LIMIT 1", (guidelines.TYPE,)
        ).fetchone():
            return
        for name, text in guidelines.read_rows().items():
            prompt_store._append(
                conn,
                type=guidelines.TYPE,
                name=name,
                text=text,
                deleted=0,
                created_by="seed",
            )
