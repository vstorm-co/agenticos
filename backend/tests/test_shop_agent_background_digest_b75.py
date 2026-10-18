"""B75 — shop digest Prefect beat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.worker.tasks.shop_agent_background_job import run_due_shop_digest_jobs

pytestmark = pytest.mark.anyio


async def test_digest_beat_queues_due_jobs() -> None:
    db = MagicMock()
    job = MagicMock(id=uuid4())
    with (
        patch(
            "app.worker.tasks.shop_agent_background_job.job_repo.list_due_digest_jobs",
            new=AsyncMock(return_value=[job]),
        ),
        patch(
            "app.worker.tasks.shop_agent_background_job.spawn",
        ) as spawn_mock,
    ):
        out = await run_due_shop_digest_jobs(db)
    assert out == {"queued": 1}
    spawn_mock.assert_called_once()
