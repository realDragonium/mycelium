"""Validated, independently revisioned product settings in the prompts database."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import TYPE_CHECKING, Annotated, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from . import (
    auth,
    github_connections,
    github_credentials,
    guidelines,
    model_settings,
    prompt_store,
    store,
)
from .ai import Provider
from .github_connections import Connection as GitHubConnection
from .model_settings import Conflict, Unavailable

logger = logging.getLogger(__name__)

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
    #: max_tokens per model turn, including thinking where supported.
    max_tokens: int = Field(default=8000, gt=0)
    #: Provider retries cover 429/5xx/connection with exponential backoff;
    #: this raises the provider's default 2 for the slow-substrate environment.
    max_retries: int = Field(default=4, ge=0)
    #: Per-model-call timeout, seconds. Kept under the whole-run wall clock so
    #: a single hung call can't blow the whole budget.
    request_timeout_s: float = Field(default=120.0, gt=0)


class LoopLimits(RequestLimits):
    #: Hard ceiling on substrate operations per run, including opening reads.
    op_cap: int = Field(default=150, gt=0)
    #: Whole-run wall-clock budget, seconds.
    wall_clock_s: float = Field(default=1200.0, gt=0)
    #: Adaptive thinking in the loop, where the model supports it.
    thinking: bool = True


class AskSettings(LoopLimits):
    kind: Literal["ask"] = "ask"
    #: Recon counts toward the substrate operation cap.
    op_cap: int = Field(default=25, gt=0)
    #: On exhaustion, return a low-confidence partial answer rather than throw.
    #: Transports without keepalive can drop calls that exceed their idle
    #: window; callers with a tight window can select the quick depth ceilings.
    wall_clock_s: float = Field(default=90.0, gt=0)
    request_timeout_s: float = Field(default=75.0, gt=0)
    #: Adaptive thinking in the retrieval loop. Default OFF: with thinking on,
    #: each retrieval turn spent ~2x as long thinking and the run still blew the
    #: wall-clock budget; off, the same question finishes cleanly and faster.
    #: Haiku does not support adaptive thinking. Enable in AI settings on a
    #: model that supports it.
    thinking: bool = False
    #: The loop re-sends a growing conversation every turn. Prompt caching
    #: reuses the static prefix (tools + system) and prior conversation on
    #: turns 2..N, reducing latency and cost. Can be disabled for A/B runs.
    cache: bool = True
    #: Per-part limit for the opening recon search, which decomposes the question.
    recon_k: int = Field(default=8, gt=0)


class IngestSettings(LoopLimits):
    kind: Literal["ingest"] = "ingest"
    #: Adaptive thinking plus a full emit_draft outgrew 8000 in most drafts.
    max_tokens: int = Field(default=32000, gt=0)
    #: Vocab fetch and every reconcile read count toward this cap. Ingest
    #: reconciles per candidate, so it needs more reads than ask.
    op_cap: int = Field(default=50, gt=0)
    #: Whole run, final emit included: reading stops early enough to leave it
    #: a third. Exhaustion forces an emit (or NothingToIngest) rather than
    #: throwing. The former 120 s left only one or two reading turns.
    wall_clock_s: float = Field(default=300.0, gt=0)
    request_timeout_s: float = Field(default=90.0, gt=0)
    #: Longer input is head-truncated and a gap recorded, never silently lost.
    max_input_chars: int = Field(default=20000, gt=0)


class DocgenSettings(LoopLimits):
    kind: Literal["docgen"] = "docgen"
    #: A run holds a shared model-loop slot for its whole life, so this also
    #: bounds how long it can keep that slot from ask and ingest.
    wall_clock_s: float = Field(default=900.0, gt=0)
    #: A document body is the largest single output of these loops, and
    #: adaptive thinking shares the budget. Both together outgrew 12000.
    max_tokens: int = Field(default=32000, gt=0)
    #: Enforced at the door by request_documentation, which refuses rather
    #: than truncates: silently dropping the tail of a person's prompt would
    #: generate the wrong document instead of an error they can act on.
    max_prompt_chars: int = Field(default=2000, gt=0)
    #: Per-part limit of the opening decomposed search_statements map. Wider
    #: than ask's recon because a document covers a topic, not a question.
    recon_k: int = Field(default=30, gt=0)


class ReviewSettings(RequestLimits):
    kind: Literal["draft_review"] = "draft_review"
    max_tokens: int = Field(default=6000, gt=0)
    max_retries: int = Field(default=0, ge=0)
    request_timeout_s: float = Field(default=90.0, gt=0)
    #: Most tokens one draft's review may use, estimated before any model
    #: call from its parts' context and max_tokens; a larger draft is
    #: refused. 0 sets no cap.
    max_draft_tokens: int = Field(default=300_000, ge=0)
    #: Further AI answers after the reviewer asks again, before its
    #: questions wait for a person.
    answer_retries: int = Field(default=2, ge=0)
    #: Automatic reviews again after refreshed alias suggestions, before
    #: the draft waits for a person to start its review again.
    refresh_reviews: int = Field(default=2, ge=0)


class AliasDiscoverySettings(RequestLimits):
    kind: Literal["alias_discovery"] = "alias_discovery"
    max_tokens: int = Field(default=6000, gt=0)
    max_retries: int = Field(default=0, ge=0)
    request_timeout_s: float = Field(default=90.0, gt=0)
    max_input_chars: int = Field(default=100000, gt=0)


class AudienceLabellingSettings(RequestLimits):
    kind: Literal["audience_labelling"] = "audience_labelling"
    #: Label new and changed statements in the background. A backfill runs
    #: either way, since an admin starts it.
    automatic: bool = True
    #: An AI grant that would newly show a statement to an external audience
    #: waits for a curator. Off applies it at once.
    confirm_external_grants: bool = True
    #: Have a second AI review grants waiting for external confirmation.
    ai_grant_review: bool = False
    #: Have the same AI decide curator labels whose statement text changed
    #: since, and confirmed grants an edit's relabel kept in force.
    ai_label_decisions: bool = False
    #: Pending grants one review sample draws per external audience.
    sample_size: int = Field(default=50, gt=0, le=500)
    #: Below this sample precision the review suggests relabelling instead
    #: of accepting the rest.
    min_sample_precision_percent: int = Field(default=90, ge=0, le=100)
    batch_size: int = Field(default=25, gt=0, le=100)
    #: Further AI decisions on an item after one failed, before it stops
    #: until its statement or label changes or a person retries it.
    decision_retries: int = Field(default=2, ge=0)
    max_tokens: int = Field(default=6000, gt=0)
    max_retries: int = Field(default=2, ge=0)
    request_timeout_s: float = Field(default=90.0, gt=0)


class DocumentationPlanningSettings(RequestLimits):
    kind: Literal["documentation_planning"] = "documentation_planning"
    max_tokens: int = Field(default=12000, gt=0)
    max_retries: int = Field(default=2, ge=0)
    request_timeout_s: float = Field(default=300.0, gt=0)
    #: Concepts the overview lists, most visible statements first.
    max_entities: int = Field(default=150, gt=0, le=1000)
    #: Capability statements the overview quotes, the most linked first.
    max_capabilities: int = Field(default=150, ge=0, le=1000)
    max_items: int = Field(default=15, gt=0, le=50)
    #: Statements no document of the profile cites that one plan is asked to
    #: place, those no plan was offered yet first.
    max_uncovered: int = Field(default=40, ge=0, le=500)
    #: A concept with this many visible statements and no document of the
    #: profile shows in the coverage view.
    coverage_min_statements: int = Field(default=10, gt=0)
    #: Newly visible statements since the last plan before re-planning is
    #: hinted, and statements no document cites and no plan was offered
    #: before a profile with automatic planning plans by itself.
    replan_hint_statements: int = Field(default=25, gt=0)
    #: Items one batch approval may start; each is a documentation run.
    approve_batch: int = Field(default=2, gt=0, le=10)
    #: Planning calls one plan may make while statements no plan was offered
    #: remain, each offered the next batch of them and keeping up to
    #: `max_items`.
    max_calls: int = Field(default=1, gt=0, le=5)
    #: Failed automatic plans retried for profiles whose recovery is `ai`.
    plan_retries: int = Field(default=2, ge=0)
    #: Failed plan reviews retried for profiles whose recovery is `ai`.
    plan_review_retries: int = Field(default=2, ge=0)
    #: Plan items retried after their run could not start under `ai` recovery.
    item_start_retries: int = Field(default=2, ge=0)


class DocumentationMaintenanceSettings(SettingsModel):
    """Guard rails for profiles whose out-of-date documents revise themselves."""

    kind: Literal["documentation_maintenance"] = "documentation_maintenance"
    #: Minutes without a further change to a document's cited statements
    #: before it is revised, so a burst of edits causes one revision.
    quiet_minutes: int = Field(default=30, ge=0)
    #: Automatic revisions one profile may start in any 24 hours.
    revisions_per_day: int = Field(default=5, ge=0)
    #: Runs that wrote nothing retried for profiles whose recovery is `ai`.
    run_retries: int = Field(default=2, ge=0)
    #: Automatic revisions retried after their run could not start under `ai` recovery.
    revision_start_retries: int = Field(default=2, ge=0)
    #: Failed automatic publications retried under `ai` recovery.
    delivery_retries: int = Field(default=2, ge=0)


class ConnectSettings(LoopLimits):
    kind: Literal["connect"] = "connect"
    #: Most statements one connect run takes; each run is one draft.
    batch_size: int = Field(default=5, gt=0, le=25)
    #: Most tokens one run may use, cache reads included; 0 sets no cap.
    max_run_tokens: int = Field(default=2_000_000, ge=0)
    max_tokens: int = Field(default=32000, gt=0)
    op_cap: int = Field(default=60, gt=0)
    wall_clock_s: float = Field(default=300.0, gt=0)
    request_timeout_s: float = Field(default=120.0, gt=0)
    #: The AI curation pass works these lists in the background on the
    #: connect model while Connecting statements runs on a server model.
    #: Run the connect pass on the next statements to connect.
    connect_automatically: bool = False
    #: Decide duplicate statement and concept candidates.
    decide_duplicates: bool = False
    #: Describe concepts that have no description.
    describe_concepts: bool = False
    #: Act on rephrase gaps and on gaps about a draft.
    act_on_gaps: bool = False
    #: Further connect runs on a statement after one failed to look at it,
    #: before it stops until its text changes or a person retries it.
    connect_retries: int = Field(default=2, ge=0)
    #: Further curation proposals in one chain of rejected drafts, before
    #: the next gap about a rejected draft is left for a person.
    follow_up_retries: int = Field(default=2, ge=0)


class ConcurrencySettings(SettingsModel):
    kind: Literal["concurrency"] = "concurrency"
    model_loops: int = Field(default=2, gt=0)
    documentation_runs: int = Field(default=2, gt=0)


class MediaSettings(SettingsModel):
    """Limits and freshness for screenshots and recordings."""

    kind: Literal["media"] = "media"
    image_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0, le=50 * 1024 * 1024)
    video_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0, le=200 * 1024 * 1024)
    #: Media captured or replaced longer ago than this is flagged as old.
    stale_after_days: int = Field(default=365, gt=0)
    #: The product version media should show. Media captured against another
    #: version is flagged; empty turns the check off.
    product_version: str = Field(default="", max_length=100)


SetupStep = Literal["credentials", "models", "audiences", "profile", "github", "review"]


class SetupSettings(SettingsModel):
    kind: Literal["setup"] = "setup"
    #: Checklist steps an admin set aside (see `setup_checklist`).
    dismissed: tuple[SetupStep, ...] = Field(default=(), strict=False)


class DestinationSettings(SettingsModel):
    name: str = Field(min_length=1, max_length=200)
    path_template: str = Field(min_length=1, max_length=1000)
    owner: str = Field(min_length=1, max_length=200)
    repo: str = Field(min_length=1, max_length=200)
    base_branch: str = Field(min_length=1, max_length=200)
    binding: str = Field(min_length=1, max_length=200)

    def destination(self, conn: sqlite3.Connection | None = None) -> DestinationConfig:
        from .docgen.destinations import DestinationConfig

        binding = github_credentials.documentation_settings(
            self.binding, self.owner, self.repo, conn
        )
        return DestinationConfig(
            self.name,
            "github",
            self.path_template,
            {
                **self.model_dump(exclude={"name", "path_template", "binding"}),
                **binding,
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


ModelId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class ModelCatalogSettings(SettingsModel):
    """The models an admin made selectable, per provider, in their order.
    Every model choice picks from these."""

    kind: Literal["model_catalog"] = "model_catalog"
    claude: tuple[ModelId, ...] = Field(default=(), strict=False)
    openai: tuple[ModelId, ...] = Field(default=(), strict=False)

    def models(self, provider: Provider) -> tuple[str, ...]:
        return self.claude if provider == "claude" else self.openai

    @model_validator(mode="after")
    def validate_models(self) -> ModelCatalogSettings:
        for provider in model_settings.PROVIDERS:
            models = self.models(provider)
            if len(set(models)) != len(models):
                raise ValueError("A provider lists a model more than once.")
            for model in models:
                model_settings.check_model_id(provider, model)
        return self


Section = Literal[
    "ask",
    "ingest",
    "docgen",
    "draft_review",
    "alias_discovery",
    "audience_labelling",
    "documentation_planning",
    "documentation_maintenance",
    "connect",
    "concurrency",
    "documentation",
    "setup",
    "media",
    "model_catalog",
]
Body = Annotated[
    AskSettings
    | IngestSettings
    | DocgenSettings
    | ReviewSettings
    | AliasDiscoverySettings
    | AudienceLabellingSettings
    | DocumentationPlanningSettings
    | DocumentationMaintenanceSettings
    | ConnectSettings
    | ConcurrencySettings
    | DocumentationSettings
    | SetupSettings
    | MediaSettings
    | ModelCatalogSettings,
    Field(discriminator="kind"),
]
BODY: TypeAdapter[Body] = TypeAdapter(Body)
DEFAULTS: tuple[Body, ...] = (
    AskSettings(),
    IngestSettings(),
    DocgenSettings(),
    ReviewSettings(),
    AliasDiscoverySettings(),
    AudienceLabellingSettings(),
    DocumentationPlanningSettings(),
    DocumentationMaintenanceSettings(),
    ConnectSettings(),
    ConcurrencySettings(),
    DocumentationSettings(),
    SetupSettings(),
    MediaSettings(),
    ModelCatalogSettings(),
)


class InvalidLegacySettings(SettingsModel):
    kind: Section
    invalid_legacy_configuration: Literal[True]

    @field_validator("invalid_legacy_configuration", mode="before")
    @classmethod
    def require_true(cls, value: object) -> Literal[True]:
        if value is not True:
            raise ValueError("Invalid legacy configuration marker must be true.")
        return True


ArchivedBody = Body | InvalidLegacySettings
ARCHIVED_BODY: TypeAdapter[ArchivedBody] = TypeAdapter(ArchivedBody)


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
    | DocgenSettings
    | ReviewSettings
    | AliasDiscoverySettings
    | AudienceLabellingSettings
    | DocumentationPlanningSettings
    | DocumentationMaintenanceSettings
    | ConnectSettings
    | ConcurrencySettings
    | DocumentationSettings
    | SetupSettings
    | MediaSettings
    | ModelCatalogSettings,
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
        if isinstance(request.settings, ModelCatalogSettings) and isinstance(
            current.settings, ModelCatalogSettings
        ):
            for provider in model_settings.PROVIDERS:
                model_settings.refuse_removing_used(
                    db,
                    provider,
                    set(current.settings.models(provider))
                    - set(request.settings.models(provider)),
                )
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
        from .server import admission

        admission._model_loop_budget().changed()
    return result


def validate_secrets(settings: Body, *, conn: sqlite3.Connection | None = None) -> None:
    if not isinstance(settings, DocumentationSettings) or not settings.destinations:
        return
    bindings = github_credentials.load(conn)
    for item in settings.destinations:
        github_credentials.documentation_settings(
            item.binding, item.owner, item.repo, conn
        )
    credentials = [
        os.environ.get(binding.token_env, "") for binding in bindings.values()
    ]
    if any(secret and secret in settings.model_dump_json() for secret in credentials):
        raise ValueError(
            "Configuration contains a credential. Use credential variable names only."
        )


def _legacy(default: Body, conn: sqlite3.Connection) -> Body:
    if isinstance(
        default,
        AliasDiscoverySettings
        | AudienceLabellingSettings
        | DocumentationPlanningSettings
        | DocumentationMaintenanceSettings
        | ConnectSettings
        | SetupSettings
        | MediaSettings
        | ModelCatalogSettings,
    ):
        return default
    if isinstance(default, DocumentationSettings):
        from .docgen.destinations import load_destinations
        from .docgen.github_destination import parse_config

        destinations = []
        for destination in load_destinations(os.environ).values():
            github = parse_config(destination)
            if github.connection is not None:
                binding = github.connection
            else:
                assert github.token_env is not None  # parse_config demands one
                binding = github_credentials.import_binding(
                    conn, github.host, github.token_env
                )
            destinations.append(
                DestinationSettings(
                    name=destination.name,
                    path_template=destination.path_template,
                    owner=github.owner,
                    repo=github.repo,
                    base_branch=github.base_branch,
                    binding=binding,
                )
            )
        return DocumentationSettings(
            guideline_set=os.environ.get("MYCELIUM_DOCGEN_GUIDELINE_SET")
            or default.guideline_set,
            destinations=tuple(destinations),
        )
    values = default.model_dump()
    concurrency_names = {
        "model_loops": "MYCELIUM_MODEL_LOOP_MAX_CONCURRENT",
        "documentation_runs": "MYCELIUM_DOCGEN_MAX_ACTIVE",
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
            body = InvalidLegacySettings(
                kind=default.kind, invalid_legacy_configuration=True
            ).model_dump_json()
        conn.execute(
            "INSERT OR IGNORE INTO product_settings VALUES (?, 1, ?)",
            (default.kind, body),
        )
    conn.execute(
        "INSERT INTO instance_settings_migrations(name) VALUES (?)", (MIGRATION,)
    )


#: Saved values that were once the shipped default and proved too small, per
#: section and field, with the once-per-instance marker that lifts them.
_OUTGROWN_DEFAULTS = (
    ("ingest", "max_tokens", 8000, "ingest-max-tokens-32000"),
    ("docgen", "max_tokens", 12000, "docgen-max-tokens-32000"),
    ("ingest", "wall_clock_s", 120.0, "ingest-wall-clock-300"),
)


def raise_outgrown_defaults(conn: sqlite3.Connection) -> None:
    """Once per instance, lift a saved value still at an old default: most
    ingest drafts outgrew 8000 output tokens and a document-writing turn
    12000, and an ingest run needs more than 120 s once the wall clock is
    enforced."""
    current = {
        "ingest": IngestSettings().model_dump(),
        "docgen": DocgenSettings().model_dump(),
    }
    for section, field, old, marker in _OUTGROWN_DEFAULTS:
        if conn.execute(
            "SELECT 1 FROM instance_settings_migrations WHERE name = ?", (marker,)
        ).fetchone():
            continue
        conn.execute(
            "UPDATE product_settings SET revision = revision + 1, "
            "body_json = json_set(body_json, '$.' || ?, ?) "
            "WHERE section = ? AND json_valid(body_json) "
            "AND json_extract(body_json, '$.' || ?) = ?",
            (field, current[section][field], section, field, old),
        )
        conn.execute("INSERT INTO instance_settings_migrations VALUES (?)", (marker,))


#: Dollar limits earlier versions saved, per section: the field, its shipped
#: default and the token field that replaced it.
_DOLLAR_LIMITS = {
    "draft_review": ("max_cost_usd", 1.0, "max_draft_tokens"),
    "connect": ("max_cost_usd", 0.5, "max_run_tokens"),
}


def replace_dollar_limit(settings: dict[str, object]) -> str | None:
    """Swap a saved dollar limit for its token field, in place. A dollar
    amount has no token equivalent that holds across models, so only a value
    still at the shipped default takes the token default; any other becomes
    no limit, and the returned line says so for the log."""
    kind = settings.get("kind")
    if not isinstance(kind, str) or kind not in _DOLLAR_LIMITS:
        return None
    old, shipped, new = _DOLLAR_LIMITS[kind]
    if old not in settings:
        return None
    dollars = settings.pop(old)
    default = next(d for d in DEFAULTS if d.kind == kind)
    if dollars == shipped:
        settings[new] = getattr(default, new)
        return None
    settings[new] = 0
    return f"{kind}: the ${dollars} {old} became no {new} limit"


def replace_dollar_limits(conn: sqlite3.Connection) -> None:
    for kind in _DOLLAR_LIMITS:
        row = conn.execute(
            "SELECT body_json FROM product_settings WHERE section = ?", (kind,)
        ).fetchone()
        if row is None:
            continue
        try:
            settings = json.loads(row["body_json"])
        except ValueError:
            continue  # unreadable settings stay disabled until an admin saves
        if not isinstance(settings, dict) or _DOLLAR_LIMITS[kind][0] not in settings:
            continue
        if note := replace_dollar_limit(settings):
            logger.warning("Mycelium keeps no prices; %s", note)
        conn.execute(
            "UPDATE product_settings SET revision = revision + 1, body_json = ? "
            "WHERE section = ?",
            (json.dumps(settings), kind),
        )


def budget_removed(settings: dict[str, object]) -> str | None:
    """The log line for a saved `ai_budget` section that set a limit, or None.
    Mycelium has no AI budget any more: spend limits are set in each
    provider's console, and per-run token limits guard against runaway runs."""
    tokens = settings.get("monthly_limit_tokens")
    if isinstance(tokens, int) and tokens:
        limit = f"{tokens:,} tokens"
    elif dollars := settings.get("monthly_limit_usd"):
        limit = f"${dollars}"
    else:
        return None
    return (
        f"removed the monthly AI budget of {limit}; set spend limits in each "
        "provider's console instead"
    )


