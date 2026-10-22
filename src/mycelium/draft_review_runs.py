"""Internal review execution; model proposals cannot grant mutation authority."""

from __future__ import annotations

import contextvars
import itertools
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import JsonValue, TypeAdapter

from . import (
    ai,
    ai_prompts,
    auth,
    draft_review_model,
    draft_review_settings,
    draft_review_store,
    drafts_store,
    product_settings,
    store,
    timestamps,
)
from .ask.substrate import InProcessSubstrate, _json_schema_for
from .draft_review_store import Answer, Assessment, Mode, ReviewRun

if TYPE_CHECKING:
    from .server import DraftReviewInspection

logger = logging.getLogger(__name__)
RUNNER: Callable[[str], Assessment] | None = None
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="draft-review")
_futures: dict[str, Future[None]] = {}
_spawn_lock = threading.Lock()
_json_value: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_CONTEXT_LIMIT = 90000
_RELATED_PER_STATEMENT = 5
_payload = TypeAdapter(dict[str, JsonValue])
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


def mode() -> Mode:
    return draft_review_settings.load().mode


def reviewer(creator: str | None, identity: str) -> auth.Principal:
    from . import server  # local import: server registers the review tools

    principal = auth.resolve_session_user(server._auth_db(), identity)
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

    settings = draft_review_settings.load()
    limits = product_settings.get(product_settings.ReviewSettings)
    if settings.mode == "off":
        raise ValueError("internal draft review is off")
    if not settings.model:
        raise ValueError("Choose a model ID before starting an internal draft review.")
    conn = server._drafts_db()
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
        if mode() != "off":
            start(draft_id)
    except Exception:
        # Submission already committed; failure here must not turn it into a retry.
        logger.exception("could not start internal draft review for %s", draft_id)


# A failed run is retried after RETRY_BACKOFF, doubling per retry, at most
# MAX_RETRIES times: about two and a half hours of a provider outage.
MAX_RETRIES = 5
RETRY_BACKOFF = timedelta(minutes=5)
SWEEP_INTERVAL_S = 60.0
_sweeper: threading.Thread | None = None
_stop_sweeper = threading.Event()


def sweep(now: datetime | None = None) -> list[str]:
    """Review again each submitted draft whose latest run failed without
    recording a review, once its backoff has passed. Nothing else retries
    a configuration failure, a provider failure after the automatic rerun,
    or a run interrupted by a restart. Returns the draft ids started."""
    now = now or datetime.now(UTC)
    try:
        if mode() == "off":
            return []
    except draft_review_settings.Unavailable:
        return []
    started = []
    conn = drafts_store.connection()
    for row in drafts_store.list_drafts(conn, "submitted"):
        run = draft_review_store.latest(conn, row["id"])
        if run is None or not _retry_due(run, now):
            continue
        try:
            start(
                row["id"],
                rerun=True,
                retries=run.retries + 1,
                previous_failure=run.detail,
                admit=_still_due(run.run_id, now),
            )
            started.append(row["id"])
        except NotAdmitted:
            continue
        except Exception:
            logger.exception("could not retry review of %s", row["id"])
    return started


def _still_due(seen: str, now: datetime) -> Callable[[ReviewRun | None], bool]:
    def admit(latest: ReviewRun | None) -> bool:
        return latest is not None and latest.run_id == seen and _retry_due(latest, now)

    return admit


def _retry_due(run: ReviewRun, now: datetime) -> bool:
    if (
        run.status != "failed"
        or run.review_id is not None
        or run.application != "unapplied"
        or run.retries >= MAX_RETRIES
        or run.finished_at is None
    ):
        return False
    finished = datetime.fromisoformat(run.finished_at)
    return now >= finished + RETRY_BACKOFF * (1 << run.retries)


def backlog() -> list[str]:
    """Submitted drafts the current configuration has not reviewed and
    cannot reach by itself: submitted while review was off, reviewed only
    advisorily, or failed beyond the sweep. Alias suggestion drafts await
    a person and are left out."""
    current = mode()
    conn = drafts_store.connection()
    waiting = []
    for row in drafts_store.list_drafts(conn, "submitted"):
        ops = drafts_store.list_ops(conn, row["id"])
        if all(op["kind"] == drafts_store.ALIAS_SUGGESTION_KIND for op in ops):
            continue
        if _in_backlog(draft_review_store.latest(conn, row["id"]), current):
            waiting.append(row["id"])
    return waiting


