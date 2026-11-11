"""Durable question answers and the owning workflow step's continuation.

The request records answers and queues dispatch in one transaction. It never
runs a model: workflow dispatch rechecks the principal, deadline and budget.
"""

from collections.abc import Mapping

from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.workflow_run import (
    NodeRun,
    NodeRunStatus,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import agent_run as agent_run_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import WorkflowQuestionRead
from app.services.workflow_execution import context, dispatch_queue


def ready(run: AgentRun) -> bool:
    """An answered or ended child can be collected; an unanswered question cannot."""
    if run.status == RunStatus.RUNNING.value:
        return False
    if run.status == RunStatus.AWAITING_ANSWER.value:
        return bool((run.paused_state or {}).get("question_results"))
    return True


async def read(db: AsyncSession, ctx: AuthContext, run: WorkflowRun) -> list[WorkflowQuestionRead]:
    """Only the execution principal sees questions asked in this workflow run."""
    from app.services.agent_runner import AgentRunnerService

    if (
        ctx.user_id is None
        or ctx.api_key_id is not None
        or run.execution_principal_user_id != ctx.user_id
        or run.public_origin
        or WorkflowRunStatus(run.status).is_terminal
    ):
        return []
    result: list[WorkflowQuestionRead] = []
    runner = AgentRunnerService(db)
    for node in await workflow_run_repo.list_question_waits(db, workflow_run_id=run.id):
        if node.waiting_agent_run_id is None:
            continue
        child = await agent_run_repo.get_run(
            db, node.waiting_agent_run_id, organization_id=ctx.organization_id
        )
        if child is None or ready(child):
            continue
        questions = await runner.parked_questions(ctx, child)
        if questions:
            result.append(
                WorkflowQuestionRead(
                    workflow_run_id=run.id,
                    node_run_id=node.id,
                    agent_run_id=child.id,
                    questions=questions,
                )
            )
    return result


async def accept(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    run: WorkflowRun,
    node: NodeRun,
    responses: Mapping[str, list[dict[str, JsonValue]]],
) -> None:
    """Accept under the owning run and node locks, then queue exactly one continuation."""
    from app.services.agent_runner import AgentRunnerService

    if (
        node.status != NodeRunStatus.WAITING.value
        or node.waiting_reason != WaitingReason.QUESTION.value
        or node.waiting_agent_run_id is None
    ):
        raise BadRequestError(
            message="This step is not waiting for an answer", details={"node_run_id": node.id}
        )
    await AgentRunnerService(db).accept_answers(ctx, node.waiting_agent_run_id, responses)
    try:
        async with db.begin_nested():
            await dispatch_queue.queue_dispatch(db, run=run, node_run_id=node.id)
    except IntegrityError:
        outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(db, node_run_id=node.id)
        if outbox is None or outbox.status not in ("pending", "claimed"):
            raise


async def link_agent_run(
    db: AsyncSession, current: context.DispatchContext, child: AgentRun
) -> None:
    """Persist ownership before the runner commits admission and calls the model.

    A crash after the child parks but before the handler settles can then recover
    the same child. A cancelled workflow refuses admission before any tool runs.
    """
    node = await own_agent_run(db, current, child)
    await workflow_run_repo.update_node_run(
        db, node_run=node, update_data={"waiting_agent_run_id": child.id}
    )
    context.report_waiting_agent_run(child.id)


async def own_agent_run(
    db: AsyncSession, current: context.DispatchContext, child: AgentRun
) -> NodeRun:
    """Tie `child` to this attempt before the runner commits admission.

    Settling reads the cost the runner committed for the child off this link, so
    an attempt that crashed after spending is still billed. A step that never
    parks on its child links only this; `link_agent_run` also waits on it.

    Raises:
        BadRequestError: The step no longer accepts an agent run.
    """
    run = await workflow_run_repo.get_run_by_id_for_update(db, current.workflow_run_id)
    node = await workflow_run_repo.get_node_run_by_id_for_update(db, current.node_run_id)
    latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=current.node_run_id)
    if (
        current.claim.lost
        or run is None
        or WorkflowRunStatus(run.status).is_terminal
        or node is None
        or node.status != NodeRunStatus.RUNNING.value
        or latest is None
        or latest.attempt_no != current.attempt_no
    ):
        raise BadRequestError(
            message="This workflow step no longer accepts an agent run",
            details={"node_run_id": current.node_run_id},
        )
    await workflow_run_repo.link_attempt_agent_run(db, attempt=latest, agent_run_id=child.id)
    return node