def without_budget_step(settings: dict[str, object]) -> bool:
    """Drop the removed budget step from a saved setup section's dismissed
    steps, in place. Returns whether it was there."""
    dismissed = settings.get("dismissed")
    if (
        settings.get("kind") != "setup"
        or not isinstance(dismissed, list)
        or "budget" not in dismissed
    ):
        return False
    settings["dismissed"] = [step for step in dismissed if step != "budget"]
    return True


def drop_budget(conn: sqlite3.Connection) -> None:
    """Remove what the monthly AI budget left behind. Strict settings models
    would otherwise refuse the leftover rows."""
    row = conn.execute(
        "SELECT body_json FROM product_settings WHERE section = 'ai_budget'"
    ).fetchone()
    if row is not None:
        saved = _json_object(row[0])
        if saved is not None and (note := budget_removed(saved)):
            logger.warning("Mycelium sets no AI budget; %s", note)
        conn.execute("DELETE FROM product_settings WHERE section = 'ai_budget'")
    row = conn.execute(
        "SELECT body_json FROM product_settings WHERE section = 'setup'"
    ).fetchone()
    setup = None if row is None else _json_object(row[0])
    if setup is not None and without_budget_step(setup):
        conn.execute(
            "UPDATE product_settings SET revision = revision + 1, body_json = ? "
            "WHERE section = 'setup'",
            (json.dumps(setup),),
        )


