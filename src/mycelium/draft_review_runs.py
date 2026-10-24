"""Internal review execution; model proposals cannot grant mutation authority."""

from __future__ import annotations

import contextvars
import functools
import itertools
import json
import logging
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from . import (
    ai,
    ai_prompts,
    ai_usage,
    auth,
    draft_review_model,
    draft_review_settings,
    draft_review_store,
    drafts_store,
    mentions,
    model_settings,
    product_settings,
    quarantine,
    request_timing,
    store,
    timestamps,
    workers,
)
from .ask.substrate import InProcessSubstrate, _json_schema_for
from .draft_review_store import Answer, Assessment, Label, Mode, PartReview, ReviewRun

if TYPE_CHECKING:
    from .server.draft_review import (
        DraftReviewInspection,
        Operation,
        OperationKnowledge,
        RecordKey,
    )

logger = logging.getLogger(__name__)
RUNNER: Callable[[str], Assessment] | None = None
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="draft-review")
_futures: dict[str, Future[None]] = {}
_spawn_lock = threading.Lock()
_json_value: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_CONTEXT_LIMIT = 90000
# A part's own operations and records fill at most this much of its context,
# leaving the rest for the closest live statements.
_PART_BASE_LIMIT = _CONTEXT_LIMIT * 3 // 5
_OTHER_PARTS_LIMIT = 8000
# Fewer characters per token than usual text, so the estimate errs high.
_CHARS_PER_TOKEN = 3
_RELATED_PER_STATEMENT = 5
_payload = TypeAdapter(dict[str, JsonValue])


def _correction_payload(
    correction: draft_review_store.Correction,
) -> dict[str, JsonValue]:
    if not correction.payload_json:
        raise ValueError(
            f"a {correction.action} correction needs payload_json: the "
            "operation's complete arguments as one JSON object"
        )
    try:
        return _payload.validate_json(correction.payload_json)
    except ValidationError:
        raise ValueError(
            f"a {correction.action} correction's payload_json is not one JSON object"
        ) from None


# These mutation families have entity/statement fingerprints in draft inspection.
REVIEWABLE_OPERATIONS = frozenset(
    {
        "upsert_entity",
        "upsert_statement",
        "upsert_statements",
        "patch_statement",
        "replace_text",
        "upsert_name",
        "move_name",
        "rename_name",
        "merge_entities",
        "merge_statements",
        "delete_name",
        "delete_entity",
        "delete_statement",
        "add_links",
        "remove_links",
        "add_entity_links",
        "remove_entity_links",
    }
)


class NotAdmitted(ValueError):
    """The draft's latest run no longer qualifies for the requested review."""


@dataclass(frozen=True)
class Read:
    name: str
    arguments: dict[str, JsonValue]
    result: JsonValue


def _settings() -> draft_review_settings.Snapshot:
    """The review settings in force. Quarantine turns review off without
    changing what is saved."""
    settings = draft_review_settings.load()
    return (
        settings.model_copy(update={"mode": "off"}) if quarantine.active() else settings
    )


def mode() -> Mode:
    return _settings().mode


def credentials_error(settings: draft_review_settings.Snapshot) -> str | None:
    reason = model_settings.provider_availability(settings.provider).reason
    return None if reason is None else f"Internal draft review cannot run: {reason}"


def reviewer(creator: str | None, identity: str) -> auth.Principal:
    from .server import runtime  # local import: loading it loads the server package

    principal = auth.resolve_session_user(runtime._auth_db(), identity)
    if principal is None or not auth.principal_has_real_role(principal, "writer"):
        raise ValueError(
            "configured review user must be an active real writer or admin"
        )
    if principal.id == creator:
        raise ValueError("configured reviewer must be independent of the draft creator")
    return principal


def start(
    draft_id: str,
    *,
    rerun: bool = False,
    attempt: int = 1,
    retries: int = 0,
    previous_failure: str | None = None,
    answer: Answer | None = None,
    admit: Callable[[ReviewRun | None], bool] | None = None,
) -> ReviewRun:
    """`admit`, when given, decides under the admission lock whether the
    draft's latest run still qualifies, so a selection made earlier cannot
    supersede a run that finished in between."""
    from . import server  # local import: server registers the review tools

    settings = _settings()
    limits = product_settings.get(product_settings.ReviewSettings)
    if settings.mode == "off":
        raise ValueError("internal draft review is off")
    if not settings.model:
        raise ValueError("Choose a model ID before starting an internal draft review.")
    # Checked before a run is recorded: without credentials every attempt
    # fails, and a restored copy would otherwise fill up with failed runs.
    if reason := credentials_error(settings):
        raise ValueError(reason)
    conn = drafts_store.connection()
    with _spawn_lock, store.transaction(conn):
        row = drafts_store.get_draft(conn, draft_id)
        if row is None or drafts_store.status_for(row) != "submitted":
            raise ValueError("only submitted drafts can be internally reviewed")
        previous = draft_review_store.latest(conn, draft_id)
        if admit is not None and not admit(previous):
            raise NotAdmitted("the draft's latest review changed; not started")
        answers = previous.answers if previous else []
        if answer is not None:
            if previous is None or previous.application != "needs_human":
                raise ValueError("the internal reviewer is not waiting for an answer")
            if previous.run_id != answer.run_id:
                raise ValueError("the reviewer has asked again since; reload")
            if previous.stale:
                raise ValueError("the draft changed after the reviewer asked; rerun")
            answers = [
                *answers,
                answer.model_copy(update={"questions": previous.questions}),
            ]
        if previous and (previous.status == "running" or not rerun):
            return previous
        active = conn.execute(
            "SELECT id FROM draft_review_runs WHERE draft_id = ? AND status = 'running'",
            (draft_id,),
        ).fetchone()
        if active:
            return draft_review_store.get(conn, active["id"])
        instructions = ai_prompts.resolve("draft_review")
        run = draft_review_store.new(draft_id, settings.mode, int(row["revision"]))
        run.prompt = instructions.reference()
        run.provider = settings.provider
        run.model = settings.model
        run.reasoning_effort = settings.reasoning_effort
        run.reviewer_id = settings.reviewer_id
        run.settings_revision = settings.revision
        run.model_settings_revision = settings.model_revision
        run.attempt = attempt
        run.retries = retries
        run.previous_failure = previous_failure
        run.answers = answers
        draft_review_store.save(conn, run)
    try:
        principal = reviewer(row["created_by"], settings.reviewer_id)
        token = auth.current_principal.set(principal)
        try:
            inspection = server.inspect_draft_review(draft_id)
        finally:
            auth.current_principal.reset(token)
        if inspection["draft_revision"] != run.draft_revision:
            raise ValueError("draft changed while starting review; rerun")
        context = contextvars.Context()
        run.knowledge_preconditions = inspection["knowledge_preconditions"]
        _save(run)
        future = _executor.submit(
            context.run, _execute, run, inspection, settings, limits, instructions
        )
        _futures[run.run_id] = future
        future.add_done_callback(lambda _: _futures.pop(run.run_id, None))
    except Exception as exc:
        _futures.pop(run.run_id, None)
        _failed(run, str(exc))
    return run