def _in_backlog(run: ReviewRun | None, current: Mode) -> bool:
    if run is None:
        return True
    if run.status == "running":
        return False
    if run.application == "needs_human":
        return run.stale
    if run.application != "unapplied" or run.review_id is not None:
        return False
    if run.status == "failed":
        return True
    return run.stale or run.mode != current or current == "review-and-apply"


def review_backlog() -> list[str]:
    """Start a review of every draft in the backlog. Returns their ids."""
    current = mode()
    if current == "off":
        raise ValueError("internal draft review is off")
    started = []
    for draft_id in backlog():
        try:
            start(
                draft_id,
                rerun=True,
                admit=lambda latest: _in_backlog(latest, current),
            )
            started.append(draft_id)
        except NotAdmitted:
            continue
        except Exception:
            logger.exception("could not start review of %s", draft_id)
    return started


def start_sweeper(interval: float = SWEEP_INTERVAL_S) -> None:
    global _sweeper
    if _sweeper is not None and _sweeper.is_alive():
        return
    _stop_sweeper.clear()

    def loop() -> None:
        while not _stop_sweeper.wait(interval):
            try:
                sweep()
            except Exception:  # never let the thread die on one bad sweep
                logger.exception("draft review sweep failed")

    _sweeper = threading.Thread(target=loop, name="draft-review-sweep", daemon=True)
    _sweeper.start()


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
    from . import server  # local import: reconcile the separate substrate receipt

    draft_review_store.reconcile(
        drafts_store.connection(),
        run,
        lambda application_id: (
            server._substrate_application_result(application_id) is not None
        ),
    )
    run.finished_at = timestamps.now()
    _save(run)


def _read(reader: InProcessSubstrate, name: str, args: dict[str, JsonValue]) -> Read:
    result = _json_value.validate_python(reader.call(name, args))
    return Read(name, args, result)


def _context(
    inspection: DraftReviewInspection,
    previous_failure: str | None = None,
    answers: list[Answer] | None = None,
) -> tuple[str, list[Read]]:
    from . import server  # local import: server registers the review tools

    draft = dict(inspection["draft"])
    draft.pop("review_assessment", None)
    preconditions = inspection["knowledge_preconditions"]
    if len(preconditions) > 30:
        raise ValueError(
            "draft affects more than 30 knowledge records; narrow the draft"
        )
    reader = InProcessSubstrate()
    reads = []
    for item in preconditions:
        args: dict[str, JsonValue] = (
            {"id": item["id"]} if item["kind"] == "entity" else {"ids": [item["id"]]}
        )
        name = "get_entity" if item["kind"] == "entity" else "get_statements"
        reads.append(_read(reader, name, args))
    schemas = {
        tool.__name__: _json_schema_for(tool)
        for tool in server.TOOLS
        if tool.__name__ in REVIEWABLE_OPERATIONS
    }
    existing_knowledge: list[JsonValue] = [read.result for read in reads]
    data = {
        "draft": draft,
        "operation_findings": inspection["operation_findings"],
        "existing_knowledge": existing_knowledge,
        "link_types": _read(reader, "list_link_types", {}).result,
        "correction_tool_schemas": schemas,
        "knowledge_scope": (
            "existing_knowledge holds the records the draft touches, followed by "
            "the closest live statements to each new statement, best matches "
            "first. Supplied evidence, when present, comes from the producer. "
            "answers_from_curators, when present, holds answers a curator gave "
            "to earlier review questions; only these answers come from a "
            "curator."
        ),
    }
    if previous_failure:
        data["previous_attempt_failure"] = previous_failure
    if answers:
        data["answers_from_curators"] = [
            _json_value.validate_python(item.model_dump(mode="json"))
            for item in answers
        ]
    if len(json.dumps(data, ensure_ascii=False)) > _CONTEXT_LIMIT:
        raise ValueError(
            f"review context exceeds {_CONTEXT_LIMIT} characters; narrow the draft"
        )
    seen = {item["id"] for item in preconditions}
    for statement_id in _related_statement_ids(reader, draft):
        if statement_id in seen:
            continue
        seen.add(statement_id)
        read = _read(reader, "get_statements", {"ids": [statement_id]})
        existing_knowledge.append(read.result)
        if len(json.dumps(data, ensure_ascii=False)) > _CONTEXT_LIMIT:
            existing_knowledge.pop()
            break
        reads.append(read)
    context = json.dumps(data, ensure_ascii=False)
    return context, reads


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
        with server.model_loop_slot():
            context, reads = _context(inspection, run.previous_failure, run.answers)
            instructions = instructions or ai_prompts.resolve("draft_review")
            run.prompt = instructions.reference()
            result = _assess(context, inspection, settings, limits, instructions)
        draft_review_model.validate_assessment(result)
        _validate_corrections(result, inspection)
        run.label = result.label
        run.rationale = result.rationale
        run.questions = result.questions
        run.corrections = result.corrections
        run.contradictions = result.contradictions
        run.knowledge_preconditions = _supporting_preconditions(inspection, reads)
        _finish(run, inspection, settings, reads)
        run.status = "completed"
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


