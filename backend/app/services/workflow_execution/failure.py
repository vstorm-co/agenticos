"""Starting a workflow's error workflow when one of its runs fails (#1945).

A workflow's settings may name an error workflow: a published workflow that
starts from `trigger.workflow_failed`. When a real run of the workflow ends
failed, that workflow's live version is admitted once, in the same transaction
that failed the run, as the member who chose it - with the run, the step that
failed and the error as its input. The poll submits its first dispatch after
the transaction commits.

Nothing starts for a test run, for a run an error workflow itself is (so a
failing error workflow never starts itself, or another, again), or when the
error workflow can no longer be run as that member - archived, unpublished,
republished from another trigger, or out of their reach. Those are logged and
left: a failure that cannot report itself must not fail the settle that
recorded it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import WorkflowStatus
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode, WorkflowRunTrigger
from app.repositories import member_repo
from app.repositories import workflow as workflow_repo
from app.schemas.workflow import StoredWorkflowSettings
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowRunInputTooLargeError,
)
from app.workflows import _registry
from app.workflows.contracts.results import WorkflowError
from app.workflows.triggers import WORKFLOW_FAILED

logger = logging.getLogger(__name__)


async def start_error_workflow(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    step_id: UUID,
    error: WorkflowError,
) -> None:
    """Admit `run`'s workflow's error workflow for `run`'s failure, if it has one it may."""
    if (
        run.mode != WorkflowRunMode.REAL.value
        or run.triggered_by == WorkflowRunTrigger.WORKFLOW_FAILED.value
    ):
        return
    workflow = await workflow_repo.get(db, run.workflow_id, organization_id=run.organization_id)
    if workflow is None:
        return
    settings = StoredWorkflowSettings.model_validate(workflow.settings)
    if settings.error_workflow_id is None or settings.error_workflow_run_as is None:
        return
    target = await workflow_repo.get(
        db, settings.error_workflow_id, organization_id=run.organization_id
    )
    version = (
        await workflow_repo.get_version(
            db, target.current_version_id, organization_id=run.organization_id
        )
        if target is not None
        and target.status != WorkflowStatus.ARCHIVED.value
        and target.live_trigger == WORKFLOW_FAILED
        and target.current_version_id is not None
        else None
    )
    membership = await member_repo.get_active(
        db, organization_id=run.organization_id, user_id=settings.error_workflow_run_as
    )
    ctx = (
        AuthContext(
            user_id=settings.error_workflow_run_as,
            organization_id=run.organization_id,
            role=membership.role,
        )
        if membership is not None
        else None
    )
    if (
        target is None
        or version is None
        or ctx is None
        or not await resolve_access(db, ctx, target, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW)
    ):
        logger.warning(
            "workflow_error_workflow_not_started",
            extra={"run_id": str(run.id), "error_workflow_id": str(settings.error_workflow_id)},
        )
        return

    # The facade imports the dispatcher, which calls this, and the node packages
    # import the table service, which imports the facade: imported here to keep
    # the modules' import order free of a cycle.
    from app.services.workflow_execution.dispatcher import resolve_graph
    from app.services.workflow_execution.facade import Causation, WorkflowExecutionService
    from app.workflows.nodes._triggers import FailedRunError, WorkflowFailedTriggerOutput

    step = (await resolve_graph(db, run)).node_by_id[step_id]

    payload = WorkflowFailedTriggerOutput(
        run_id=run.id,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        step_id=step_id,
        # What the step is called: the name its builder gave it, else its node type's.
        step_name=step.label or _registry.get(step.definition_id, step.definition_version).name,
        error=FailedRunError(code=error.code, message=error.message),
    ).model_dump(mode="json")
    try:
        async with db.begin_nested():
            await WorkflowExecutionService(db).admit_pinned(
                ctx,
                target,
                version,
                triggered_by=WorkflowRunTrigger.WORKFLOW_FAILED,
                run_input=payload,
                causation=Causation(
                    root_run_id=run.root_run_id,
                    causation_run_id=run.id,
                    visited_trigger_ids=list(run.visited_trigger_ids),
                    depth=run.depth + 1,
                ),
                submitted=False,
            )
    except (WorkflowAdmissionQuotaError, WorkflowRunInputTooLargeError):
        logger.warning("workflow_error_workflow_refused", extra={"run_id": str(run.id)})
