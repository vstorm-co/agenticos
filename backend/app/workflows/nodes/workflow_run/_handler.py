"""`workflow.run`: run another workflow as a step, and hand on what it answered.

The first dispatch starts the chosen workflow's published version - one that
starts from **Called by a workflow** - with the bound input, as this run acts, and
parks the step on it. The called run's end wakes the step
(`delivery.wake_caller`), and this handler, dispatched again, hands on the run's
output, or fails with its error. With `wait` off it hands on the started run at
once and the called run goes on by itself.

The called run is found by the step's own `NodeRun`, so a retried or re-woken
dispatch finds the run it started instead of starting another. A call that would
loop back into a workflow already in the chain, or go deeper than
`MAX_CALL_DEPTH`, is refused.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.db.session import get_worker_db_context
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution import context
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
)
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError
from app.workflows.triggers import WORKFLOW_CALL

MAX_CALL_DEPTH = 5
"""How many calls deep a chain of workflows may go."""


class WorkflowRunConfig(BaseModel):
    """Which workflow to run, and whether to wait for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID = Field(
        json_schema_extra={"x-resource": "workflow"},
        title="Workflow",
        description="A published workflow that starts from Called by a workflow",
    )
    wait: bool = Field(
        default=True,
        title="Wait for it to finish",
        description="Hand on what it answers. Off, the step goes on as soon as it starts",
    )


class WorkflowRunInput(BaseModel):
    """What the called workflow starts with, checked against the fields it declares."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunOutput(BaseModel):
    """The run it started: how it stands, and what it answered once it has."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    status: str
    output: dict[str, Any] | None = None


def _callable_version(workflow: Workflow) -> UUID | None:
    """The live version a step may call, or None when the workflow is not one to call."""
    if workflow.status == WorkflowStatus.ARCHIVED.value or workflow.live_trigger != WORKFLOW_CALL:
        return None
    return workflow.current_version_id


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a workflow the author cannot run, or one no step can call."""
    if not isinstance(config, WorkflowRunConfig):
        return []
    workflow = await workflow_repo.get(db, config.workflow_id, organization_id=ctx.organization_id)
    if workflow is None or not await resolve_access(
        db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
    ):
        return [("workflow_id", "No workflow you can run has that id")]
    if _callable_version(workflow) is None:
        return [("workflow_id", "Publish that workflow starting from Called by a workflow first")]
    return []


def _answer(called: WorkflowRun, *, wait: bool) -> NodeResult:
    """What the step hands on for the run it called, as that run stands now."""
    if not wait:
        return Completed[WorkflowRunOutput](
            output=WorkflowRunOutput(run_id=called.id, status=called.status)
        )
    if not WorkflowRunStatus(called.status).is_terminal:
        return Waiting(reason="external_event", resume_token=str(called.id))
    if called.status == WorkflowRunStatus.SUCCEEDED.value:
        return Completed[WorkflowRunOutput](
            output=WorkflowRunOutput(run_id=called.id, status=called.status, output=called.output)
        )
    error = called.error or {}
    return Failed(
        error=WorkflowError(
            code="CALLED_WORKFLOW_FAILED",
            message=f"The workflow this step ran ended {called.status}: "
            + str(error.get("message", "no error was recorded")),
            details={"run_id": str(called.id), "code": error.get("code")},
        )
    )


def _refused(code: str, message: str, **details: object) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message, details=dict(details)))


def _unavailable() -> Failed:
    return _refused(
        "CALLED_WORKFLOW_UNAVAILABLE", "The workflow this step runs is not published to be called"
    )


async def _call(
    db: AsyncSession, config: WorkflowRunConfig, run_input: dict[str, Any]
) -> WorkflowRun | Failed:
    current = context.current()
    caller = await workflow_run_repo.get_run(
        db, current.workflow_run_id, organization_id=current.organization_id
    )
    workflow = await workflow_repo.get(
        db, config.workflow_id, organization_id=current.organization_id
    )
    version_id = _callable_version(workflow) if workflow is not None else None
    if caller is None or workflow is None or version_id is None:
        return _unavailable()
    if not await resolve_access(
        db, current.auth, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
    ):
        return _refused("CALLED_WORKFLOW_UNAVAILABLE", "This run may not run that workflow")
    visited = f"workflow:{workflow.id}"
    if workflow.id == caller.workflow_id or visited in caller.visited_trigger_ids:
        return _refused(
            "WORKFLOW_CALL_LOOP",
            "That workflow is already running further up this chain of calls",
            workflow_id=str(workflow.id),
        )
    if caller.depth + 1 > MAX_CALL_DEPTH:
        return _refused(
            "WORKFLOW_CALL_TOO_DEEP",
            f"A chain of workflows may call at most {MAX_CALL_DEPTH} deep",
        )
    version = await workflow_repo.get_version(
        db, version_id, organization_id=current.organization_id
    )
    if version is None:
        return _unavailable()
    return await _admit(db, caller, workflow, version, run_input, visited)


async def _admit(
    db: AsyncSession,
    caller: WorkflowRun,
    workflow: Workflow,
    version: WorkflowVersion,
    run_input: dict[str, Any],
    visited: str,
) -> WorkflowRun | Failed:
    # The execution service imports the node packages through the registry.
    from app.services.workflow_execution.facade import Causation, WorkflowExecutionService

    current = context.current()
    try:
        return await WorkflowExecutionService(db).admit_call(
            current.auth,
            workflow,
            version,
            run_input=run_input,
            causation=Causation(
                root_run_id=caller.root_run_id,
                causation_run_id=caller.id,
                visited_trigger_ids=[
                    *caller.visited_trigger_ids,
                    f"workflow:{caller.workflow_id}",
                    visited,
                ],
                depth=caller.depth + 1,
            ),
            parent_node_run_id=current.node_run_id,
        )
    except WorkflowAdmissionQuotaError as refusal:
        # Too much work in flight: the next try may find room.
        return Failed(
            error=WorkflowError(
                code=refusal.code,
                message=refusal.message,
                details=refusal.details or {},
                retryable=True,
            )
        )
    except (WorkflowRunInputInvalidError, WorkflowRunInputTooLargeError) as refusal:
        return _refused(refusal.code, refusal.message, **(refusal.details or {}))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Start the workflow, keep waiting on it, or hand on what it answered."""
    if not isinstance(config, WorkflowRunConfig):
        return _refused("WORKFLOW_RUN_NOT_CONFIGURED", "This step names no workflow to run")
    run_input = node_input.input if isinstance(node_input, WorkflowRunInput) else {}
    current = context.current()
    async with get_worker_db_context() as db:
        called = await workflow_run_repo.get_run_called_by(db, node_run_id=current.node_run_id)
        if called is None:
            started = await _call(db, config, run_input)
            if isinstance(started, Failed):
                return started
            called = started
        return _answer(called, wait=config.wait)