def on_submitted(draft_id: str) -> None:
    try:
        settings = _settings()
        if settings.mode != "off" and not credentials_error(settings):
            start(draft_id)
    except Exception:
        # Submission already committed; failure here must not turn it into a retry.
        logger.exception("could not start internal draft review for %s", draft_id)


# A failed run is retried after RETRY_BACKOFF, doubling per retry, at most
# MAX_RETRIES times: about two and a half hours of a provider outage.
MAX_RETRIES = 5
RETRY_BACKOFF = timedelta(minutes=5)
# A failure older than the whole schedule did not happen under this process's
# watch: a restored copy of another instance, or a long outage of this one.
# Retrying it would review, and possibly apply, old drafts unasked, so it is
# left for the backlog review.
RETRY_WINDOW = RETRY_BACKOFF * (1 << MAX_RETRIES)
SWEEP_INTERVAL_S = 60.0


@request_timing.tracked("background draft review sweep")
def sweep(now: datetime | None = None) -> list[str]:
    """Resume budget-paused reviews and retry failed reviews after backoff.
    Returns the draft ids started."""
    now = now or datetime.now(UTC)
    try:
        settings = _settings()
    except draft_review_settings.Unavailable:
        return []
    if settings.mode == "off" or credentials_error(settings):
        return []
    started = []
    conn = drafts_store.connection()
    budget = product_settings.get(product_settings.AIBudgetSettings)
    if ai_usage.paused_reason(conn, "draft_review", budget, now):
        return []
    for row in drafts_store.list_drafts(conn, "submitted"):
        run = draft_review_store.latest(conn, row["id"])
        if run is None or not _retry_due(run, now):
            continue
        try:
            start(
                row["id"],
                rerun=True,
                attempt=run.attempt if run.status == "paused" else 1,
                retries=run.retries if run.status == "paused" else run.retries + 1,
                previous_failure=run.previous_failure
                if run.status == "paused"
                else run.detail,
                admit=_still_due(run, now),
            )
            started.append(row["id"])
        except NotAdmitted:
            continue
        except Exception:
            logger.exception("could not retry review of %s", row["id"])
    return started


def _still_due(seen: ReviewRun, now: datetime) -> Callable[[ReviewRun | None], bool]:
    def admit(latest: ReviewRun | None) -> bool:
        return (
            latest is not None
            and latest.run_id == seen.run_id
            and latest.status == seen.status
            and _retry_due(latest, now)
        )

    return admit


def _retry_due(run: ReviewRun, now: datetime) -> bool:
    if run.status == "paused":
        return True
    if (
        run.status != "failed"
        or run.review_id is not None
        or run.application != "unapplied"
        or run.retries >= MAX_RETRIES
        or run.finished_at is None
    ):
        return False
    finished = datetime.fromisoformat(run.finished_at)
    return (
        finished + RETRY_BACKOFF * (1 << run.retries) <= now < finished + RETRY_WINDOW
    )


def backlog() -> list[str]:
    """Submitted drafts the current configuration has not reviewed and
    cannot reach by itself: submitted while review was off, reviewed only
    advisorily, or failed beyond the sweep, oldest first. Alias suggestion
    drafts await a person and are left out."""
    current = mode()
    conn = drafts_store.connection()
    waiting = []
    for row in reversed(drafts_store.list_drafts(conn, "submitted")):
        ops = drafts_store.list_ops(conn, row["id"])
        if all(op["kind"] == drafts_store.ALIAS_SUGGESTION_KIND for op in ops):
            continue
        if _in_backlog(draft_review_store.latest(conn, row["id"]), current):
            waiting.append(row["id"])
    return waiting


def _in_backlog(run: ReviewRun | None, current: Mode) -> bool:
    if run is None:
        return True
    if run.status in {"running", "paused"}:
        return False
    if run.application == "needs_human":
        return run.stale
    if run.application != "unapplied" or run.review_id is not None:
        return False
    if run.status == "failed":
        return True
    return run.stale or run.mode != current or current == "review-and-apply"


class BacklogJob(BaseModel):
    """An admin's review of the backlog, one draft at a time, oldest first.
    It lives in this process: a restart ends it, and starting it again
    picks up the drafts still waiting."""

    status: Literal["running", "paused", "finished"] = "running"
    #: The most the job may spend; None leaves only the monthly AI budget.
    budget_usd: float | None = None
    spent_usd: float = 0.0
    reviewed: int = 0
    remaining: int = 0
    detail: str | None = None
    started_at: str = Field(default_factory=timestamps.now)
    finished_at: str | None = None


_backlog_lock = threading.Lock()
_backlog_job: BacklogJob | None = None
_backlog_attempted: set[str] = set()
_backlog_thread: threading.Thread | None = None


def backlog_job() -> BacklogJob | None:
    with _backlog_lock:
        return None if _backlog_job is None else _backlog_job.model_copy()


def review_backlog(budget_usd: float | None = None) -> BacklogJob:
    """Start reviewing the backlog oldest first, stopping before a draft
    whose likely cost would pass `budget_usd`."""
    global _backlog_job
    if reason := _backlog_unavailable():
        raise ValueError(reason)
    with _backlog_lock:
        if _backlog_job is not None and _backlog_job.status != "finished":
            raise ValueError("a backlog review is already started; resume it")
        _backlog_job = BacklogJob(budget_usd=budget_usd, remaining=len(backlog()))
        _backlog_attempted.clear()
        _drain_in_background()
        return _backlog_job.model_copy()


def pause_backlog() -> BacklogJob:
    with _backlog_lock:
        if _backlog_job is None or _backlog_job.status != "running":
            raise ValueError("no backlog review is running")
        _backlog_job.status = "paused"
        _backlog_job.detail = "Paused by an administrator after the draft under review."
        return _backlog_job.model_copy()


def resume_backlog() -> BacklogJob:
    if reason := _backlog_unavailable():
        raise ValueError(reason)
    with _backlog_lock:
        if _backlog_job is None or _backlog_job.status != "paused":
            raise ValueError("no backlog review is paused")
        _backlog_job.status = "running"
        _backlog_job.detail = None
        _drain_in_background()
        return _backlog_job.model_copy()


def forget_backlog_job() -> None:
    """A job belongs to the runtime that started it; a thread still running
    for an earlier one stops at its next draft."""
    global _backlog_job
    with _backlog_lock:
        _backlog_job = None
        _backlog_attempted.clear()


