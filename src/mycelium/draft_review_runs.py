"""Internal review execution; model proposals cannot grant mutation authority."""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import JsonValue, TypeAdapter

from . import (
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
from .draft_review_store import Assessment, Mode, ReviewRun

if TYPE_CHECKING:
    from .server import DraftReviewInspection

logger = logging.getLogger(__name__)
RUNNER: Callable[[str], Assessment] | None = None
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="draft-review")
_futures: dict[str, Future[None]] = {}
_spawn_lock = threading.Lock()
_json_value = TypeAdapter(JsonValue)
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


def start(draft_id: str, *, rerun: bool = False) -> ReviewRun:
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
        if previous and (previous.status == "running" or not rerun):
            return previous
        active = conn.execute(
            "SELECT id FROM draft_review_runs WHERE draft_id = ? AND status = 'running'",
            (draft_id,),
        ).fetchone()
        if active:
            return draft_review_store.get(conn, active["id"])
        run = draft_review_store.new(draft_id, settings.mode, int(row["revision"]))
        run.provider = settings.provider
        run.model = settings.model
        run.reviewer_id = settings.reviewer_id
        run.settings_revision = settings.revision
        run.model_settings_revision = settings.model_revision
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
            context.run, _execute, run, inspection, settings, limits
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


def wait_all(timeout: float = 10) -> None:
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


def _context(inspection: DraftReviewInspection) -> tuple[str, list[Read]]:
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
    query = str(draft.get("title") or "")
    ops = draft.get("ops")
    if isinstance(ops, list):
        query += " " + json.dumps(ops, ensure_ascii=False)[:2000]
    search = _read(reader, "search_statements", {"query": query, "limit": 12})
    hits = search.result
    if not isinstance(hits, list):
        raise ValueError("related knowledge search returned an invalid result")
    ids = [
        hit["id"]
        for hit in hits
        if isinstance(hit, dict) and isinstance(hit.get("id"), str)
    ]
    if ids:
        reads.append(_read(reader, "get_statements", {"ids": ids}))
    schemas = {
        tool.__name__: _json_schema_for(tool)
        for tool in server.TOOLS
        if tool.__name__ in REVIEWABLE_OPERATIONS
    }
    data = {
        "draft": draft,
        "operation_findings": inspection["operation_findings"],
        "existing_knowledge": [read.result for read in reads],
        "correction_tool_schemas": schemas,
        "evidence_limitations": (
            "Only supplied evidence and these knowledge records are available. "
            "PR provenance and URLs do not provide source contents. Search is bounded "
            "to 12 related statements; unestablished claims require questions."
        ),
    }
    context = json.dumps(data, ensure_ascii=False)
    if len(context) > 90000:
        raise ValueError("review context exceeds 90000 characters; narrow the draft")
    return context, reads


def _execute(
    run: ReviewRun,
    inspection: DraftReviewInspection,
    settings: draft_review_settings.Snapshot,
    limits: product_settings.ReviewSettings | None = None,
) -> None:
    from . import server  # local import: server registers the review tools

    try:
        principal = reviewer(_creator(inspection), settings.reviewer_id)
        auth.current_principal.set(principal)
        with server.model_loop_slot():
            context, reads = _context(inspection)
            result = _assess(context, inspection, settings, limits)
        draft_review_model.validate_assessment(result)
        _validate_corrections(result, inspection)
        run.label = result.label
        run.rationale = result.rationale
        run.questions = result.questions
        run.corrections = result.corrections
        run.knowledge_preconditions = _supporting_preconditions(inspection, reads)
        _finish(run, inspection, settings, reads)
        run.status = "completed"
        run.finished_at = timestamps.now()
        _save(run)
    except Exception as exc:
        logger.warning("internal review %s failed: %s", run.run_id, type(exc).__name__)
        _failed(run, str(exc))
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
            label="needs_context",
            rationale="Internal review cannot inspect all knowledge affected by these operations.",
            questions=[
                "Can a curator inspect and resolve these operations manually: "
                + ", ".join(unsupported)
                + "?"
            ],
            corrections=[],
        )
    if RUNNER is not None:
        return RUNNER(context)
    return draft_review_model.assess(
        context, model=settings.model, provider=settings.provider, limits=limits
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
        if run.mode != "review-and-apply" or draft_review_settings.load() != settings:
            run.detail = "Advisory assessment only; automatic action disabled by mode or changed settings."
            return
        _mutation_authority(run, inspection, settings)
        if run.label == "needs_context":
            run.detail = "Missing evidence; answer the questions and rerun."
            return
        if not server._reviewed_apply_enabled():
            run.detail = "Reviewed application gate is disabled; no automatic changes."
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
            return
        _mutation_authority(run, inspection, settings)
        receipt = server.apply_reviewed_draft(run.draft_id, review["review_id"])
        run.application = "applied"
        run.detail = (
            f"Applied through reviewed application {receipt['application_id']}."
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
            if not isinstance(statement, dict) or not isinstance(
                statement.get("id"), str
            ):
                continue
            identity = statement["id"]
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
        if correction.action == "append":
            name = correction.tool_name
            if reference is not None or not name or name not in REVIEWABLE_OPERATIONS:
                raise ValueError("append correction needs a supported tool_name only")
        else:
            if (
                reference not in originals
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
