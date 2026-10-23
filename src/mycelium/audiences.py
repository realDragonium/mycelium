"""Documentation audiences: who a writing profile writes for.

An audience is instance configuration, stored as versioned `audience` rows in
the prompt store, so every edit keeps history and a retirement is a tombstone.
The row name is the audience's immutable id; the text holds its name, whether
it is internal or external, and the description the labeller and the writer
read. Statement labels (in the substrate) reference the id.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import auth, prompt_store, store

TYPE = "audience"
Scope = Literal["internal", "external"]
#: The audience a profile without a chosen audience writes for, while it lives.
DEFAULT_ID = "internal-technical"


class Conflict(ValueError):
    pass


class AudienceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    scope: Scope
    description: str = Field(min_length=1, max_length=4000)


@dataclass(frozen=True)
class Audience:
    id: str
    name: str
    scope: Scope
    description: str
    version: int

    @property
    def internal(self) -> bool:
        return self.scope == "internal"


SEEDS: tuple[tuple[str, AudienceBody], ...] = (
    (
        "internal-technical",
        AudienceBody(
            name="Internal technical",
            scope="internal",
            description=(
                "Engineers, support engineers and operators inside the company "
                "who build and run the product. They need the full technical "
                "picture: architecture, internal components, configuration, "
                "failure modes, limits and workarounds. Nothing is withheld "
                "from them: every statement may be shown to this audience."
            ),
        ),
    ),
    (
        "internal-non-technical",
        AudienceBody(
            name="Internal non-technical",
            scope="internal",
            description=(
                "Colleagues in sales, customer success, marketing and "
                "management. They need what the product does and for whom, its "
                "options, the limits that affect customers and how internal "
                "processes run, in plain language. They do not need code, "
                "internal component names, data models or infrastructure detail."
            ),
        ),
    ),
    (
        "external-technical",
        AudienceBody(
            name="External technical",
            scope="external",
            description=(
                "Developers and administrators at customer or partner "
                "organisations who integrate with the product. They need what "
                "an integrator needs: APIs, webhooks, single sign-on, "
                "provisioning, data exports, authentication, rate limits and "
                "the settings they control. They must not get internal "
                "architecture, internal service or component names, "
                "infrastructure, internal processes, unreleased work, security "
                "internals, or anything about other customers."
            ),
        ),
    ),
    (
        "external-non-technical",
        AudienceBody(
            name="External non-technical",
            scope="external",
            description=(
                "End users and customer stakeholders who use the product "
                "through its interface. They need visible product behaviour: "
                "what features do, how to use them, which settings exist and "
                "what they change. They must not get technical internals, "
                "integration mechanics, internal processes, the roadmap, "
                "commercial terms, or anything about other customers."
            ),
        ),
    ),
)


def _parse(row: sqlite3.Row) -> Audience | None:
    try:
        body = AudienceBody.model_validate_json(row["text"])
    except ValidationError:
        return None
    return Audience(
        id=str(row["name"]),
        name=body.name,
        scope=body.scope,
        description=body.description,
        version=int(row["version"]),
    )


def live(conn: sqlite3.Connection | None = None) -> tuple[Audience, ...]:
    """Every live, well-formed audience, internal first, then by name."""
    db = conn if conn is not None else prompt_store.connection()
    parsed = (_parse(row) for row in prompt_store.list_current(db, TYPE))
    return tuple(
        sorted(
            (item for item in parsed if item is not None),
            key=lambda item: (not item.internal, item.name.casefold()),
        )
    )


def default(audiences: tuple[Audience, ...]) -> Audience | None:
    """The most permissive internal audience: the seeded internal technical
    one while it lives, else the first internal audience."""
    return next((item for item in audiences if item.id == DEFAULT_ID), None) or next(
        (item for item in audiences if item.internal), None
    )


def resolve(chosen: str | None, audiences: tuple[Audience, ...]) -> Audience | None:
    """The audience a profile writes for. A chosen audience that was retired
    resolves to nothing, so the run refuses instead of widening silently."""
    if chosen is None:
        return default(audiences)
    return next((item for item in audiences if item.id == chosen), None)


def seed(conn: sqlite3.Connection) -> None:
    """Seed the starter audiences once; any history, even retired, wins."""
    with store.write_lock(), prompt_store._writing(conn):
        if conn.execute(
            "SELECT 1 FROM prompt_texts WHERE type = ? LIMIT 1", (TYPE,)
        ).fetchone():
            return
        for audience_id, body in SEEDS:
            prompt_store._append(
                conn,
                type=TYPE,
                name=audience_id,
                text=body.model_dump_json(),
                deleted=0,
                created_by="seed",
            )


# --- views and edits ---------------------------------------------------------


class AudienceView(BaseModel):
    id: str
    name: str
    scope: Scope
    description: str
    version: int
    retired: bool
    default: bool
    profiles: list[str]
    visible_statements: int
    unlabelled_statements: int


class AudiencesView(BaseModel):
    audiences: list[AudienceView]
    can_configure: bool
    statements: int
    unlabelled: int


class SaveAudience(AudienceBody):
    revision: int = Field(ge=0)


class CreateAudience(AudienceBody):
    id: str | None = Field(default=None, max_length=64)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value):
            raise ValueError("Audience ids use lowercase letters, digits and dashes.")
        return value


class RetireAudience(BaseModel):
    revision: int = Field(ge=1)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:64] or "audience"


def _actor(principal: auth.Principal) -> str | None:
    from .documentation_profiles import _actor

    return _actor(principal)


def _require_admin(principal: auth.Principal) -> None:
    if not principal.is_admin:
        raise auth.RoleRequired("admin role required")


def profile_audiences(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Each live profile mapped to the audience id it chose, if any."""
    from .documentation_profiles import capture

    return {
        profile.name: profile.audience.text.strip() if profile.audience else None
        for profile in capture(conn).profiles
    }