def wait_backlog(timeout: float = 10) -> None:
    thread = _backlog_thread
    if thread is not None:
        thread.join(timeout)


def _backlog_unavailable() -> str | None:
    settings = _settings()
    if settings.mode == "off":
        return "internal draft review is off"
    return credentials_error(settings)


def _drain_in_background() -> None:
    """Called holding _backlog_lock; a thread still finishing its draft
    after a pause carries on instead of a second one starting."""
    global _backlog_thread
    if _backlog_thread is not None and _backlog_thread.is_alive():
        return
    _backlog_thread = threading.Thread(
        target=_drain, name="draft-review-backlog", daemon=True
    )
    _backlog_thread.start()


def _drain() -> None:
    while (draft_id := _next_backlog_draft()) is not None:
        since = timestamps.now()
        try:
            start(
                draft_id,
                rerun=True,
                admit=functools.partial(_in_backlog, current=mode()),
            )
        except NotAdmitted:
            continue
        except Exception:
            logger.exception("could not start review of %s", draft_id)
            continue
        _wait_for(draft_id)
        cost = ai_usage.draft_cost(
            drafts_store.connection(), "draft_review", draft_id, since
        )
        with _backlog_lock:
            assert _backlog_job is not None  # set before the thread starts
            _backlog_job.reviewed += 1
            _backlog_job.spent_usd += cost


def _next_backlog_draft() -> str | None:
    """The oldest waiting draft this job has not tried, or None once the
    job pauses or finishes."""
    waiting = [item for item in backlog() if item not in _backlog_attempted]
    hold = _backlog_unavailable() or _backlog_spent()
    with _backlog_lock:
        job = _backlog_job
        if job is None or job.status != "running":
            return None
        job.remaining = len(waiting)
        if not waiting:
            job.status = "finished"
            job.detail = "No waiting draft is left."
            job.finished_at = timestamps.now()
            return None
        if hold:
            job.status = "paused"
            job.detail = hold
            return None
        _backlog_attempted.add(waiting[0])
        return waiting[0]


def _backlog_spent() -> str | None:
    conn = drafts_store.connection()
    budget = product_settings.get(product_settings.AIBudgetSettings)
    if reason := ai_usage.paused_reason(conn, "draft_review", budget):
        return reason
    with _backlog_lock:
        job = _backlog_job
        if job is None or job.budget_usd is None:
            return None
        spent, limit = job.spent_usd, job.budget_usd
    since = timestamps.of(datetime.now(UTC) - timedelta(days=30))
    next_draft = ai_usage.mean_run_cost(conn, "draft_review", since) or 0.0
    if spent + next_draft <= limit:
        return None
    return (
        f"Stopped at the backlog budget: about ${spent:.2f} of ${limit:g} spent, "
        f"and the next draft likely costs ${next_draft:.2f}. Resume to go on."
    )


def _wait_for(draft_id: str) -> None:
    """Until the draft's review, including its automatic rerun, is done."""
    conn = drafts_store.connection()
    while (run := draft_review_store.latest(conn, draft_id)) is not None:
        future = _futures.get(run.run_id)
        if run.status != "running" or future is None:
            return
        try:
            future.result()
        except Exception:
            logger.exception("review of %s failed", draft_id)


_sweeper = workers.Worker(
    "draft-review-sweep",
    lambda _: sweep(),
    interval=SWEEP_INTERVAL_S,
    session=workers.no_session,
    delay_first=True,
)


def start_sweeper() -> None:
    _sweeper.start()


def stop_sweeper(timeout: float = 5.0) -> None:
    _sweeper.stop(timeout)


def wait_all(timeout: float = 10) -> None:
    while _futures:
        for future in list(_futures.values()):
            future.result(timeout=timeout)


def _save(run: ReviewRun) -> None:
    conn = drafts_store.connection()
    with store.transaction(conn):
        draft_review_store.save(conn, run)


def _failed(run: ReviewRun, detail: str) -> None:
    run.status = "failed"
    run.detail = detail
    from .server import (
        draft_application,  # local import: reconcile the separate substrate receipt
    )

    draft_review_store.reconcile(
        drafts_store.connection(),
        run,
        lambda application_id: (
            draft_application.substrate_application_result(application_id) is not None
        ),
    )
    run.finished_at = timestamps.now()
    _save(run)


def _read(reader: InProcessSubstrate, name: str, args: dict[str, JsonValue]) -> Read:
    result = _json_value.validate_python(reader.call(name, args))
    return Read(name, args, result)


@dataclass(frozen=True)
class Part:
    """Connected operations reviewed together, with the records they touch."""

    ops: list[dict[str, JsonValue]]
    records: list[draft_review_store.Precondition]

    @property
    def refs(self) -> set[str]:
        return {str(op["operation_ref"]) for op in self.ops}


@dataclass(frozen=True)
class PartContext:
    part: Part
    context: str
    reads: list[Read]


class Refused(ValueError):
    """The draft cannot be reviewed as submitted; the server rejects it
    without a model call."""


def _ops(inspection: DraftReviewInspection) -> list[dict[str, JsonValue]]:
    ops = inspection["draft"].get("ops")
    if not isinstance(ops, list):
        raise ValueError("draft has no operation list")
    return [op for op in ops if isinstance(op, dict)]


def _operations(ops: list[dict[str, JsonValue]]) -> list[Operation]:
    return [
        (
            str(op["operation_ref"]),
            str(op["kind"]),
            _payload.validate_python(op["payload"]),
        )
        for op in ops
    ]


def _whole(inspection: DraftReviewInspection) -> Part:
    return Part(_ops(inspection), list(inspection["knowledge_preconditions"]))


def _components(inspection: DraftReviewInspection) -> list[Part]:
    """The draft's operations grouped so that operations naming the same
    record, referring to each other's results (`@seq:index`), or naming an
    entity the draft creates stay together. Records an operation only
    mentions are context for it, not a reason to group."""
    from .server import draft_review  # local import: loads the server package

    ops = _ops(inspection)
    knowledge = draft_review.operation_knowledge(_operations(ops))
    parent = {str(op["operation_ref"]): str(op["operation_ref"]) for op in ops}

    def find(ref: str) -> str:
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    for a, b in _ties(ops, knowledge):
        parent[find(a)] = find(b)
    preconditions = {
        (item["kind"], item["id"]): item
        for item in inspection["knowledge_preconditions"]
    }
    groups: dict[str, list[dict[str, JsonValue]]] = {}
    for op in ops:
        groups.setdefault(find(str(op["operation_ref"])), []).append(op)
    parts = []
    for members in groups.values():
        keys: set[RecordKey] = set()
        for op in members:
            item = knowledge[str(op["operation_ref"])]
            keys |= item["targets"] | item["mentioned"]
        parts.append(
            Part(
                members,
                [preconditions[key] for key in sorted(keys) if key in preconditions],
            )
        )
    return parts


