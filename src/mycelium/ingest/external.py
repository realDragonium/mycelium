"""Ingest and the connect pass done by an outside agent instead of a server
model.

With External agent selected for ingest or connect, the call queues an
`agent_tasks` task rather than running the loop. The agent gets what the
loop's model would: its system prompt, the opening message with the live
vocabulary, the read tools and the `emit_draft` schema, all from the loop's
own `_open`. Reads go through `read` and count toward the reading floor as
the model's do. A submission is the `emit_draft` input and goes through the
loop's `_handle_emit`: the floor, ledger and coverage checks, then the same
draft assembly, screening and validation. A refusal is the re-prompt the
model would get, returned as findings, as often as the loop allows.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from typing import Any, Literal

from pydantic import BaseModel, JsonValue, TypeAdapter

from .. import agent_tasks, ai, model_settings
from ..agent_tasks import Finding, Kind, ReadResult, Submitted, Task
from ..ask.substrate import InProcessSubstrate
from . import loop
from .config import IngestConfig
from .connect import Target, config_from_settings, connect_task
from .draft import InProcessDraftEmitter
from .schema import DraftCreated, IngestResult, NothingToIngest
from .tools import _EMIT_SCHEMA, EMIT_TOOL, emit_tool_def
from .trace import TraceBuilder

_json = TypeAdapter(dict[str, JsonValue])
Action = Literal["ingest", "connect"]


class LoopState(BaseModel):
    #: Ingest's text, or the statements the connect pass works on.
    text: str | None = None
    statement_ids: list[str] = []
    reader: str | None = None
    #: The reads the current claimant made that succeeded, for the floor.
    reads: list[str] = []
    floor_blocks: int = 0
    malformed: int = 0


def external(action: Action) -> bool:
    return model_settings.get(action).external_agent


def queue(
    action: Action, state: LoopState, requested_by: str | None
) -> dict[str, JsonValue]:
    """Queue the run; the response the tool returns instead of its result."""
    from .. import drafts_store

    task_id = agent_tasks.create(
        drafts_store.connection(),
        action,
        subject_id=None,
        state=_json.validate_python(state.model_dump()),
        requested_by=requested_by,
    )
    return {
        "outcome": "waiting_for_agent",
        "agent_task": task_id,
        "message": "Queued for an outside agent; get_agent_task shows the "
        "draft it makes.",
    }


def connecting(conn: sqlite3.Connection) -> set[str]:
    """The statements an unfinished connect task works on."""
    return {
        statement_id
        for task in agent_tasks.open_tasks(conn, "connect")
        for statement_id in LoopState.model_validate(task.state).statement_ids
    }


def _targets(state: LoopState) -> list[Target]:
    from .. import knowledge_health
    from ..server.runtime import _db

    return knowledge_health.targets(_db(), state.statement_ids)


def _open(kind: Kind, state: LoopState, claimant: str) -> loop._RunContext:
    from ..server.model_loops import _known_name

    if kind == "connect":
        config = config_from_settings()
        task, _ = connect_task(_targets(state), _known_name)
    else:
        config = IngestConfig.from_env()
        task, _ = loop.ingest_task(state.text or "", config)
    # No model runs, so the run has no price and no spending cap.
    config = dataclasses.replace(config, model=f"agent:{claimant}", max_cost_usd=None)
    return loop._open(task, None, InProcessSubstrate(), InProcessDraftEmitter(), config)


def prepare(task: Task, claimant: str) -> Task | None:
    """Brief a just-claimed task on its first claim, and start a new
    claimant's reads afresh: the floor counts what this agent read."""
    from .. import drafts_store

    conn = drafts_store.connection()
    state = LoopState.model_validate(task.state)
    brief = task.brief
    if brief is None:
        try:
            ctx = _open(task.kind, state, claimant)
        except ValueError as exc:
            agent_tasks.closed(conn, task, str(exc), failed=True)
            return None
        opening = ctx.messages[0]["content"]
        assert isinstance(opening, str)
        brief = _json.validate_python(
            {
                "protocol": agent_tasks.PROTOCOL,
                "instructions": ctx.task.system_prompt,
                "input": opening,
                "read_tools": [t for t in ctx.tools if t["name"] != EMIT_TOOL],
                "result": emit_tool_def()["description"],
                "result_schema": _EMIT_SCHEMA,
            }
        )
    if state.reader != claimant:
        state.reader = claimant
        state.reads = []
    agent_tasks.save(
        conn, task.id, brief=brief, state=_json.validate_python(state.model_dump())
    )
    return agent_tasks.get(conn, task.id)


