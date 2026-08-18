"""The heartbeat that dispatches the triggers due now.

`check_agent_triggers_flow` advances every claimed trigger's `next_fire_at` in
one committed batch and then hands each off to its own capped flow run. Because
the advance already happened, a hand-off that raises would not be re-claimed
until the trigger's next cadence - so one failing dispatch must not strand the
rest of the batch. The flow's own function is exercised through `.fn`, so the
test asserts the loop without standing up Prefect's engine.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.worker.tasks.trigger_tasks import check_agent_triggers_flow

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _db() -> Any:
    yield MagicMock()


async def test_one_failing_dispatch_does_not_stop_the_rest(monkeypatch: pytest.MonkeyPatch):
    triggers = [MagicMock(id=uuid.uuid4()) for _ in range(3)]
    service = MagicMock(claim_and_advance=AsyncMock(return_value=triggers))
    attempted: list[str] = []

    async def _dispatch(trigger_id: str, *, event_context: str | None = None) -> None:
        attempted.append(trigger_id)
        if trigger_id == str(triggers[1].id):
            raise RuntimeError("prefect unreachable")

    monkeypatch.setattr("app.worker.tasks.trigger_tasks.get_worker_db_context", _db)
    monkeypatch.setattr(
        "app.services.agent_trigger.AgentTriggerService", MagicMock(return_value=service)
    )
    monkeypatch.setattr("app.worker.tasks.trigger_tasks.dispatch_trigger_fire", _dispatch)

    await check_agent_triggers_flow.fn()

    # Every claimed trigger was attempted - the middle one raising did not skip
    # the third, which a bare loop would have.
    assert attempted == [str(t.id) for t in triggers]