def _json_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None  # unreadable settings stay disabled until an admin saves
    return value if isinstance(value, dict) else None


class ArchivedSection(SettingsModel):
    revision: int = Field(gt=0)
    settings: ArchivedBody
    configuration_error: None = None


class Archive(SettingsModel):
    sections: list[ArchivedSection]
    github_bindings: dict[str, github_credentials.Binding]
    github_connections: dict[str, GitHubConnection] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def validate_sections(self) -> Archive:
        kinds = [item.settings.kind for item in self.sections]
        if len(set(kinds)) != len(kinds):
            raise ValueError("Archive repeats a product settings section.")
        return self


def archive(conn: sqlite3.Connection) -> Archive:
    sections = []
    for row in conn.execute(
        "SELECT section, revision, body_json FROM product_settings ORDER BY section"
    ):
        settings = ARCHIVED_BODY.validate_json(row["body_json"])
        if settings.kind != row["section"]:
            raise ValueError(
                "Saved product settings section does not match its content."
            )
        sections.append(ArchivedSection(revision=row["revision"], settings=settings))
    bindings = {
        row["name"]: github_credentials.Binding.model_validate_json(row["body_json"])
        for row in conn.execute(
            "SELECT name, body_json FROM github_credential_bindings"
        )
    }
    return Archive(
        sections=sections,
        github_bindings=bindings,
        github_connections=github_connections.load(conn),
    )


def restore(conn: sqlite3.Connection, archived: Archive) -> None:
    for name, connection in archived.github_connections.items():
        if name != connection.name:
            raise ValueError("Invalid archived GitHub connection reference.")
        conn.execute(
            "INSERT INTO github_app_connections VALUES (?, ?)",
            (name, connection.model_copy(update={"enabled": False}).model_dump_json()),
        )
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
