"""A resumed task owns the same cancellable lifecycle as its initial attempt."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services import conversation_tasks as module

pytestmark = pytest.mark.anyio


@dataclass
class Task:
    status: str = "awaiting_approval"
    delivery: str = "pending"
    return_run_id: UUID | None = None


@asynccontextmanager
async def database() -> AsyncGenerator[MagicMock]:
    yield MagicMock()


async def test_an_ordinary_run_never_queries_task_state() -> None:
    with patch.object(module.task_repo, "get", new=AsyncMock()) as get:
        async with module.task_execution(None, uuid4(), uuid4()):
            pass
        get.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
async def test_a_stopped_or_deleted_task_cannot_enter_its_next_model_call(missing: bool) -> None:
    with (
        patch.object(module, "get_db_context", database),
        patch.object(
            module.task_repo,
            "get",
            new=AsyncMock(return_value=None if missing else Task(status="cancelled")),
        ),
        pytest.raises(module.ConversationTaskStopped),
    ):
        async with module.task_execution(uuid4(), uuid4(), uuid4()):
            pytest.fail("No model may start after Stop")


@pytest.mark.parametrize("returning", [False, True])
async def test_stop_cancels_and_joins_the_current_segment_including_resumed_work(
    returning: bool,
) -> None:
    run_id = uuid4()
    row = Task(
        status="completed" if returning else "awaiting_approval",
        delivery="running",
        return_run_id=run_id if returning else None,
    )
    closed = False
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module, "CANCEL_POLL_SECONDS", 0.001),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        pytest.raises(module.ConversationTaskStopped),
    ):
        async with module.task_execution(uuid4(), uuid4(), run_id):
            if returning:
                row.delivery = "interrupted"
            else:
                row.status = "cancelled"
            try:
                async with asyncio.timeout(1):
                    await asyncio.Event().wait()
            finally:
                closed = True
    assert closed


async def test_monitor_is_closed_after_a_successful_segment() -> None:
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module, "CANCEL_POLL_SECONDS", 0.001),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=Task())) as get,
    ):
        async with module.task_execution(uuid4(), uuid4(), uuid4()):
            await asyncio.sleep(0.01)
        reads = get.await_count
        await asyncio.sleep(0.01)
        assert get.await_count == reads
        assert reads > 1


async def test_a_model_failure_keeps_its_original_exception_identity() -> None:
    failure = ValueError("original model failure")
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=Task())),
        pytest.raises(ValueError) as raised,
    ):
        async with module.task_execution(uuid4(), uuid4(), uuid4()):
            raise failure
    assert raised.value is failure


async def test_a_cleanup_failure_is_not_hidden_by_a_concurrent_stop() -> None:
    row = Task()
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module, "CANCEL_POLL_SECONDS", 0.001),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        pytest.raises(ExceptionGroup) as raised,
    ):
        async with module.task_execution(uuid4(), uuid4(), uuid4()):
            row.status = "cancelled"
            try:
                async with asyncio.timeout(1):
                    await asyncio.Event().wait()
            finally:
                raise ValueError("cleanup failed")
    assert {type(error) for error in raised.value.exceptions} == {
        ValueError,
        module.ConversationTaskStopped,
    }


async def test_external_cancellation_still_propagates_and_joins_the_monitor() -> None:
    entered = asyncio.Event()
    with (
        patch.object(module, "get_db_context", database),
        patch.object(module, "CANCEL_POLL_SECONDS", 0.001),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=Task())) as get,
    ):

        async def execution() -> None:
            async with module.task_execution(uuid4(), uuid4(), uuid4()):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(execution())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        reads = get.await_count
        await asyncio.sleep(0.01)
        assert get.await_count == reads
