"""Documentation written by an outside agent instead of a server model.

With External agent selected for documentation, a run queues an
`agent_tasks` task rather than starting a model loop. The agent gets what the
loop's writer would: the system prompt built from the doctrine and the
profile's guidance, exposure rules and template, and the opening message
with the anchor and recon reads. Those come from the loop's own `_open`, so
the brief cannot drift from an internal run's.

Every read goes through `read`, inside the profile's audience boundary
(`audience_scope`), and is recorded as the internal loop records its reads.
A submission is the `emit_document` input and passes the loop's gates: it
cites only statements this task read and its audience may see, uses no
internal vocabulary and places only media it was offered. A grounded document
is then reviewed, by the server's reviewer on the documentation provider or,
when the setting says so, by a second agent that is not the writer. Refusals
come back as findings, as many times as the internal loop allows. What is
finally kept or refused is recorded by the same code that records an internal
run (`doc_runs.record_result`).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import time
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter

from .. import (
    agent_tasks,
    ai,
    ai_prompts,
    audience_scope,
    documentation_profiles,
    media,
)
from ..agent_tasks import Finding, ReadResult, Submitted, Task
from ..ask.substrate import InProcessSubstrate
from ..model_settings import AgentReview
from . import loop, prompts
from .config import DOCTRINE_NAME, DocgenConfig
from .schema import (
    DocgenResult,
    DocumentWritten,
    NothingWritten,
    ReviewCheck,
    ReviewRecord,
    RevisionTarget,
)
from .tools import (
    _EMIT_SCHEMA,
    READ_TOOLS,
    build_tools,
    emit_tool_def,
    parse_emit_input,
    parse_review_input,
    review_tool_def,
)
from .trace import ReviewNote, TraceBuilder

_json = TypeAdapter(dict[str, JsonValue])


class Request(BaseModel):
    """What the run was asked, kept on its task until the work is done."""

    run_id: str
    prompt: str
    guideline_set: str
    document_type: str
    #: The anchor the request named: with the pair, the document's identity.
    anchor_entity_id: str | None
    #: The concept the writer starts from, also for a revision.
    writer_anchor: str | None
    target: RevisionTarget | None
    review_notes: list[ReviewNote]
    review: AgentReview
    #: The server reviewer's model, captured with the request.
    provider: ai.Provider
    model: str
    reasoning_effort: ai.ReasoningEffort | None


class Pending(BaseModel):
    """A grounded document waiting for an agent's review."""

    title: str
    body: str
    statement_ids: list[str]
    gaps: list[str]


class WritingState(BaseModel):
    request: Request
    #: What the opening reads put in front of the writer.
    opening: list[str] = []
    #: What the current claimant has read, the opening included.
    retrieved: list[str] = []
    offered_media: list[str] = []
    reader: str | None = None
    emit_blocks: int = 0
    malformed: int = 0
    #: Documents put to a reviewer and refused.
    reviews: int = 0
    pending: Pending | None = None


class ReviewState(BaseModel):
    writer_task: str
    check_exposure: bool
    cited_statements: dict[str, str] | None
    malformed: int = 0


def _dump(model: BaseModel) -> dict[str, JsonValue]:
    return _json.validate_python(model.model_dump(mode="json"))


# --- queueing ------------------------------------------------------------------


def queue(conn: sqlite3.Connection, request: Request) -> str:
    """Queue the writing task for an admitted run."""
    return agent_tasks.create(
        conn,
        "documentation",
        subject_id=request.run_id,
        state=_dump(WritingState(request=request)),
    )


# --- context -------------------------------------------------------------------


def _config(request: Request) -> DocgenConfig:
    return dataclasses.replace(
        DocgenConfig.from_env(),
        provider=request.provider,
        model=request.model,
        reasoning_effort=request.reasoning_effort,
    )


def _open(request: Request) -> loop._RunContext | NothingWritten:
    config = _config(request)
    instructions = ai_prompts.resolve(DOCTRINE_NAME, default_path=config.doctrine_path)
    review_instructions = ai_prompts.resolve("document_review")
    profiles = documentation_profiles.capture()
    return loop._open(
        request.prompt,
        requested_set=request.guideline_set,
        requested_type=request.document_type,
        client=None,
        substrate=InProcessSubstrate(),
        report_gap=loop._default_gap_reporter,
        config=config,
        doctrine_text=instructions.text,
        doctrine_note=instructions.note,
        catalogue=profiles.catalogue(),
        load_texts=profiles.texts,
        revision_target=request.target,
        review_instructions=review_instructions.text,
        anchor_entity_id=request.writer_anchor,
        run_id=request.run_id,
        load_audience=profiles.audience,
        scope_reader=loop._scope_reader,
        review_notes=request.review_notes,
        media_lookup=media,
    )