def _ties(
    ops: list[dict[str, JsonValue]], knowledge: dict[str, OperationKnowledge]
) -> Iterator[tuple[str, str]]:
    """Pairs of operations that must be reviewed together."""
    owner: dict[RecordKey, str] = {}
    by_seq = {op.get("seq"): str(op["operation_ref"]) for op in ops}
    created: dict[str, str] = {}
    for op in ops:
        ref = str(op["operation_ref"])
        for key in knowledge[ref]["targets"]:
            yield ref, owner.setdefault(key, ref)
        payload = op.get("payload")
        for seq in re.findall(r'"@(\d+):\d+"', json.dumps(payload)):
            if (producer := by_seq.get(int(seq))) is not None:
                yield ref, producer
        name = payload.get("name") if isinstance(payload, dict) else None
        targets = knowledge[ref]["targets"]
        if op.get("kind") == "upsert_entity" and isinstance(name, str):
            if not any(kind == "entity" for kind, _ in targets):
                created[name] = ref
    for op in ops:
        for text in _statement_texts([op]):
            for name, creator in created.items():
                if mentions.text_contains_name(text, name):
                    yield str(op["operation_ref"]), creator


def _seq(op: dict[str, JsonValue]) -> int:
    seq = op.get("seq")
    return seq if isinstance(seq, int) else 0


def _merge(parts: list[Part]) -> Part:
    ops = sorted(
        (op for part in parts for op in part.ops),
        key=_seq,
    )
    records = {
        (item["kind"], item["id"]): item for part in parts for item in part.records
    }
    return Part(ops, [records[key] for key in sorted(records)])


def _split(
    inspection: DraftReviewInspection,
    previous_failure: str | None = None,
    answers: list[Answer] | None = None,
) -> list[Part]:
    """The parts to review: the whole draft when its operations and records
    fit one context with room for related knowledge, otherwise connected
    operations packed together up to that size."""
    reader = InProcessSubstrate()
    whole = _whole(inspection)
    if (
        _size(_base(reader, inspection, whole, previous_failure, answers)[0])
        <= _PART_BASE_LIMIT
    ):
        return [whole]
    parts: list[Part] = []
    for component in _components(inspection):
        if parts:
            merged = _merge([parts[-1], component])
            data, _ = _base(reader, inspection, merged, previous_failure, answers)
            if _size(data) <= _PART_BASE_LIMIT:
                parts[-1] = merged
                continue
        parts.append(component)
    return parts


def _size(data: dict[str, JsonValue]) -> int:
    return len(json.dumps(data, ensure_ascii=False))


def _record_read(
    reader: InProcessSubstrate, item: draft_review_store.Precondition
) -> Read:
    if item["kind"] == "entity":
        return _read(reader, "get_entity", {"id": item["id"]})
    return _read(reader, "get_statements", {"ids": [item["id"]]})


def _summary(ops: list[dict[str, JsonValue]]) -> list[JsonValue]:
    """What the operations outside a part add, for reference, within
    _OTHER_PARTS_LIMIT characters."""
    out: list[JsonValue] = []
    used = 0
    for op in ops:
        payload = op.get("payload")
        texts: list[JsonValue] = list(_statement_texts([op]))
        if isinstance(payload, dict) and isinstance(name := payload.get("name"), str):
            texts.append(name)
        item: dict[str, JsonValue] = {
            "operation_ref": op.get("operation_ref"),
            "kind": op.get("kind"),
            "texts": texts,
        }
        used += len(json.dumps(item, ensure_ascii=False))
        if used > _OTHER_PARTS_LIMIT:
            out.append({"omitted_operations": len(ops) - len(out)})
            break
        out.append(item)
    return out


def _base(
    reader: InProcessSubstrate,
    inspection: DraftReviewInspection,
    part: Part,
    previous_failure: str | None,
    answers: list[Answer] | None,
    position: tuple[int, int] = (1, 1),
) -> tuple[dict[str, JsonValue], list[Read]]:
    from . import server  # local import: server registers the review tools

    draft = dict(inspection["draft"])
    draft.pop("review_assessment", None)
    refs = part.refs
    draft["ops"] = list(part.ops)
    reads = [_record_read(reader, item) for item in part.records]
    schemas: dict[str, JsonValue] = {
        tool.__name__: _json_schema_for(tool)
        for tool in server.TOOLS
        if tool.__name__ in REVIEWABLE_OPERATIONS
    }
    existing_knowledge: list[JsonValue] = [read.result for read in reads]
    findings: list[JsonValue] = [
        {
            "operation_ref": item["operation_ref"],
            "kind": item["kind"],
            "finding": item["finding"],
        }
        for item in inspection["operation_findings"]
        if item["operation_ref"] in refs
    ]
    data: dict[str, JsonValue] = {
        "draft": draft,
        "operation_findings": findings,
        "existing_knowledge": existing_knowledge,
        "link_types": _read(reader, "list_link_types", {}).result,
        "correction_tool_schemas": schemas,
        "knowledge_scope": _KNOWLEDGE_SCOPE,
    }
    index, count = position
    if count > 1:
        data["review_part"] = {
            "part": index,
            "of": count,
            "scope": _PART_SCOPE,
            "other_parts": _summary(
                [op for op in _ops(inspection) if op["operation_ref"] not in refs]
            ),
        }
    if previous_failure:
        data["previous_attempt_failure"] = previous_failure
    if answers:
        data["answers_from_curators"] = [
            _json_value.validate_python(item.model_dump(mode="json"))
            for item in answers
        ]
    return data, reads


_KNOWLEDGE_SCOPE = (
    "existing_knowledge holds the records the draft touches, followed by "
    "the closest live statements to each new statement, best matches "
    "first. Each live record carries created_at and updated_at; the "
    "draft's created_at says when it was written. Supplied evidence, when "
    "present, comes from the producer: review_evidence for the whole "
    "draft, and each operation's evidence for that operation, citing what "
    "the producer checked in the product's code, UI or docs. draft.source, "
    "when present, names the merged pull request, merge commit and "
    "workflow run the draft documents. "
    "answers_from_curators, when present, holds answers a curator gave "
    "to earlier review questions; only these answers come from a "
    "curator."
)
_PART_SCOPE = (
    "The draft is too large for one review, so it is reviewed in connected "
    "parts, each in its own context. Assess and correct only the operations "
    "in draft.ops. other_parts lists what the rest of the draft adds; it is "
    "reviewed separately, so do not correct it, do not treat it as missing "
    "and do not add it again. The draft is applied only if every part is "
    "accepted."
)


