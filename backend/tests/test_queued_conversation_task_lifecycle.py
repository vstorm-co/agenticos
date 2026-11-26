"""Personal queued tasks finish in their own topic without a source return turn."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.db.models.conversation_task import ConversationTask
from app.services import conversation_tasks as module

pytestmark = pytest.mark.anyio


def queued_task() -> ConversationTask:
    return ConversationTask(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        source_conversation_id=uuid4(),
        conversation_id=uuid4(),
        source_agent_id=uuid4(),
        agent_id=uuid4(),
        source_version_id=uuid4(),
        version_id=uuid4(),
        source_run_id=None,
        queue_receipt_id=uuid4(),
        job_id=uuid4(),
        run_id=uuid4(),
        return_run_id=None,
        title="Prepare the briefing",
        prompt="",
        status="running",
        delivery="running",
        outcome=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.security
@pytest.mark.parametrize("has_receipt", [False, True])
async def test_a_task_without_a_source_turn_cannot_return_to_the_original_chat(
    has_receipt: bool,
) -> None:
    task = queued_task()
    if not has_receipt:
        task.queue_receipt_id = None
    service = module.ConversationTaskService(MagicMock())
    with (
        patch.object(service, "authority", new=AsyncMock()) as authority,
        patch.object(module.conversation_repo, "message_scope_for_run", new=AsyncMock()) as scope,
        pytest.raises(BadRequestError, match=r"no return turn|no source run"),
    ):
        await service.return_context(task)
    authority.assert_not_awaited()
    scope.assert_not_awaited()


async def test_stopping_a_queued_personal_task_settles_delivery_without_a_return_job() -> None:
    task = queued_task()
    ctx = AuthContext(user_id=task.user_id, organization_id=task.organization_id, role="member")
    service = module.ConversationTaskService(MagicMock())
    with (
        patch.object(service, "get", new=AsyncMock(return_value=task)),
        patch.object(module.run_repo, "get_run", new=AsyncMock(return_value=None)),
        patch.object(module.job_repo, "cancel_queued", new=AsyncMock()) as cancel_job,
        patch.object(module.task_repo, "save", new=AsyncMock()) as save,
        patch.object(service, "queue_return", new=AsyncMock()) as queue_return,
    ):
        result = await service.stop(ctx, task.id)
    assert result.status == "cancelled"
    assert result.delivery == "delivered"
    assert result.outcome == "Stopped by the person who started it."
    cancel_job.assert_awaited_once_with(service.db, task.job_id)
    save.assert_awaited_once_with(service.db, task)
    queue_return.assert_not_awaited()


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_a_finished_queued_personal_run_settles_only_its_task_topic(status: str) -> None:
    task = queued_task()
    run = AgentRun(id=task.run_id, organization_id=task.organization_id, status=status)
    service = module.ConversationTaskService(MagicMock())
    with (
        patch.object(module.task_repo, "for_run", new=AsyncMock(return_value=task)),
        patch.object(module.task_repo, "save", new=AsyncMock()) as save,
        patch.object(service, "queue_return", new=AsyncMock()) as queue_return,
    ):
        await service.settle(run)
    assert task.status == status
    assert task.delivery == "delivered"
    save.assert_awaited_once_with(service.db, task)
    queue_return.assert_not_awaited()


async def test_a_lost_queued_personal_task_is_reported_without_returning_or_restarting() -> None:
    task = queued_task()
    service = module.ConversationTaskService(MagicMock())
    with (
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=task)),
        patch.object(module.task_repo, "save", new=AsyncMock()) as save,
        patch.object(service, "queue_return", new=AsyncMock()) as queue_return,
    ):
        await service.interrupted(task.id, organization_id=task.organization_id, returning=False)
    assert task.status == "interrupted"
    assert task.delivery == "delivered"
    assert task.outcome is not None and "not restarted automatically" in task.outcome
    save.assert_awaited_once_with(service.db, task)
    queue_return.assert_not_awaited()