def read(task: Task, tool: str, arguments: dict[str, JsonValue]) -> ReadResult:
    if tool == EMIT_TOOL:
        raise ValueError("submit the draft with submit_agent_task")
    state = LoopState.model_validate(task.state)
    messages: list[dict[str, Any]] = []
    trace = TraceBuilder(model="agent", op_cap=0, wall_clock_s=0)
    if loop._dispatch_read(
        tool, dict(arguments), "read", InProcessSubstrate(), trace, messages
    ):
        from .. import drafts_store

        state.reads.append(tool)
        agent_tasks.save(
            drafts_store.connection(),
            task.id,
            state=_json.validate_python(state.model_dump()),
        )
    content = messages[-1]["content"]
    assert isinstance(content, list)
    return ReadResult(content=str(content[0]["content"]), error=content[0]["is_error"])


def submit(task: Task, claimant: str, result: dict[str, JsonValue]) -> Submitted:
    from .. import drafts_store

    conn = drafts_store.connection()
    state = LoopState.model_validate(task.state)
    try:
        ctx = _open(task.kind, state, claimant)
    except ValueError as exc:
        return agent_tasks.closed(conn, task, str(exc), failed=True)
    ctx.reads_after_vocab.extend(state.reads)
    ctx.floor_blocks, ctx.malformed_retries = state.floor_blocks, state.malformed
    ctx.submitted = dict(result)
    outcome = loop._handle_emit(
        ai.ToolUse(id="submit", name=EMIT_TOOL, input=result), ctx
    )
    if outcome is None:
        return _refused(task, state, ctx)
    return _close(task, state, outcome)


def _refused(task: Task, state: LoopState, ctx: loop._RunContext) -> Submitted:
    from .. import drafts_store

    malformed = ctx.malformed_retries > state.malformed
    state.floor_blocks, state.malformed = ctx.floor_blocks, ctx.malformed_retries
    reply = ctx.messages[-1]["content"]
    assert isinstance(reply, list)
    finding = Finding(
        check="shape" if malformed else "floor", problem=str(reply[-1]["content"])
    )
    left = (
        loop._MAX_MALFORMED_RETRIES - state.malformed
        if malformed
        else loop._MAX_FLOOR_BLOCKS - state.floor_blocks
    )
    return agent_tasks.refused(
        drafts_store.connection(),
        task,
        [finding],
        left + 1,
        state=_json.validate_python(state.model_dump()),
    )


def _close(task: Task, state: LoopState, outcome: IngestResult) -> Submitted:
    from .. import drafts_store
    from ..server.drafts import _auto_submit
    from ..server.model_loops import connected

    if task.kind == "connect":
        response = connected(outcome, _targets(state))
    else:
        response = outcome.model_dump()
        if isinstance(outcome, DraftCreated):
            response["submitted_for_review"] = _auto_submit(outcome.draft_id)
    kept = {
        key: response[key]
        for key in (
            "outcome",
            "draft_id",
            "alias_draft_id",
            "submitted_for_review",
            "reason",
            "gaps_filed",
        )
        if key in response
    }
    failed = isinstance(outcome, NothingToIngest) and outcome.reason.startswith(
        "degraded"
    )
    return agent_tasks.closed(
        drafts_store.connection(),
        task,
        outcome.reason
        if isinstance(outcome, NothingToIngest)
        else f"Draft {outcome.draft_id} created.",
        failed=failed,
        result=_json.validate_python(kept),
    )


HANDLER = agent_tasks.Handler(prepare=prepare, read=read, submit=submit)