def _context(
    inspection: DraftReviewInspection,
    previous_failure: str | None = None,
    answers: list[Answer] | None = None,
    part: Part | None = None,
    position: tuple[int, int] = (1, 1),
) -> tuple[str, list[Read]]:
    reader = InProcessSubstrate()
    part = part or _whole(inspection)
    data, reads = _base(reader, inspection, part, previous_failure, answers, position)
    existing_knowledge = data["existing_knowledge"]
    assert isinstance(existing_knowledge, list)  # built by _base
    if _size(data) > _CONTEXT_LIMIT:
        raise Refused(
            "Operations "
            + ", ".join(sorted(part.refs))
            + " depend on each other and need more than the "
            f"{_CONTEXT_LIMIT} characters one review may read; split them "
            "into smaller drafts."
        )
    seen = {item["id"] for item in part.records}
    draft = data["draft"]
    assert isinstance(draft, dict)  # built by _base
    for statement_id in _related_statement_ids(reader, draft):
        if statement_id in seen:
            continue
        seen.add(statement_id)
        read = _read(reader, "get_statements", {"ids": [statement_id]})
        existing_knowledge.append(read.result)
        if _size(data) > _CONTEXT_LIMIT:
            existing_knowledge.pop()
            break
        reads.append(read)
    return json.dumps(data, ensure_ascii=False), reads


def _part_contexts(
    inspection: DraftReviewInspection,
    previous_failure: str | None = None,
    answers: list[Answer] | None = None,
) -> list[PartContext]:
    parts = _split(inspection, previous_failure, answers)
    out = []
    for index, part in enumerate(parts, start=1):
        context, reads = _context(
            inspection, previous_failure, answers, part, (index, len(parts))
        )
        out.append(PartContext(part, context, reads))
    return out


def _stale(inspection: DraftReviewInspection) -> str | None:
    """Why the draft must not be applied over the knowledge it changes: a
    record it overwrites now says something written after its operation was,
    by a direct edit or by a newer draft applied since. A change an older
    draft wrote, even if applied later, is not newer knowledge."""
    from .server import draft_review  # local import: loads the server package

    conn = store.substrate_connection()
    for op in _ops(inspection):
        ref, kind, payload = _operations([op])[0]
        written = op.get("created_at")
        if not isinstance(written, str):
            continue
        for record_kind, identity in draft_review.overwritten_records(kind, payload):
            row = (
                store.get_statement(conn, identity)
                if record_kind == "statement"
                else store.get_entity_by_id(conn, identity)
            )
            if row is None:
                return (
                    f"Operation {ref} changes {record_kind} {identity}, which no "
                    "longer exists; the draft was written against older knowledge."
                )
            if _unchanged_by(kind, payload, row):
                continue
            authored = _authored((record_kind, identity), row)
            if authored is not None and authored > written:
                return (
                    f"Operation {ref} was written at {written}, but {record_kind} "
                    f"{identity} now holds a change written at {authored}. "
                    "Applying the draft could overwrite that newer knowledge; "
                    "submit the change again against the current knowledge."
                )
    return None


def _unchanged_by(kind: str, payload: dict[str, JsonValue], row: sqlite3.Row) -> bool:
    """Whether the operation would leave the record as it is."""
    if kind == "upsert_entity":
        description: str | None = row["description"]
        return payload.get("description") == description
    if kind in ("replace_text", "patch_statement"):
        return payload.get("text") in (None, row["text"]) and payload.get("kind") in (
            None,
            row["kind"],
        )
    return False


def _authored(key: RecordKey, row: sqlite3.Row) -> str | None:
    """When the record's current content was written: the operation time of
    the applied draft that last changed it, or the change itself."""
    from .server import draft_review  # local import: loads the server package

    changed = row["updated_at"] or row["created_at"]
    if not isinstance(changed, str):
        return None
    conn = drafts_store.connection()
    applied = conn.execute(
        "SELECT id FROM drafts WHERE decision = 'approved' AND decided_at >= ? "
        "ORDER BY decided_at",
        (changed,),
    ).fetchall()
    for draft in applied:
        for op in drafts_store.list_ops(conn, draft["id"]):
            if op["kind"] not in REVIEWABLE_OPERATIONS:
                continue
            payload = _payload.validate_json(op["payload_json"])
            if key in draft_review.overwritten_records(op["kind"], payload):
                return str(op["created_at"])
    return changed


def _estimated_cost(
    contexts: list[PartContext],
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings,
    instructions: ai_prompts.Snapshot,
) -> float | None:
    price = ai.pricing.price(settings.provider, settings.model)
    if price is None:
        return None
    system = len(draft_review_model.build_system_prompt(instructions.text))
    return sum(
        price.cost_usd(
            ai.Usage(
                input_tokens=(system + len(item.context)) // _CHARS_PER_TOKEN,
                output_tokens=limits.max_tokens,
            )
        )
        for item in contexts
    )


def _related_statement_ids(
    reader: InProcessSubstrate, draft: dict[str, JsonValue]
) -> list[str]:
    queries = _statement_texts(draft.get("ops"))
    if not queries:
        ops = json.dumps(draft.get("ops"), ensure_ascii=False)[:2000]
        queries = [f"{draft.get('title') or ''} {ops}"]
    rankings: list[list[str]] = []
    for query in queries:
        hits = _read(
            reader,
            "search_statements",
            {"query": query, "limit": _RELATED_PER_STATEMENT},
        ).result
        if not isinstance(hits, list):
            raise ValueError("related knowledge search returned an invalid result")
        rankings.append(
            [
                hit_id
                for hit in hits
                if isinstance(hit, dict) and isinstance(hit_id := hit.get("id"), str)
            ]
        )
    return [
        statement_id
        for rank in itertools.zip_longest(*rankings)
        for statement_id in rank
        if statement_id is not None
    ]


def _statement_texts(ops: JsonValue) -> list[str]:
    texts: list[str] = []
    for op in ops if isinstance(ops, list) else []:
        payload = op.get("payload") if isinstance(op, dict) else None
        if not isinstance(payload, dict):
            continue
        if isinstance(text := payload.get("text"), str):
            texts.append(text)
        statements = payload.get("statements")
        for item in statements if isinstance(statements, list) else []:
            if isinstance(item, dict) and isinstance(
                item_text := item.get("text"), str
            ):
                texts.append(item_text)
    return texts


