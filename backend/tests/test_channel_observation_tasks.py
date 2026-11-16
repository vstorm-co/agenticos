"""Worker jobs preserve their observation scope and scheduled time."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.worker.jobs import AnalyzeChannel, Tick
from app.worker.tasks.channel_observation_tasks import analyze_channel, sweep_channels

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_worker_observation_handlers_keep_the_job_scope_and_scheduled_time():
    db = object()

    @asynccontextmanager
    async def session():
        yield db

    now = datetime.now(UTC)
    payload = AnalyzeChannel(
        organization_id=uuid4(),
        observation_id=uuid4(),
        generation=uuid4(),
        admission_hash="a" * 64,
        revision=1,
        messages=[{"text": "New message"}],
    )
    with (
        patch("app.worker.tasks.channel_observation_tasks.get_db_context", session),
        patch(
            "app.worker.tasks.channel_observation_tasks.sweep", new=AsyncMock(return_value=3)
        ) as sweep,
        patch(
            "app.worker.tasks.channel_observation_tasks.analyze", new=AsyncMock(return_value=False)
        ) as analyze,
        patch("app.worker.tasks.channel_observation_tasks.ensure_channel_adapters") as register,
    ):
        assert await sweep_channels(Tick(scheduled_for=now)) == 3
        assert not await analyze_channel(payload)
    sweep.assert_awaited_once_with(db, now=now)
    analyze.assert_awaited_once_with(db, payload)
    register.assert_called_once_with()
