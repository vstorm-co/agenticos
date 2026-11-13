"""The trigger heartbeat claims and queues in one transaction (#2219).

`check_agent_triggers` used to claim the due triggers, commit, and then submit
a Prefect run for each - and a submit that raised could not say whether the run
had started (#589), so the marker had to be left for its lease. Now the claim,
the advance and the queued fires are one session's work: they commit together
or not at all, and the heartbeat has no second step left to fail.
"""

import contextlib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks import trigger_tasks

pytestmark = pytest.mark.anyio


async def test_the_heartbeat_claims_on_one_session_at_the_ticks_own_time() -> None:
    opened: list[MagicMock] = []

    @contextlib.asynccontextmanager
    async def tracking_context() -> AsyncGenerator[MagicMock]:
        db = MagicMock()
        opened.append(db)
        yield db

    service = MagicMock()
    service.expire_due = AsyncMock(return_value=0)
    service.resume_device_waits = AsyncMock(return_value=0)
    service.claim_and_advance = AsyncMock(return_value=[MagicMock(id=uuid.uuid4())])
    before = datetime.now(UTC)
    with (
        patch.object(trigger_tasks, "get_worker_db_context", tracking_context),
        patch("app.services.agent_trigger.AgentTriggerService", return_value=service) as built,
    ):
        await trigger_tasks.check_agent_triggers()

    service.expire_due.assert_awaited_once_with(
        now=service.claim_and_advance.call_args.kwargs["now"]
    )
    service.resume_device_waits.assert_awaited_once_with()
    assert len(opened) == 1, "the claim and its fires share one transaction"
    built.assert_called_once_with(opened[0])
    assert before <= service.claim_and_advance.call_args.kwargs["now"] <= datetime.now(UTC)


async def test_fire_job_forwards_the_stable_device_activation() -> None:
    from app.schemas.agent_trigger import TriggerFireResult
    from app.worker.jobs import FireTrigger

    @contextlib.asynccontextmanager
    async def context() -> AsyncGenerator[MagicMock]:
        yield MagicMock()

    payload = FireTrigger(trigger_id=uuid.uuid4(), activation_id=uuid.uuid4())
    with (
        patch.object(trigger_tasks, "get_worker_db_context", context),
        patch("app.services.agent_trigger.AgentTriggerService") as service,
    ):
        outcome = TriggerFireResult(outcome="blocked", attempt_id=uuid.uuid4())
        service.return_value.fire_job = AsyncMock(return_value=outcome)
        assert await trigger_tasks.fire_trigger(payload) == outcome
        service.return_value.fire_job.assert_awaited_once_with(payload)