def view(principal: auth.Principal, substrate: sqlite3.Connection) -> AudiencesView:
    conn = prompt_store.connection()
    current = live(conn)
    fallback = default(current)
    chosen = profile_audiences(conn)
    rows = {
        str(row["name"]): row
        for row in conn.execute(
            "SELECT * FROM prompt_texts p WHERE type = ? AND version = "
            "(SELECT MAX(version) FROM prompt_texts WHERE type = p.type AND name = p.name)",
            (TYPE,),
        )
    }
    total = int(substrate.execute("SELECT COUNT(*) FROM statements").fetchone()[0])
    unlabelled = int(
        substrate.execute(
            "SELECT COUNT(*) FROM statements s WHERE NOT EXISTS "
            "(SELECT 1 FROM statement_audience_labels l WHERE l.statement_id = s.id)"
        ).fetchone()[0]
    )
    views: list[AudienceView] = []
    for audience in current:
        views.append(
            AudienceView(
                id=audience.id,
                name=audience.name,
                scope=audience.scope,
                description=audience.description,
                version=audience.version,
                retired=False,
                default=fallback is not None and audience.id == fallback.id,
                profiles=sorted(
                    name
                    for name, choice in chosen.items()
                    if (choice or (fallback.id if fallback else None)) == audience.id
                ),
                visible_statements=len(
                    store.visible_statement_ids(
                        substrate, audience.id, audience.internal
                    )
                ),
                unlabelled_statements=unlabelled,
            )
        )
    for audience_id, row in sorted(rows.items()):
        if not row["deleted"]:
            continue
        history = prompt_store.history(conn, TYPE, audience_id)
        previous = next(
            (parsed for item in history if (parsed := _parse(item)) is not None), None
        )
        if previous is None:
            continue
        views.append(
            AudienceView(
                id=audience_id,
                name=previous.name,
                scope=previous.scope,
                description=previous.description,
                version=int(row["version"]),
                retired=True,
                default=False,
                profiles=[],
                visible_statements=0,
                unlabelled_statements=unlabelled,
            )
        )
    return AudiencesView(
        audiences=views,
        can_configure=principal.is_admin,
        statements=total,
        unlabelled=unlabelled,
    )


def create(request: CreateAudience, principal: auth.Principal) -> Audience:
    _require_admin(principal)
    conn = prompt_store.connection()
    audience_id = request.id or _slug(request.name)
    with store.write_lock(), prompt_store._writing(conn):
        if prompt_store.history(conn, TYPE, audience_id):
            raise Conflict(
                f"An audience with id {audience_id!r} exists or existed; "
                "choose another id or restore it."
            )
        _check_unique_name(conn, request.name, audience_id)
        row = prompt_store._append(
            conn,
            type=TYPE,
            name=audience_id,
            text=AudienceBody.model_validate(
                request.model_dump(exclude={"id"})
            ).model_dump_json(),
            deleted=0,
            created_by=_actor(principal),
        )
    parsed = _parse(row)
    assert parsed is not None
    return parsed


def save(
    audience_id: str, request: SaveAudience, principal: auth.Principal
) -> Audience:
    """Edit an audience, or restore a retired one at the same id."""
    _require_admin(principal)
    conn = prompt_store.connection()
    body = AudienceBody.model_validate(request.model_dump(exclude={"revision"}))
    with store.write_lock(), prompt_store._writing(conn):
        history = prompt_store.history(conn, TYPE, audience_id)
        if not history:
            raise ValueError(f"Audience {audience_id!r} does not exist.")
        if int(history[0]["version"]) != request.revision:
            raise Conflict("This audience changed. Reload before saving.")
        current = _parse(history[0]) if not history[0]["deleted"] else None
        if current is not None and current.internal and body.scope == "external":
            _protect_last_internal(conn, audience_id)
        _check_unique_name(conn, body.name, audience_id)
        if current is not None and history[0]["text"] == body.model_dump_json():
            return current
        row = prompt_store._append(
            conn,
            type=TYPE,
            name=audience_id,
            text=body.model_dump_json(),
            deleted=0,
            created_by=_actor(principal),
        )
    parsed = _parse(row)
    assert parsed is not None
    return parsed


def retire(
    audience_id: str, request: RetireAudience, principal: auth.Principal
) -> None:
    _require_admin(principal)
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        history = prompt_store.history(conn, TYPE, audience_id)
        if not history or history[0]["deleted"]:
            raise ValueError(f"Audience {audience_id!r} is not live.")
        if int(history[0]["version"]) != request.revision:
            raise Conflict("This audience changed. Reload before retiring.")
        users = sorted(
            name
            for name, choice in profile_audiences(conn).items()
            if choice == audience_id
        )
        if users:
            raise ValueError(
                "Profiles still write for this audience: "
                + ", ".join(users)
                + ". Choose another audience for them first."
            )
        _protect_last_internal(conn, audience_id)
        prompt_store._append(
            conn,
            type=TYPE,
            name=audience_id,
            text="",
            deleted=1,
            created_by=_actor(principal),
        )


def _protect_last_internal(conn: sqlite3.Connection, audience_id: str) -> None:
    if not any(item.internal and item.id != audience_id for item in live(conn)):
        raise ValueError(
            "Keep at least one internal audience: profiles without a chosen "
            "audience write for it."
        )


def _check_unique_name(conn: sqlite3.Connection, name: str, audience_id: str) -> None:
    if any(
        item.name.casefold() == name.casefold() and item.id != audience_id
        for item in live(conn)
    ):
        raise Conflict(f"Another audience is already called {name!r}.")