def _resume(state: WritingState) -> loop._RunContext:
    """The run context of an earlier call, rebuilt for this one. The scope is
    captured again, so a statement whose label narrowed since is no longer
    readable or citable."""
    request = state.request
    profiles = documentation_profiles.capture()
    audience = profiles.audience(request.guideline_set)
    if audience is None:
        raise ValueError(
            f"profile '{request.guideline_set}' writes for an audience that is "
            "no longer configured"
        )
    _guidance, exposure, template = profiles.texts(
        request.guideline_set, request.document_type
    )
    config = _config(request)
    scoped = audience_scope.scoped(InProcessSubstrate(), audience)
    return loop._RunContext(
        prompt=request.prompt,
        manual_document=None,
        client=None,
        substrate=scoped,
        report_gap=loop._default_gap_reporter,
        config=config,
        trace=TraceBuilder(
            model=config.model,
            provider=config.provider,
            run_id=request.run_id,
            op_cap=config.limits.op_cap,
            wall_clock_s=config.limits.wall_clock_s,
            prompt=request.prompt,
            requested_set=request.guideline_set,
            requested_type=request.document_type,
        ),
        start=time.monotonic(),
        review_instructions=ai_prompts.resolve("document_review").text,
        guideline_set=request.guideline_set,
        document_type=request.document_type,
        exposure=exposure,
        template=template,
        retrieved_ids=set(state.retrieved),
        visible_ids=scoped.scope.statement_ids,
        audience=audience,
        media_lookup=media,
        offered_media=media.placeable(state.offered_media, audience),
    )


def _keep_reads(state: WritingState, ctx: loop._RunContext) -> None:
    state.retrieved = sorted(ctx.retrieved_ids)
    state.offered_media = sorted(ctx.offered_media)


# --- claiming ------------------------------------------------------------------


def prepare(task: Task, claimant: str) -> Task | None:
    """Ready a just-claimed writing task: build its brief on the first claim,
    and start a new claimant's reads from the opening ones. None when the
    run cannot be written at all; it is recorded as such."""
    from .. import drafts_store

    conn = drafts_store.connection()
    state = WritingState.model_validate(task.state)
    brief = task.brief
    if brief is None:
        opened = _open(state.request)
        if isinstance(opened, NothingWritten):
            _close(task, state, opened, failed=True)
            return None
        brief = _brief(opened)
        state.opening = sorted(opened.retrieved_ids)
        state.offered_media = sorted(opened.offered_media)
    if state.reader != claimant:
        state.reader = claimant
        state.retrieved = list(state.opening)
    agent_tasks.save(conn, task.id, brief=brief, state=_dump(state))
    return agent_tasks.get(conn, task.id)


def _brief(ctx: loop._RunContext) -> dict[str, JsonValue]:
    request_message = ctx.messages[0]["content"]
    assert isinstance(request_message, str)
    reads = [
        tool
        for tool in build_tools(ctx.substrate.tool_specs())
        if tool["name"] in READ_TOOLS
    ]
    return _json.validate_python(
        {
            "protocol": agent_tasks.PROTOCOL,
            "instructions": ctx.system_prompt,
            "input": request_message,
            "read_tools": reads,
            "result": emit_tool_def()["description"],
            "result_schema": _EMIT_SCHEMA,
            "guideline_set": ctx.guideline_set,
            "document_type": ctx.document_type,
            "audience": None
            if ctx.audience is None
            else {
                "id": ctx.audience.id,
                "name": ctx.audience.name,
                "scope": ctx.audience.scope,
            },
        }
    )


# --- reading -------------------------------------------------------------------


def read(task: Task, tool: str, arguments: dict[str, JsonValue]) -> ReadResult:
    """Run one read for the task inside its audience boundary, recording which
    statements it put in front of the agent."""
    from .. import drafts_store

    state = WritingState.model_validate(task.state)
    if state.pending is not None:
        raise ValueError("this task's document is being reviewed")
    ctx = _resume(state)
    loop._dispatch_read(tool, dict(arguments), "read", ctx)
    result = ctx.messages[-1]["content"][0]
    _keep_reads(state, ctx)
    agent_tasks.save(drafts_store.connection(), task.id, state=_dump(state))
    return ReadResult(content=str(result["content"]), error=bool(result["is_error"]))


# --- submitting ----------------------------------------------------------------


