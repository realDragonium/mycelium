"""Versioned documentation profiles and editable loop instructions.

Profiles retain the existing guideline-set rows. Their revision includes retired
slots, so retiring and restoring a text never makes a stale editor current again.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import ai_prompts, audiences, auth, errors, guidelines, prompt_store, store
from .audiences import Audience

INSTRUCTIONS = ai_prompts.ACTIONS
#: What happens to a profile's document once a statement it cites changes:
#: nothing until someone revises it, an update item in the profile's plan, or
#: a revision that runs by itself (see `mycelium.document_maintenance`).
Maintenance = Literal["manual", "propose", "auto-revise"]
#: What happens once enough statements the profile's audience may see are
#: cited by none of its documents: nothing until someone plans, a plan whose
#: items wait for approval, or a plan whose items start their runs.
Planning = Literal["off", "propose", "write"]
#: Who decides the profile's proposed plan items: a person, or an AI reviewer
#: other than the planner that approves or dismisses each with a reason (see
#: `mycelium.documentation_plan_review`).
PlanReview = Literal["person", "ai"]
#: Who may deliver the profile's documents: people in the web app, or also
#: agents over MCP (`deliver_document`).
Delivery = Literal["people", "agents"]


class Conflict(errors.Conflict):
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
            raise ValueError(
                "guidance, exposure, audience, maintenance, planning, "
                "plan_review, delivery and destinations are reserved names."
            )
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
    #: The audience id this profile writes for; None writes for the default
    #: internal audience.
    audience: str | None = None
    maintenance: Maintenance = "manual"
    planning: Planning = "off"
    plan_review: PlanReview = "person"
    delivery: Delivery = "people"
    #: The destinations the profile's documents may be published to; empty
    #: allows every configured destination.
    destinations: tuple[str, ...] = ()
    templates: tuple[Template, ...] = ()

    @model_validator(mode="after")
    def unique_templates(self) -> ProfileBody:
        if len({item.name for item in self.templates}) != len(self.templates):
            raise ValueError("Template names must be unique.")
        return self

    @field_validator("destinations")
    @classmethod
    def valid_destinations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(
            not item.strip() or item != item.strip() or "\n" in item for item in value
        ):
            raise ValueError("Destination names must be unique and nonblank.")
        return value


class SaveProfile(ProfileBody):
    revision: str


class RevisionRequest(Model):
    revision: str


class Profile(ProfileBody):
    name: str
    #: The audience runs of this profile write for, after the default applies;
    #: None when the chosen audience was retired.
    effective_audience: str | None
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
    audience: PromptRevision | None = None
    maintenance: Maintenance = "manual"
    planning: Planning = "off"
    plan_review: PlanReview = "person"
    delivery: Delivery = "people"
    destinations: tuple[str, ...] = ()

    def may_publish_to(self, destination: str) -> bool:
        return not self.destinations or destination in self.destinations


@dataclass(frozen=True)
class CatalogueSnapshot:
    profiles: tuple[ProfileSnapshot, ...]
    audiences: tuple[Audience, ...] = ()

    def audience(self, set_name: str) -> Audience | None:
        """The audience a profile writes for; None when the profile does not
        exist or its chosen audience was retired."""
        profile = next((item for item in self.profiles if item.name == set_name), None)
        if profile is None:
            return None
        return audiences.resolve(
            profile.audience.text.strip() if profile.audience else None,
            self.audiences,
        )

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
                slots.get(guidelines.AUDIENCE_SLOT),
                maintenance(slots.get(guidelines.MAINTENANCE_SLOT)),
                planning(slots.get(guidelines.PLANNING_SLOT)),
                plan_review(slots.get(guidelines.PLAN_REVIEW_SLOT)),
                delivery(slots.get(guidelines.DELIVERY_SLOT)),
                destinations(slots.get(guidelines.DESTINATIONS_SLOT)),
            )
            for name, slots in sorted(grouped.items())
        ),
        audiences.live(db),
    )


def maintenance(slot: PromptRevision | str | None) -> Maintenance:
    """The stored policy; an unknown text maintains by hand rather than
    guessing at automation."""
    text = (slot.text if isinstance(slot, PromptRevision) else slot or "").strip()
    return cast(Maintenance, text) if text in get_args(Maintenance) else "manual"


def planning(slot: PromptRevision | str | None) -> Planning:
    """The stored policy; an unknown text plans by hand."""
    text = (slot.text if isinstance(slot, PromptRevision) else slot or "").strip()
    return cast(Planning, text) if text in get_args(Planning) else "off"


def plan_review(slot: PromptRevision | str | None) -> PlanReview:
    """The stored reviewer; an unknown text leaves review to a person."""
    text = (slot.text if isinstance(slot, PromptRevision) else slot or "").strip()
    return cast(PlanReview, text) if text in get_args(PlanReview) else "person"


def delivery(slot: PromptRevision | str | None) -> Delivery:
    """The stored policy; an unknown text lets only people deliver."""
    text = (slot.text if isinstance(slot, PromptRevision) else slot or "").strip()
    return cast(Delivery, text) if text in get_args(Delivery) else "people"


def destinations(slot: PromptRevision | str | None) -> tuple[str, ...]:
    """The stored destination names, one per line."""
    text = slot.text if isinstance(slot, PromptRevision) else slot or ""
    return tuple(line.strip() for line in text.splitlines() if line.strip())


#: Policy slots and the texts each may hold.
_POLICIES: dict[str, tuple[str, object]] = {
    guidelines.MAINTENANCE_SLOT: ("Maintenance", Maintenance),
    guidelines.PLANNING_SLOT: ("Planning", Planning),
    guidelines.PLAN_REVIEW_SLOT: ("Plan review", PlanReview),
    guidelines.DELIVERY_SLOT: ("Delivery", Delivery),
}


def _revision(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return ""
    return hashlib.sha256(
        "\n".join(
            f"{row['name']}:{row['id']}:{row['version']}" for row in rows
        ).encode()
    ).hexdigest()


def _profile(
    name: str, rows: list[sqlite3.Row], live_audiences: tuple[Audience, ...]
) -> Profile:
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
    chosen = live.get(guidelines.AUDIENCE_SLOT, "").strip() or None
    effective = audiences.resolve(chosen, live_audiences)
    if not live.get("exposure", "").strip():
        issues.append(
            "No disclosure rules are configured; exposure is checked only "
            "against the audience's description."
            if effective is not None
            else "No disclosure rules are configured; exposure will be unchecked."
        )
    if effective is None:
        issues.append(
            "The audience this profile writes for was retired; choose another."
            if chosen
            else "No internal audience exists to write for."
        )
    return Profile(
        name=name,
        revision=_revision(rows),
        guidance=live.get("guidance", ""),
        exposure=live.get("exposure", ""),
        audience=chosen,
        maintenance=maintenance(live.get(guidelines.MAINTENANCE_SLOT)),
        planning=planning(live.get(guidelines.PLANNING_SLOT)),
        plan_review=plan_review(live.get(guidelines.PLAN_REVIEW_SLOT)),
        delivery=delivery(live.get(guidelines.DELIVERY_SLOT)),
        destinations=destinations(live.get(guidelines.DESTINATIONS_SLOT)),
        effective_audience=effective.id if effective else None,
        templates=tuple(templates),
        retired=bool(rows) and not live,
        ready=bool(templates)
        and effective is not None
        and not any("needs repair" in issue for issue in issues),
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
        name,
        [row for row in _rows(db) if str(row["name"]).partition("/")[0] == name],
        audiences.live(db),
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
    live_audiences = audiences.live(conn)
    return Profiles(
        profiles=tuple(
            _profile(name, rows, live_audiences)
            for name, rows in sorted(grouped.items())
        ),
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


def _texts(request: SaveProfile) -> dict[str, str]:
    """The slots a save stores, before its policy slots."""
    desired = {item.name: item.text for item in request.templates}
    if request.guidance.strip():
        desired["guidance"] = request.guidance
    if request.exposure.strip():
        desired["exposure"] = request.exposure
    if request.audience is not None:
        desired[guidelines.AUDIENCE_SLOT] = request.audience
    if request.destinations:
        desired[guidelines.DESTINATIONS_SLOT] = "\n".join(request.destinations)
    return desired


def save(name: str, request: SaveProfile, principal: auth.Principal) -> Profile:
    _authorize(principal)
    _part(name)
    desired = _texts(request)
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
        if request.audience is not None and request.audience not in {
            item.id for item in audiences.live(conn)
        }:
            raise ValueError(f"Audience {request.audience!r} is not live.")
        if live and any(
            live.get(slot) != desired.get(slot)
            for slot in (guidelines.AUDIENCE_SLOT, guidelines.DESTINATIONS_SLOT)
        ):
            # The audience decides what a profile's documents may disclose,
            # and the destinations who gets to read them.
            _authorize(principal, "admin")
        # Going back to manual rewrites the slot rather than retiring it, so
        # it needs no more than the writer who turned automation on.
        for slot, value, default in (
            (guidelines.MAINTENANCE_SLOT, request.maintenance, "manual"),
            (guidelines.PLANNING_SLOT, request.planning, "off"),
            (guidelines.PLAN_REVIEW_SLOT, request.plan_review, "person"),
            (guidelines.DELIVERY_SLOT, request.delivery, "people"),
        ):
            if value != default or slot in live:
                desired[slot] = value
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
    if type == audiences.TYPE:
        raise ValueError("Edit audiences in Settings, not as prompt texts.")
    if type == guidelines.TYPE:
        profile, separator, slot = name.partition("/")
        if not separator:
            raise ValueError(
                "Guideline names must use profile/template, profile/guidance, "
                "profile/exposure, profile/audience, profile/maintenance, "
                "profile/planning, profile/plan_review, profile/delivery or "
                "profile/destinations."
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
    if _is_admin_slot(type, name):
        _authorize(principal, "admin")
    if _is_audience_slot(type, name):
        if text.strip() not in {item.id for item in audiences.live()}:
            raise ValueError(f"Audience {text.strip()!r} is not live.")
    policy = _POLICIES.get(name.partition("/")[2]) if type == guidelines.TYPE else None
    if policy is not None and text.strip() not in get_args(policy[1]):
        raise ValueError(
            f"{policy[0]} must be one of: " + ", ".join(get_args(policy[1])) + "."
        )
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
            profile, _, _slot = name.partition("/")
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


def _is_audience_slot(type: str, name: str) -> bool:
    return (
        type == guidelines.TYPE and name.partition("/")[2] == guidelines.AUDIENCE_SLOT
    )


def _is_admin_slot(type: str, name: str) -> bool:
    return type == guidelines.TYPE and name.partition("/")[2] in {
        guidelines.AUDIENCE_SLOT,
        guidelines.DESTINATIONS_SLOT,
    }


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


class Starter(Model):
    name: str
    title: str
    description: str
    audience: str | None
    guidance: str
    exposure: str
    templates: tuple[Template, ...]


def starters() -> tuple[Starter, ...]:
    """The packaged starters an editor may create a profile from or reset
    one to; a starter whose files cannot be read is left out."""
    offered: list[Starter] = []
    for starter in guidelines.STARTERS:
        try:
            texts = {
                slot: path.read_text(encoding="utf-8")
                for slot, path in starter.sources().items()
            }
        except OSError:
            continue
        offered.append(
            Starter(
                name=starter.name,
                title=starter.title,
                description=starter.description,
                audience=starter.audience,
                guidance=texts["guidance"],
                exposure=texts["exposure"],
                templates=tuple(
                    Template(name=name, text=texts[name]) for name in starter.templates
                ),
            )
        )
    return tuple(offered)
