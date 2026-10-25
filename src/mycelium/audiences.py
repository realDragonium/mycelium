"""Documentation audiences: who a writing profile writes for.

An audience is instance configuration, stored as versioned `audience` rows in
the prompt store, so every edit keeps history and a retirement is a tombstone.
The row name is the audience's immutable id; the text holds its name, whether
it is internal or external, the description the labeller and the writer
read, and the audiences it includes. Statement labels (in the substrate)
reference the id.

An audience that includes another may see everything that one may see, so a
statement is visible to an audience when its label grants the audience or
any audience it includes, transitively. The labeller then only names the
most restricted audiences a statement fits.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import auth, errors, prompt_store, store

TYPE = "audience"
Scope = Literal["internal", "external"]
#: The audience a profile without a chosen audience writes for, while it lives.
DEFAULT_ID = "internal-technical"


class Conflict(errors.Conflict):
    pass


class AudienceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    scope: Scope
    description: str = Field(min_length=1, max_length=4000)
    #: Audiences this one may see everything of.
    includes: list[str] = Field(default_factory=list, max_length=50)


@dataclass(frozen=True)
class Audience:
    id: str
    name: str
    scope: Scope
    description: str
    version: int
    includes: tuple[str, ...] = ()
    #: Every live audience it includes, directly or through another; filled
    #: by `live`.
    reach: tuple[str, ...] = ()

    @property
    def internal(self) -> bool:
        return self.scope == "internal"

    @property
    def sees(self) -> frozenset[str]:
        """The audience ids whose grants this audience may see."""
        return frozenset((self.id, *self.reach))


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
            includes=[
                "internal-non-technical",
                "external-technical",
                "external-non-technical",
            ],
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
            includes=["external-non-technical"],
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
            includes=["external-non-technical"],
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
                "infrastructure, integration mechanics, internal processes, "
                "unreleased work or the roadmap, security internals, "
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
        includes=tuple(body.includes),
    )


def _reach(audience_id: str, includes: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    found: list[str] = []
    stack = list(includes.get(audience_id, ()))
    while stack:
        item = stack.pop()
        if item in found or item == audience_id or item not in includes:
            continue
        found.append(item)
        stack.extend(includes[item])
    return tuple(sorted(found))


def live(conn: sqlite3.Connection | None = None) -> tuple[Audience, ...]:
    """Every live, well-formed audience, internal first, then by name."""
    db = conn if conn is not None else prompt_store.connection()
    parsed = [
        item
        for item in (_parse(row) for row in prompt_store.list_current(db, TYPE))
        if item is not None
    ]
    includes = {item.id: item.includes for item in parsed}
    return tuple(
        sorted(
            (replace(item, reach=_reach(item.id, includes)) for item in parsed),
            key=lambda item: (not item.internal, item.name.casefold()),
        )
    )


def graph(current: tuple[Audience, ...] | None = None) -> store.audience_labels.Graph:
    """The live includes as the label store reads them."""
    found = current if current is not None else live()
    return store.audience_labels.Graph(
        sees={item.id: item.sees for item in found},
        internal=frozenset(item.id for item in found if item.internal),
    )


def sees_of(
    audience_id: str, current: tuple[Audience, ...] | None = None
) -> frozenset[str]:
    """The audience ids whose grants `audience_id` may see, by the live
    includes; only itself when it is not live or no prompts store is open."""
    if current is None and not prompt_store.is_configured():
        return frozenset((audience_id,))
    found = next(
        (
            item
            for item in (current if current is not None else live())
            if item.id == audience_id
        ),
        None,
    )
    return found.sees if found is not None else frozenset((audience_id,))


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
            _seed_includes(conn)
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


def _seed_includes(conn: sqlite3.Connection) -> None:
    """Give the seeded audiences their includes once, on instances seeded
    before audiences could include each other. A text without the field was
    written before then; a saved one always carries it."""
    current = {item.id for item in live(conn)}
    for audience_id, seeded in SEEDS:
        history = prompt_store.history(conn, TYPE, audience_id)
        if not history or history[0]["deleted"] or '"includes"' in history[0]["text"]:
            continue
        body = AudienceBody.model_validate_json(history[0]["text"])
        body.includes = [item for item in seeded.includes if item in current]
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
    includes: list[str]
    retired: bool
    default: bool
    profiles: list[str]
    visible_statements: int
    unlabelled_statements: int
    #: AI grants to this audience waiting for a curator.
    pending_statements: int


class AudiencesView(BaseModel):
    audiences: list[AudienceView]
    can_configure: bool
    statements: int
    unlabelled: int
    pending: int


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
    from .grant_confirmation import pending_counts

    pending = pending_counts(substrate)
    views: list[AudienceView] = []
    for audience in current:
        views.append(
            AudienceView(
                id=audience.id,
                name=audience.name,
                scope=audience.scope,
                description=audience.description,
                version=audience.version,
                includes=list(audience.includes),
                retired=False,
                default=fallback is not None and audience.id == fallback.id,
                profiles=sorted(
                    name
                    for name, choice in chosen.items()
                    if (choice or (fallback.id if fallback else None)) == audience.id
                ),
                visible_statements=len(
                    store.visible_statement_ids(
                        substrate, audience.sees, audience.internal
                    )
                ),
                unlabelled_statements=unlabelled,
                pending_statements=pending.get(audience.id, 0),
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
                includes=list(previous.includes),
                retired=True,
                default=False,
                profiles=[],
                visible_statements=0,
                unlabelled_statements=unlabelled,
                pending_statements=0,
            )
        )
    return AudiencesView(
        audiences=views,
        can_configure=principal.is_admin,
        statements=total,
        unlabelled=unlabelled,
        pending=sum(pending.get(item.id, 0) for item in current),
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
        _check_includes(conn, audience_id, request)
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
        _check_includes(conn, audience_id, body)
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


def _check_includes(
    conn: sqlite3.Connection, audience_id: str, body: AudienceBody
) -> None:
    """Includes name other live audiences, an external audience never
    includes an internal one, and no audience includes itself through others."""
    others = {item.id: item for item in live(conn) if item.id != audience_id}
    unknown = sorted(set(body.includes) - others.keys())
    if unknown:
        raise ValueError(
            "Unknown or retired audiences to include: " + ", ".join(unknown)
        )
    scopes = {key: item.scope for key, item in others.items()}
    scopes[audience_id] = body.scope
    includes = {key: item.includes for key, item in others.items()}
    includes[audience_id] = tuple(body.includes)
    for key, included in includes.items():
        if scopes[key] == "external" and any(
            scopes[item] == "internal" for item in included if item in scopes
        ):
            raise ValueError(
                "An external audience cannot include an internal one: it would "
                "see internal statements."
            )
    if any(audience_id in _reach(item, includes) for item in body.includes):
        raise ValueError("These includes would make the audience include itself.")