def submit(task: Task, claimant: str, result: dict[str, JsonValue]) -> Submitted:
    """Gate one emitted document as the loop's emit gate does, then review it."""
    state = WritingState.model_validate(task.state)
    if state.pending is not None:
        raise ValueError("this task's document is being reviewed")
    ctx = _resume(state)
    try:
        title, body, ids, gaps = parse_emit_input(dict(result))
    except ValueError as exc:
        state.malformed += 1
        if state.malformed > loop._MAX_MALFORMED_RETRIES:
            return _close(
                task,
                state,
                loop._nothing(ctx, f"the emitted document was malformed: {exc}"),
                failed=True,
            )
        return _refused(
            task,
            state,
            [Finding(check="shape", problem=str(exc))],
            loop._MAX_MALFORMED_RETRIES - state.malformed + 1,
        )
    problem = loop._emit_problem(
        title, body, ids, ctx.retrieved_ids, ctx.visible_ids
    ) or loop._media_problem(ctx, body)
    if problem is not None:
        state.emit_blocks += 1
        if state.emit_blocks > loop._MAX_EMIT_BLOCKS:
            return _close(
                task,
                state,
                loop._nothing(ctx, f"the document was not recorded: {problem}"),
                failed=True,
            )
        return _refused(
            task,
            state,
            [Finding(check="grounding", problem=problem)],
            loop._MAX_EMIT_BLOCKS - state.emit_blocks + 1,
        )
    pending = Pending(title=title, body=body, statement_ids=ids, gaps=gaps)
    if state.request.review == "agent":
        return _queue_review(task, claimant, state, ctx, pending)
    return _server_review(task, state, ctx, pending)


def _server_review(
    task: Task, state: WritingState, ctx: loop._RunContext, pending: Pending
) -> Submitted:
    from .. import server

    with (
        server.model_loop_slot(),
        ai.usage.attributed("docgen", run_id=state.request.run_id),
    ):
        record = loop._review(ctx, pending.title, pending.body, pending.statement_ids)
    if record is None:
        return _close(
            task,
            state,
            loop._nothing(
                ctx, f"the document could not be reviewed: {ctx.review_error}"
            ),
            failed=True,
        )
    return _reviewed(task, state, ctx, pending, record, ctx.cited_statements)


def _reviewed(
    task: Task,
    state: WritingState,
    ctx: loop._RunContext,
    pending: Pending,
    record: ReviewRecord,
    cited: dict[str, str] | None,
) -> Submitted:
    """Keep a passed document; send a refused one back while a retry is
    left, as the loop gives its writer one fresh attempt."""
    record = record.model_copy(update={"attempts": state.reviews + 1})
    if record.passed:
        ctx.cited_statements = cited
        written = DocumentWritten(
            slug=loop._slug(pending.title),
            title=pending.title,
            body=pending.body,
            statement_ids=pending.statement_ids,
            cited_statements=cited,
            guideline_set=state.request.guideline_set,
            document_type=state.request.document_type,
            review=record,
            gaps=loop._merged_gaps(ctx, pending.gaps),
            trace=loop._build_trace(
                ctx, "document_written", cited=pending.statement_ids
            ),
        )
        return _close(task, state, written, failed=False)
    state.reviews += 1
    state.pending = None
    if state.reviews <= loop._MAX_REVIEW_RETRIES:
        return _refused(
            task,
            state,
            _review_findings(record),
            loop._MAX_REVIEW_RETRIES - state.reviews + 1,
        )
    refused = loop._nothing(
        ctx,
        loop._review_refusal_reason(record),
        review=record,
        title=pending.title,
        body=pending.body,
        cited=pending.statement_ids,
    )
    return _close(task, state, refused, failed=True)


def _review_findings(record: ReviewRecord) -> list[Finding]:
    checks: Sequence[tuple[Literal["exposure", "conformance"], ReviewCheck]] = (
        ("exposure", record.exposure),
        ("conformance", record.conformance),
    )
    return [
        Finding(check=name, where=finding.where, problem=finding.problem)
        for name, check in checks
        if check.status == "fail"
        for finding in check.findings
    ]


def _refused(
    task: Task, state: WritingState, findings: list[Finding], retries_left: int
) -> Submitted:
    from .. import drafts_store

    return agent_tasks.refused(
        drafts_store.connection(), task, findings, retries_left, state=_dump(state)
    )


def _close(
    task: Task, state: WritingState, result: DocgenResult, *, failed: bool
) -> Submitted:
    """Record the run's outcome as an internal run's is recorded, and close
    the task."""
    from .. import doc_runs, drafts_store

    request = state.request
    doc_runs.record_result(
        request.run_id,
        result,
        prompt=request.prompt,
        guideline_set=request.guideline_set,
        document_type=request.document_type,
        revision_target=request.target,
        anchor_entity_id=request.anchor_entity_id,
    )
    reason = result.reason if isinstance(result, NothingWritten) else None
    return agent_tasks.closed(
        drafts_store.connection(),
        task,
        reason or "The document was reviewed and saved; see get_documentation_run.",
        failed=failed,
        findings=_review_findings(result.review)
        if isinstance(result, NothingWritten) and result.review is not None
        else [],
    )