@request_timing.tracked("background draft review")
def _execute(
    run: ReviewRun,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings | None = None,
    instructions: ai_prompts.Snapshot | None = None,
) -> None:
    from . import server  # local import: server registers the review tools

    try:
        principal = reviewer(_creator(inspection), settings.reviewer_id)
    except Exception as exc:
        _failed(run, str(exc))
        _futures.pop(run.run_id, None)
        return
    auth.current_principal.set(principal)
    try:
        with (
            server.model_loop_slot(),
            ai.usage.attributed(
                "draft_review", run_id=run.run_id, draft_id=run.draft_id
            ),
        ):
            instructions = instructions or ai_prompts.resolve("draft_review")
            run.prompt = instructions.reference()
            results, reads = _review(
                run,
                inspection,
                settings,
                limits or product_settings.get(product_settings.ReviewSettings),
                instructions,
            )
        _validate_corrections(
            [c for _, result in results for c in result.corrections], inspection
        )
        _record(run, results)
        run.knowledge_preconditions = _supporting_preconditions(inspection, reads)
        _finish(run, inspection, settings, reads)
        run.status = "completed"
        run.finished_at = timestamps.now()
        _save(run)
    except ai.usage.Paused as exc:
        run.status = "paused"
        run.detail = str(exc)
        run.finished_at = timestamps.now()
        _save(run)
    except Exception as exc:
        logger.warning(
            "internal review %s failed: %s: %s", run.run_id, type(exc).__name__, exc
        )
        _failed(run, str(exc))
        _follow_up(run, settings, systemic=isinstance(exc, ai.ModelError))
    finally:
        _futures.pop(run.run_id, None)


def _creator(inspection: DraftReviewInspection) -> str | None:
    creator = inspection["draft"].get("created_by")
    return creator if isinstance(creator, str) else None


def _unsupported(inspection: DraftReviewInspection) -> str | None:
    unsupported = sorted(
        {
            str(op.get("kind"))
            for op in _ops(inspection)
            if op.get("kind") not in REVIEWABLE_OPERATIONS
        }
    )
    if not unsupported:
        return None
    return (
        "Internal review cannot inspect the knowledge these operations "
        "affect: " + ", ".join(unsupported) + "."
    )


def _refusal(reason: str) -> Assessment:
    return Assessment(
        label="reject",
        rationale=reason,
        questions=[],
        corrections=[],
        contradictions=[],
    )


def _review(
    run: ReviewRun,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings,
    instructions: ai_prompts.Snapshot,
) -> tuple[list[tuple[Part, Assessment]], list[Read]]:
    """Each part's validated assessment, and every read the parts made.
    A draft the server refuses gets one rejection and no model call."""
    reason = _unsupported(inspection) or _stale(inspection)
    contexts: list[PartContext] = []
    if reason is None:
        try:
            contexts = _part_contexts(inspection, run.previous_failure, run.answers)
        except Refused as exc:
            reason = str(exc)
    if reason is None:
        cost = _estimated_cost(contexts, settings, limits, instructions)
        if cost is not None and cost > limits.max_cost_usd:
            reason = (
                f"Reviewing this draft could cost up to ${cost:.2f} in "
                f"{len(contexts)} parts, above the ${limits.max_cost_usd:g} a "
                "draft review may cost (Settings › Product › Draft review). "
                "Split it into smaller drafts."
            )
    if reason is not None:
        return [(_whole(inspection), _refusal(reason))], []
    results = []
    every = {str(op["operation_ref"]) for op in _ops(inspection)}
    for item in contexts:
        result = _assess(item.context, settings, limits, instructions)
        result = _without_redundant_tool_names(result, inspection)
        draft_review_model.validate_assessment(result)
        outside = [
            ref
            for correction in result.corrections
            if (ref := correction.operation_ref) in every - item.part.refs
        ]
        if outside:
            raise ValueError(
                "a part's correction names an operation of another part: "
                + ", ".join(outside)
            )
        results.append((item.part, result))
    reads: dict[str, Read] = {}
    for item in contexts:
        for read in item.reads:
            reads.setdefault(json.dumps([read.name, read.arguments]), read)
    return results, list(reads.values())


def _record(run: ReviewRun, results: list[tuple[Part, Assessment]]) -> None:
    """Combine the parts: any rejection rejects the draft with its parts'
    reasons, otherwise any question holds it, otherwise every part's
    corrections and contradictions apply together."""
    if len(results) == 1:
        [(_, result)] = results
        run.label = result.label
        run.rationale = result.rationale
        run.questions = result.questions
        run.corrections = result.corrections
        run.contradictions = result.contradictions
        run.parts = []
        return
    labels = [result.label for _, result in results]
    label: Label = (
        "reject"
        if "reject" in labels
        else "needs_context"
        if "needs_context" in labels
        else "changes_suggested"
        if any(result.corrections for _, result in results)
        else "good"
    )
    deciding = [
        (index, part, result)
        for index, (part, result) in enumerate(results, start=1)
        if result.label == label
    ]
    run.label = label
    run.rationale = (
        f"All {len(results)} parts of the draft fit; each part's assessment "
        "is listed with it."
        if label in ("good", "changes_suggested")
        else "\n\n".join(
            f"Part {index} of {len(results)} ({len(part.ops)} operations): "
            f"{result.rationale}"
            for index, part, result in deciding
        )
    )
    run.questions = [q for _, _, result in deciding for q in result.questions]
    applies = label == "changes_suggested"
    run.corrections = [c for _, r in results for c in r.corrections] if applies else []
    run.contradictions = (
        [c for _, r in results for c in r.contradictions] if applies else []
    )
    run.parts = [
        PartReview(
            operation_refs=[str(op["operation_ref"]) for op in part.ops],
            label=result.label,
            rationale=result.rationale,
            questions=result.questions,
            corrections=result.corrections,
            contradictions=result.contradictions,
        )
        for part, result in results
    ]


def _assess(
    context: str,
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings | None = None,
    instructions: ai_prompts.Snapshot | None = None,
) -> Assessment:
    if RUNNER is not None:
        return RUNNER(context)
    return draft_review_model.assess(
        context,
        model=settings.model,
        provider=settings.provider,
        limits=limits,
        reasoning_effort=settings.reasoning_effort,
        instructions=instructions,
    )


def _validate_snapshot(inspection: DraftReviewInspection, reads: list[Read]) -> None:
    from . import server  # local import: server registers the review tools

    draft_id = inspection["draft"]["id"]
    if not isinstance(draft_id, str):
        raise ValueError("invalid draft identity")
    current = server.inspect_draft_review(draft_id)
    if current["draft"].get("status") != "submitted":
        raise ValueError("draft is no longer submitted")
    if current["draft_revision"] != inspection["draft_revision"]:
        raise ValueError("draft or supplied evidence changed during review; rerun")
    if current["knowledge_preconditions"] != inspection["knowledge_preconditions"]:
        raise ValueError("affected knowledge changed during review; rerun")
    reader = InProcessSubstrate()
    for read in reads:
        if _read(reader, read.name, read.arguments).result != read.result:
            raise ValueError("supporting knowledge changed during review; rerun")


