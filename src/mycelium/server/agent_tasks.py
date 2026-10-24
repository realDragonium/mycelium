"""The agent task queue over MCP: outside agents do the work an action would
give a server model (see `mycelium.agent_tasks`).

Writers and admins claim tasks: the same real role that may request
documentation, so an agent can do no more than its token could already ask
the server to do. Drafters, readers and audience-scoped tokens cannot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, JsonValue

from .. import agent_tasks
from .. import auth as _auth
from ..agent_tasks import Kind, Submitted, Task
from ..docgen import external
from .registry import tool
from .runtime import _drafts_db


class ClaimedTask(BaseModel):
    id: str
    kind: Kind
    #: The documentation run or plan the task completes.
    subject_id: str | None
    #: What the work needs: `protocol`, `instructions`, `input`,
    #: `read_tools`, `result` and `result_schema`, plus what the kind adds.
    brief: dict[str, JsonValue] | None
    #: Why the last submission was refused, when one was.
    findings: list[agent_tasks.Finding]
    failures: int


class TaskBatch(BaseModel):
    kind: Kind
    tasks: list[ClaimedTask]
    #: Tasks of this kind you already held, whose lease this call extended.
    renewed: list[str]
    expires_at: str


class Released(BaseModel):
    task_id: str
    status: str


def _claimant() -> str:
    principal = _auth.current_principal.get()
    return principal.id if principal is not None else _auth.LOCAL_ADMIN_ID


def _prepare(task: Task, claimant: str) -> Task | None:
    from .. import documentation_planning

    if task.kind == "documentation":
        return external.prepare(task, claimant)
    if task.kind == "documentation_planning":
        return documentation_planning.prepare_agent_task(task)
    return task


@tool(role="writer", real_role=True)
def claim_agent_task(
    kind: Kind,
    limit: Annotated[int, Field(ge=0, le=agent_tasks.MAX_BATCH)] = 1,
) -> TaskBatch:
    """Claim work this server would otherwise give its own model, for 30
    minutes, when an action's model setting is External agent.

    `kind`: `documentation` (write or revise a document), `document_review`
    (review a document another agent wrote; never your own),
    `documentation_planning` (propose a writing profile's documents) or
    `audience_labelling` (decide which audiences may see statements).
    Oldest tasks come first. Each carries a `brief`: `instructions` and
    `input` are what the server's model would be given, `read_tools` the
    reads it could make (call them with `read_for_agent_task`) and
    `result_schema` what `submit_agent_task` takes. `findings` say why your
    or a previous agent's last submission was refused.

    Each call also extends your lease on every task of `kind` you hold
    (`limit=0` only renews). A task whose lease runs out goes back to the
    queue; `release_agent_task` gives one back at once.
    """
    from .. import audience_labelling

    claimant = _claimant()
    if kind == "audience_labelling" and limit:
        audience_labelling.queue_agent_tasks(limit)
    chosen, renewed, expires = agent_tasks.claim(
        _drafts_db(), kind, claimant=claimant, limit=limit, now=datetime.now(UTC)
    )
    tasks = [
        ClaimedTask(
            id=ready.id,
            kind=ready.kind,
            subject_id=ready.subject_id,
            brief=ready.brief,
            findings=ready.findings,
            failures=ready.failures,
        )
        for task in chosen
        if (ready := _prepare(task, claimant)) is not None
    ]
    return TaskBatch(kind=kind, tasks=tasks, renewed=renewed, expires_at=expires)


@tool(role="writer", real_role=True)
def read_for_agent_task(
    task_id: str, tool: str, arguments: dict[str, JsonValue] | None = None
) -> external.ReadResult:
    """Run one of a documentation task's `read_tools` for it, inside the
    audience boundary the task writes for: what that audience may not see
    is not there. Only statements a read returned to you may be cited when
    you submit. `content` is the result as the server's model would get it,
    truncated where it would be.
    """
    task = agent_tasks.held(_drafts_db(), task_id, _claimant())
    if task.kind != "documentation":
        raise ValueError(f"a {task.kind} task has no reads; its brief holds its input")
    return external.read(task, tool, arguments or {})


@tool(role="writer", real_role=True)
def submit_agent_task(task_id: str, result: dict[str, JsonValue]) -> Submitted:
    """Hand in a claimed task's result, shaped as its brief's
    `result_schema`. It passes the checks the server's own output would:
    a refusal returns `findings` and how many `retries_left`; fix them and
    submit again. `in_review` means another agent reviews the document
    next; `failed` closes the task.
    """
    from .. import audience_labelling, documentation_planning

    claimant = _claimant()
    task = agent_tasks.held(_drafts_db(), task_id, claimant)
    if task.kind == "documentation":
        return external.submit(task, claimant, result)
    if task.kind == "document_review":
        return external.submit_review(task, result)
    if task.kind == "documentation_planning":
        return documentation_planning.submit_agent_task(task, result)
    return audience_labelling.submit_agent_task(task, claimant, result)


@tool(role="writer", real_role=True)
def release_agent_task(
    task_id: str, reason: Annotated[str, Field(min_length=1, max_length=300)]
) -> Released:
    """Give a claimed task back to the queue, saying why, for another agent
    or a later attempt."""
    task = agent_tasks.held(_drafts_db(), task_id, _claimant())
    agent_tasks.set_status(
        _drafts_db(), task.id, "waiting", release_reason=reason.strip()
    )
    return Released(task_id=task.id, status="waiting")
