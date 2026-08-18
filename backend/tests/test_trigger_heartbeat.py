"""The heartbeat's dispatch loop isolates each submission and preserves its marker.

`check_agent_triggers_flow` claims the due triggers in one committed transaction,
then submits a run for each. Because the claim commits *before* the loop, a trigger
whose `run_deployment` raises has already had its `next_fire_at` advanced *and* its
`fire_in_flight_since` marker set - so a bare loop that let the exception propagate
would abort after the first failure and leave the rest of the batch with an advanced
schedule and no run: a missed fire nobody asked for. The loop isolates each dispatch
instead.

The marker of a failed dispatch is deliberately *left set*: `run_deployment` can
accept the flow creation on the Prefect API and then lose or time out the response,
so a submit that raised may still have started the child flow. Clearing the marker
would let the next tick fire again on top of that accepted-but-queued run (#589), so
`_FIRE_LEASE`, not this loop, governs re-dispatch.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
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
    never the whole batch - and each dispatch is handed the tick's own claim `now` as
    `claimed_at`, the same timestamp the claim stamped on every marker, so the fire it
    starts clears only the marker its claim set."""
    triggers = [MagicMock(id=uuid.uuid4()) for _ in range(3)]
    attempted: list[tuple[str, datetime]] = []

    async def dispatch(trigger_id: str, claimed_at: datetime) -> None:
        attempted.append((trigger_id, claimed_at))
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

    # Every trigger is attempted, and each with the exact `now` handed to the claim.
    claimed_now = service.claim_and_advance.call_args.kwargs["now"]
    assert attempted == [(str(t.id), claimed_now) for t in triggers]


async def test_a_failed_dispatch_does_not_release_the_marker() -> None:
    """A submit that raised may still have created the child flow, so the marker is
    left for the lease rather than cleared - the loop opens no second session to
    release it, and the trigger's own marker attribute is untouched."""
    trigger = MagicMock(id=uuid.uuid4(), fire_in_flight_since=datetime(2026, 1, 1, tzinfo=UTC))
    opened: list[object] = []

    @contextlib.asynccontextmanager
    async def tracking_context() -> AsyncGenerator[MagicMock, None]:
        db = MagicMock()
        opened.append(db)
        yield db

    async def dispatch(trigger_id: str, claimed_at: datetime) -> None:
        raise RuntimeError("prefect api 503")

    service = MagicMock()
    service.claim_and_advance = AsyncMock(return_value=[trigger])
    with (
        patch.object(trigger_tasks, "get_worker_db_context", tracking_context),
        patch.object(trigger_tasks, "_dispatch", side_effect=dispatch),
        patch("app.services.agent_trigger.AgentTriggerService", return_value=service),
    ):
        await trigger_tasks.check_agent_triggers_flow.fn()  # must not raise

    # Exactly one session - the claim's. No second one is opened to release a marker.
    assert len(opened) == 1
    assert trigger.fire_in_flight_since == datetime(2026, 1, 1, tzinfo=UTC)