def _mutation_authority(
    run: ReviewRun,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
) -> None:
    if run.mode != "review-and-apply" or mode() != "review-and-apply":
        raise ValueError("automatic action disabled by review mode")
    if draft_review_settings.load() != settings:
        raise ValueError("review configuration changed; rerun before automatic action")
    principal = reviewer(_creator(inspection), settings.reviewer_id)
    auth.current_principal.set(principal)


def _finish(
    run: ReviewRun,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
    reads: list[Read],
) -> None:
    from . import server  # local import: server registers the review tools
    from .server import draft_application

    with store.write_lock():
        _validate_snapshot(inspection, reads)
        from . import alias_suggestions

        if alias_suggestions.contains(
            drafts_store.list_ops(drafts_store.connection(), run.draft_id)
        ):
            run.detail = (
                "Advisory assessment only; alias suggestions require human review."
            )
            return
        if run.mode != "review-and-apply" or draft_review_settings.load() != settings:
            run.detail = "Advisory assessment only; automatic action disabled by mode or changed settings."
            return
        _mutation_authority(run, inspection, settings)
        if not draft_application._reviewed_apply_enabled():
            run.detail = "Reviewed application gate is disabled; no automatic changes."
            return
        if run.label == "needs_context":
            _ask_person(run, inspection, reads)
            return
        with store.transaction(drafts_store.connection()):
            _mutation_authority(run, inspection, settings)
            for correction in run.corrections:
                _mutation_authority(run, inspection, settings)
                _correct(run.draft_id, correction)
            final = server.inspect_draft_review(run.draft_id)
            if final["operation_findings"]:
                raise ValueError(
                    "the corrected draft still has operation findings: "
                    + "; ".join(
                        f"{item['operation_ref']}: {item['finding']}"
                        for item in final["operation_findings"]
                    )
                )
            _check_correction_knowledge(inspection, final, reads)
            _mutation_authority(run, inspection, settings)
            outcome: Literal["rejected", "refined", "accepted"] = (
                "rejected"
                if run.label == "reject"
                else "refined"
                if run.corrections
                else "accepted"
            )
            review = server.record_draft_review(
                run.draft_id,
                outcome,
                run.rationale or "",
                final["draft_revision"],
                _supporting_preconditions(final, reads),
            )
            run.review_id = review["review_id"]
            run.draft_revision = final["draft_revision"]
            run.knowledge_preconditions = _supporting_preconditions(final, reads)
            draft_review_store.save(drafts_store.connection(), run)
        if run.label == "reject":
            run.application = "rejected"
            run.detail = "Draft rejected by the configured internal reviewer."
            _report_gap(
                run.draft_id,
                f"Draft {run.draft_id} was rejected by the internal reviewer: "
                f"{run.rationale}",
            )
            return
        _mutation_authority(run, inspection, settings)
        receipt = server.apply_reviewed_draft(run.draft_id, review["review_id"])
        run.application = "applied"
        run.detail = (
            f"Applied through reviewed application {receipt['application_id']}."
        )
        for contradiction in run.contradictions:
            _report_gap(
                run.draft_id,
                f"Draft {run.draft_id} contradicted live statement "
                f"{contradiction.statement_id}; the internal reviewer resolved it "
                f"in favour of the draft: {contradiction.resolution}",
                statement_id=contradiction.statement_id,
            )


def _ask_person(
    run: ReviewRun, inspection: DraftReviewInspection, reads: list[Read]
) -> None:
    from . import server  # local import: server registers the review tools

    conn = drafts_store.connection()
    with store.transaction(conn):
        review = server.record_draft_review(
            run.draft_id,
            "needs_context",
            run.rationale or "",
            inspection["draft_revision"],
            _supporting_preconditions(inspection, reads),
            run.questions,
        )
        run.review_id = review["review_id"]
        run.application = "needs_human"
        run.detail = draft_review_store.WAITING_FOR_PERSON
        draft_review_store.save(conn, run)
    _report_gap(
        run.draft_id,
        f"Draft {run.draft_id} needs a person to answer the internal reviewer: "
        + " ".join(run.questions),
    )


def answer(
    draft_id: str, run_id: str, text: str, principal: auth.Principal
) -> ReviewRun:
    """Review the draft again with a curator's answer to the questions run
    `run_id` asked."""
    return start(
        draft_id,
        rerun=True,
        answer=Answer(
            run_id=run_id, questions=[], answer=text.strip(), answered_by=principal.id
        ),
    )


def _follow_up(
    run: ReviewRun, settings: draft_review_settings.Snapshot, *, systemic: bool
) -> None:
    # Nobody approves drafts by hand, so a failed automatic review must not
    # leave its draft queued: run it once more, then reject it unless the
    # failure was the model provider's rather than the draft's. A run that
    # already recorded its review failed while applying, which
    # apply_reviewed_draft recovers.
    from .server import (
        draft_application,
    )  # local import: loading it loads the server package

    if (
        run.mode != "review-and-apply"
        or mode() != "review-and-apply"
        or run.review_id is not None
        or run.application != "unapplied"
        or not draft_application._reviewed_apply_enabled()
    ):
        return
    try:
        if run.attempt == 1:
            start(
                run.draft_id,
                rerun=True,
                attempt=2,
                retries=run.retries,
                previous_failure=run.detail,
            )
        elif not systemic:
            _reject(run, settings)
    except Exception:
        logger.exception("could not follow up failed review %s", run.run_id)


def _reject(run: ReviewRun, settings: draft_review_settings.Snapshot) -> None:
    from . import server  # local import: server registers the review tools

    reason = f"Automatic review failed twice: {run.detail}"
    with store.write_lock():
        inspection = server.inspect_draft_review(run.draft_id)
        if inspection["draft"].get("status") != "submitted":
            return
        _mutation_authority(run, inspection, settings)
        review = server.record_draft_review(
            run.draft_id,
            "rejected",
            reason,
            inspection["draft_revision"],
            inspection["knowledge_preconditions"],
        )
        run.review_id = review["review_id"]
        run.application = "rejected"
        run.detail = reason
        _save(run)
    _report_gap(run.draft_id, f"Draft {run.draft_id} was rejected: {reason}")


def _report_gap(draft_id: str, text: str, *, statement_id: str | None = None) -> None:

    with store.transaction(store.substrate_connection()):
        store.create_knowledge_gap(
            store.substrate_connection(),
            text,
            draft_id=draft_id,
            statement_id=statement_id,
        )