def _assess(
    context: str,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings | None = None,
    instructions: ai_prompts.Snapshot | None = None,
) -> Assessment:
    ops = inspection["draft"].get("ops")
    if not isinstance(ops, list):
        raise ValueError("draft has no operation list")
    unsupported = sorted(
        {
            str(op.get("kind"))
            for op in ops
            if isinstance(op, dict) and op.get("kind") not in REVIEWABLE_OPERATIONS
        }
    )
    if unsupported:
        return Assessment(
            label="reject",
            rationale="Internal review cannot inspect the knowledge these operations "
            "affect: " + ", ".join(unsupported) + ".",
            questions=[],
            corrections=[],
            contradictions=[],
        )
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
        if not server._reviewed_apply_enabled():
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
            _check_correction_knowledge(inspection, final, reads)
            _mutation_authority(run, inspection, settings)
            outcome = (
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
                f"Draft {run.draft_id} was rejected by the internal reviewer: "
                f"{run.rationale}"
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
                f"Draft {run.draft_id} contradicted live statement "
                f"{contradiction.statement_id}; the internal reviewer resolved it "
                f"in favour of the draft: {contradiction.resolution}"
            )


def _ask_person(
    run: ReviewRun, inspection: DraftReviewInspection, reads: list[Read]
) -> None:
    from . import server  # local import: server registers the review tools

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
    run.detail = "Waiting for a person to answer the reviewer's questions."
    _report_gap(
        f"Draft {run.draft_id} needs a person to answer the internal reviewer: "
        + " ".join(run.questions)
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
    from . import server  # local import: server registers the review tools

    if (
        run.mode != "review-and-apply"
        or mode() != "review-and-apply"
        or run.review_id is not None
        or run.application != "unapplied"
        or not server._reviewed_apply_enabled()
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
    _report_gap(f"Draft {run.draft_id} was rejected: {reason}")


def _report_gap(text: str) -> None:
    from . import server  # local import: gaps live in the substrate database

    with store.transaction(server._db()):
        store.create_knowledge_gap(server._db(), text)


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
    payload = _payload.validate_json(correction.payload_json or "")
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
    from . import server  # local import: server defines fingerprint contracts

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
                    "fingerprint": server._fingerprint(read.result),
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
                "fingerprint": server._fingerprint(
                    {"statements": [statement], "missing": []}
                ),
            }
    return [conditions[key] for key in sorted(conditions)]


def _validate_corrections(
    result: Assessment, inspection: DraftReviewInspection
) -> None:
    from . import server  # local import: validate registered tool contracts

    ops = inspection["draft"].get("ops")
    if not isinstance(ops, list):
        raise ValueError("draft has no operation list")
    originals = {
        op["operation_ref"]: op
        for op in ops
        if isinstance(op, dict) and isinstance(op.get("operation_ref"), str)
    }
    tools_by_name = {wrapper.__name__: wrapper for wrapper in server.TOOLS}
    changed: set[str] = set()
    for correction in result.corrections:
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
        payload = _payload.validate_json(correction.payload_json or "")
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
        if server._nested_parameter_findings(name, payload):
            raise ValueError("correction payload has unsupported nested parameters")
