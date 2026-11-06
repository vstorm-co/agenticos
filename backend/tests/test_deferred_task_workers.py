"""The durable worker payload reaches the intended service once, without losing cleanup."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.worker.jobs import DialPhone, WakeTask
from app.worker.tasks import task_tasks, voice_tasks

pytestmark = pytest.mark.anyio


async def test_task_wakeup_uses_the_job_session_and_exact_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()

    @asynccontextmanager
    async def session():
        yield db

    execute = AsyncMock()
    monkeypatch.setattr(task_tasks, "get_worker_db_context", session)
    monkeypatch.setattr(
        task_tasks,
        "TaskExecution",
        lambda actual: MagicMock(wake=execute) if actual is db else None,
    )
    payload = WakeTask(task_id=uuid4(), organization_id=uuid4(), revision=1)
    await task_tasks.wake_task(payload)
    execute.assert_awaited_once_with(payload)


async def test_telephone_jobs_dial_or_end_the_exact_durable_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.telephony import runtime

    dial, end = AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime, "dial", dial)
    monkeypatch.setattr(runtime, "end_media", end)
    payload = DialPhone(call_id=uuid4())
    await voice_tasks.dial_phone(payload)
    await voice_tasks.end_phone(payload)
    dial.assert_awaited_once_with(payload.call_id)
    assert end.await_args.args == (payload.call_id,)
    assert end.await_args.kwargs["sessions"] is voice_tasks.get_worker_db_context