def _correct(draft_id: str, correction: draft_review_store.Correction) -> None:
    from . import server  # local import: server registers the review tools

    revision = server.inspect_draft_review(draft_id)["draft_revision"]
    if correction.action == "strike":
        if (
            not correction.operation_ref
            or correction.payload_json
            or correction.tool_name
        ):
            raise ValueError("strike requires only operation_ref")
        server.strike_draft_operation(draft_id, correction.operation_ref, revision)
        return
    payload = _correction_payload(correction)
    if correction.action == "revise":
        if not correction.operation_ref or correction.tool_name:
            raise ValueError("revise requires operation_ref and payload_json")
        server.revise_draft_operation(
            draft_id, correction.operation_ref, payload, revision
        )
    else:
        if not correction.tool_name or correction.operation_ref:
            raise ValueError("append requires tool_name and payload_json")
        server.append_draft_correction(
            draft_id, correction.tool_name, payload, revision
        )


def _check_correction_knowledge(
    before: DraftReviewInspection, after: DraftReviewInspection, reads: list[Read]
) -> None:
    known = {item["id"] for item in before["knowledge_preconditions"]}

    def collect(value: JsonValue) -> None:
        if isinstance(value, dict):
            identity = value.get("id")
            if isinstance(identity, str):
                known.add(identity)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for read in reads:
        collect(read.result)
    if any(item["id"] not in known for item in after["knowledge_preconditions"]):
        raise ValueError(
            "correction touches knowledge not inspected by review; refine manually"
        )


def _supporting_preconditions(
    inspection: DraftReviewInspection, reads: list[Read]
) -> list[draft_review_store.Precondition]:
    from .server import (
        draft_review,
    )  # local import: server defines fingerprint contracts

    conditions = {
        (item["kind"], item["id"]): item
        for item in inspection["knowledge_preconditions"]
    }
    for read in reads:
        if read.name == "get_entity" and isinstance(read.result, dict):
            identity = read.result.get("id")
            if isinstance(identity, str):
                conditions[("entity", identity)] = {
                    "kind": "entity",
                    "id": identity,
                    "fingerprint": draft_review._fingerprint(read.result),
                }
            continue
        if read.name != "get_statements" or not isinstance(read.result, dict):
            continue
        statements = read.result.get("statements")
        if not isinstance(statements, list):
            continue
        for statement in statements:
            if not isinstance(statement, dict):
                continue
            identity = statement.get("id")
            if not isinstance(identity, str):
                continue
            conditions[("statement", identity)] = {
                "kind": "statement",
                "id": identity,
                "fingerprint": draft_review._fingerprint(
                    {"statements": [statement], "missing": []}
                ),
            }
    return [conditions[key] for key in sorted(conditions)]


def _without_redundant_tool_names(
    result: Assessment, inspection: DraftReviewInspection
) -> Assessment:
    """Reviewers often name the tool of the operation they revise or strike.
    That restates the operation's own kind, so it is dropped rather than
    failing the whole review."""
    ops = inspection["draft"].get("ops")
    kinds = {
        op["operation_ref"]: op.get("kind")
        for op in (ops if isinstance(ops, list) else [])
        if isinstance(op, dict) and isinstance(op.get("operation_ref"), str)
    }
    corrections = [
        correction.model_copy(update={"tool_name": None})
        if correction.action != "append"
        and correction.operation_ref is not None
        and correction.tool_name is not None
        and kinds.get(correction.operation_ref) == correction.tool_name
        else correction
        for correction in result.corrections
    ]
    return result.model_copy(update={"corrections": corrections})


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _unresolved_reference(
    name: str, payload: dict[str, JsonValue], ops: list[JsonValue]
) -> str | None:
    batches: dict[int, int] = {}
    for op in ops:
        if isinstance(op, dict) and op.get("kind") == "upsert_statements":
            seq, op_payload = op.get("seq"), op.get("payload")
            items = (
                op_payload.get("statements") if isinstance(op_payload, dict) else None
            )
            if isinstance(seq, int) and isinstance(items, list):
                batches[seq] = len(items)
    statements = payload.get("statements")
    size = len(statements) if isinstance(statements, list) else 0
    for value in _strings(payload):
        if sibling := re.fullmatch(r"@(\d+)", value):
            if name != "upsert_statements":
                return (
                    f"{value} names a statement of the same upsert_statements "
                    "batch; outside a batch write @<seq>:<index>"
                )
            if int(sibling[1]) >= size:
                return f"{value} is past the end of its batch"
        elif other := re.fullmatch(r"@(\d+):(\d+)", value):
            seq, index = int(other[1]), int(other[2])
            if index >= batches.get(seq, 0):
                return (
                    f"{value} names no statement: the draft has no "
                    f"upsert_statements operation at seq {seq} with that index"
                )
    return None


def _validate_corrections(
    corrections: list[draft_review_store.Correction],
    inspection: DraftReviewInspection,
) -> None:
    from . import server  # local import: validate registered tool contracts
    from .server import draft_review

    ops = inspection["draft"].get("ops")
    if not isinstance(ops, list):
        raise ValueError("draft has no operation list")
    originals = {
        op["operation_ref"]: op
        for op in ops
        if isinstance(op, dict) and isinstance(op.get("operation_ref"), str)
    }
    struck = {c.operation_ref for c in corrections if c.action == "strike"}
    if (
        originals
        and struck >= originals.keys()
        and all(c.action == "strike" for c in corrections)
    ):
        raise ValueError(
            "the corrections strike every operation, so nothing would land; "
            "a draft that should not land is a reject"
        )
    tools_by_name = {wrapper.__name__: wrapper for wrapper in server.TOOLS}
    changed: set[str] = set()
    for correction in corrections:
        reference = correction.operation_ref
        name: JsonValue
        if correction.action == "append":
            name = correction.tool_name
            if reference is not None or not name or name not in REVIEWABLE_OPERATIONS:
                raise ValueError("append correction needs a supported tool_name only")
        else:
            if (
                reference is None
                or reference not in originals
                or reference in changed
                or correction.tool_name is not None
            ):
                raise ValueError("correction needs an existing, unique operation_ref")
            changed.add(reference)
            name = originals[reference].get("kind")
        if correction.action == "strike":
            if correction.payload_json is not None:
                raise ValueError("strike correction cannot carry a payload")
            continue
        payload = _correction_payload(correction)
        if name not in REVIEWABLE_OPERATIONS:
            raise ValueError(
                "correction affects knowledge internal review cannot inspect"
            )
        if (
            not isinstance(name, str)
            or name not in server._ORIG_SIGNATURES
            or name not in tools_by_name
        ):
            raise ValueError("correction names an unsupported tool")
        signature = server._ORIG_SIGNATURES[name]
        signature.bind(**payload)
        for key, value in payload.items():
            TypeAdapter(tools_by_name[name].__annotations__[key]).validate_python(
                value, strict=True
            )
        if draft_review._nested_parameter_findings(name, payload):
            raise ValueError("correction payload has unsupported nested parameters")
        if problem := _unresolved_reference(name, payload, ops):
            raise ValueError(problem)
