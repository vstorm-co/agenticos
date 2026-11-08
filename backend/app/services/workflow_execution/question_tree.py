"""Surface questions from the synchronous workflow calls a chat is waiting on."""

from collections import deque
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import WorkflowQuestionRead
from app.services.workflow_execution import questions
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError
from app.workflows.nodes.workflow_run._handler import MAX_CALL_DEPTH


async def read(
    db: AsyncSession,
    ctx: AuthContext,
    run: WorkflowRun,
    *,
    load: Callable[[UUID], Awaitable[WorkflowRun]],
    can_answer: Callable[[WorkflowRun], Awaitable[bool]],
) -> list[WorkflowQuestionRead]:
    """Collect visible questions without changing the child runs' reply destinations.

    Each child requires its own workflow view permission, and only runs the
    person may still execute offer answer controls. Only synchronous calls for
    the same person are followed; detached work keeps its own run surface.
    """
    if (
        ctx.user_id is None
        or ctx.api_key_id is not None
        or run.execution_principal_user_id != ctx.user_id
        or run.public_origin
        or WorkflowRunStatus(run.status).is_terminal
    ):
        return []
    pending = deque([(run, 0)])
    visited: set[UUID] = set()
    result: list[WorkflowQuestionRead] = []
    while pending:
        current, depth = pending.popleft()
        if current.id in visited:
            continue
        visited.add(current.id)
        if await can_answer(current):
            result.extend(await questions.read(db, ctx, current))
        if depth >= MAX_CALL_DEPTH:
            continue
        for child in await workflow_run_repo.list_waited_child_runs(
            db, workflow_run_id=current.id, organization_id=ctx.organization_id
        ):
            if child.execution_principal_user_id != ctx.user_id or child.public_origin:
                continue
            try:
                visible = await load(child.id)
            except WorkflowRunNotFoundError:
                continue
            pending.append((visible, depth + 1))
    return result
