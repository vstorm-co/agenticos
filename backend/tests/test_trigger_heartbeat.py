"""The heartbeat's dispatch loop isolates each submission.

`check_agent_triggers_flow` claims the due triggers in one committed
transaction, then submits a run for each. Because the claim commits *before* the
loop, a trigger whose `run_deployment` raises has already had its `next_fire_at`
advanced - so a bare loop that let the exception propagate would abort after the
first failure and leave the rest of the batch with an advanced schedule and no
run: a missed fire nobody asked for. The loop isolates each dispatch instead.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks import trigger_tasks

pytestmark = pytest.mark.anyio


@contextlib.asynccontextmanager
async def _fake_db_context() -> AsyncGenerator[MagicMock, None]:
    yield MagicMock()


async def test_one_failed_dispatch_does_not_drop_the_rest_of_the_batch() -> None:
    """Three triggers are claimed; the middle one's dispatch raises. The other two
    are still submitted - one transient Prefect error costs its own trigger a fire,
    never the whole batch."""
    triggers = [MagicMock(id=uuid.uuid4()) for _ in range(3)]
    attempted: list[str] = []

    async def dispatch(trigger_id: str) -> None:
        attempted.append(trigger_id)
        if trigger_id == str(triggers[1].id):
            raise RuntimeError("prefect api 503")

    service = MagicMock()
    service.claim_and_advance = AsyncMock(return_value=triggers)
    with (
        patch.object(trigger_tasks, "get_worker_db_context", _fake_db_context),
        patch.object(trigger_tasks, "_dispatch", side_effect=dispatch),
        patch("app.services.agent_trigger.AgentTriggerService", return_value=service),
    ):
        await trigger_tasks.check_agent_triggers_flow.fn()  # must not raise

    assert attempted == [str(t.id) for t in triggers]
