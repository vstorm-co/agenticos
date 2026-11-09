"""Delivery job failures expose a controlled retry message, not SQL or answer text."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import DatabaseError
from app.worker.errors import describe
from app.worker.jobs import DeliverRoutineAnswer
from app.worker.tasks.trigger_tasks import deliver_routine_answer

pytestmark = pytest.mark.anyio


async def test_a_delivery_failure_remains_retryable_without_leaking_its_payload() -> None:
    @asynccontextmanager
    async def context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    sql = SQLAlchemyError("SQL params contain private-answer-and-token")
    with (
        patch("app.worker.tasks.trigger_tasks.get_worker_db_context", new=context),
        patch("app.services.agent_trigger.AgentTriggerService") as service,
        pytest.raises(DatabaseError) as caught,
    ):
        service.return_value.deliver_resumed_answer = AsyncMock(side_effect=sql)
        await deliver_routine_answer(DeliverRoutineAnswer(organization_id=uuid4(), run_id=uuid4()))
    assert "Retry its delivery" in describe(caught.value)
    assert "private-answer-and-token" not in describe(caught.value)
    assert caught.value.__cause__ is sql


async def test_the_production_worker_accepts_and_dispatches_the_declared_handoff() -> None:
    from app.worker.handlers import production
    from app.worker.jobs import DELIVER_ROUTINE_ANSWER

    @asynccontextmanager
    async def context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    organization_id, run_id = uuid4(), uuid4()
    with (
        patch("app.worker.tasks.trigger_tasks.get_worker_db_context", new=context),
        patch("app.services.agent_trigger.AgentTriggerService") as service,
    ):
        delivered = AsyncMock()
        service.return_value.deliver_resumed_answer = delivered
        assert (
            await production()[DELIVER_ROUTINE_ANSWER.kind].execute(
                {"organization_id": str(organization_id), "run_id": str(run_id)}
            )
            is None
        )
        delivered.assert_awaited_once_with(organization_id, run_id)