# --- agent review --------------------------------------------------------------


def _queue_review(
    task: Task,
    claimant: str,
    state: WritingState,
    ctx: loop._RunContext,
    pending: Pending,
) -> Submitted:
    """Hold the grounded document for a review by an agent other than its
    writer, briefed as the server's reviewer would be."""
    from .. import drafts_store

    conn = drafts_store.connection()
    statements = ctx.substrate.call("get_statements", {"ids": pending.statement_ids})
    check_exposure = bool((ctx.exposure or "").strip()) or ctx.audience is not None
    assert ctx.guideline_set is not None and ctx.document_type is not None
    tool = review_tool_def(check_exposure=check_exposure)
    brief = _json.validate_python(
        {
            "protocol": agent_tasks.PROTOCOL,
            "instructions": prompts.build_review_system_prompt(
                instructions=ctx.review_instructions,
                guideline_set=ctx.guideline_set,
                document_type=ctx.document_type,
                exposure=ctx.exposure,
                template=ctx.template,
                audience=ctx.audience,
            ),
            "input": prompts.review_message(
                prompt=ctx.prompt,
                title=pending.title,
                body=pending.body,
                statements=statements,
                placed_media=loop._placed(ctx, pending.body),
            ),
            "read_tools": [],
            "result": tool["description"],
            "result_schema": tool["input_schema"],
            "writer_task": task.id,
        }
    )
    agent_tasks.create(
        conn,
        "document_review",
        subject_id=state.request.run_id,
        brief=brief,
        state=_dump(
            ReviewState(
                writer_task=task.id,
                check_exposure=check_exposure,
                cited_statements=loop._statement_texts(statements),
            )
        ),
        excluded_claimant=claimant,
    )
    state.pending = pending
    agent_tasks.save(
        conn, task.id, state=_dump(state), findings=[], submitted_by=claimant
    )
    agent_tasks.set_status(conn, task.id, "in_review")
    return Submitted(
        task_id=task.id,
        status="in_review",
        message="Grounded. Another agent reviews the document next; a refused "
        "review returns the task to the queue with its findings.",
    )


def submit_review(
    task: Task, _claimant: str, result: dict[str, JsonValue]
) -> Submitted:
    """Take an agent's review of a held document, as the loop takes its
    reviewer's `record_review`."""
    from .. import drafts_store

    conn = drafts_store.connection()
    review = ReviewState.model_validate(task.state)
    writer = agent_tasks.get(conn, review.writer_task)
    if writer is None or writer.finished_at is not None:
        agent_tasks.finish(conn, task.id, "failed", error="the document is gone")
        raise ValueError("the document this review was for is no longer waiting")
    state = WritingState.model_validate(writer.state)
    pending = state.pending
    assert pending is not None
    ctx = _resume(state)
    try:
        exposure, conformance = parse_review_input(
            dict(result), check_exposure=review.check_exposure
        )
    except (TypeError, ValueError) as exc:
        review.malformed += 1
        if review.malformed > loop._MAX_MALFORMED_RETRIES:
            agent_tasks.finish(conn, task.id, "failed", error=str(exc))
            outcome = _close(
                writer,
                state,
                loop._nothing(
                    ctx,
                    f"the document could not be reviewed: the review was malformed: {exc}",
                ),
                failed=True,
            )
            return outcome.model_copy(update={"task_id": task.id})
        return agent_tasks.refused(
            conn,
            task,
            [Finding(check="shape", problem=str(exc))],
            loop._MAX_MALFORMED_RETRIES - review.malformed + 1,
            state=_dump(review),
        )
    record = ReviewRecord(
        exposure=exposure,
        conformance=conformance,
        attempts=state.reviews + 1,
        passed=exposure.status in ("pass", "unchecked")
        and conformance.status == "pass",
    )
    ctx.review = record
    ctx.trace.reviews.append(
        {
            "attempt": record.attempts,
            "exposure": exposure.model_dump(),
            "conformance": conformance.model_dump(),
            "passed": record.passed,
            "reviewer": "agent",
        }
    )
    agent_tasks.finish(conn, task.id, "done")
    outcome = _reviewed(writer, state, ctx, pending, record, review.cited_statements)
    if outcome.status == "refused":
        agent_tasks.set_status(conn, writer.id, "waiting")
        message = "Review recorded: the document goes back to its writer's queue."
    elif outcome.status == "accepted":
        message = "Review recorded: the document was saved."
    else:
        message = "Review recorded: " + outcome.message
    return Submitted(
        task_id=task.id,
        status="accepted",
        message=message,
        findings=outcome.findings,
    )


WRITING = agent_tasks.Handler(prepare=prepare, read=read, submit=submit)
REVIEW = agent_tasks.Handler(submit=submit_review)
