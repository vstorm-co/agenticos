"""An Improve or Verify is a job of its own, and the worker runs it."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import jobs
from app.worker.handlers import production
from app.worker.jobs import RunAuthoring
from app.worker.tasks import authoring_tasks

pytestmark = pytest.mark.anyio


async def test_the_job_runs_the_worker_for_that_request() -> None:
    request_id, org_id = uuid.uuid4(), uuid.uuid4()
    worker = MagicMock(run=AsyncMock())
    with patch("app.services.authoring_worker.AuthoringWorker", return_value=worker) as built:
        await authoring_tasks.run_authoring(
            RunAuthoring(request_id=request_id, organization_id=org_id)
        )

    built.assert_called_once_with(request_id, org_id)
    worker.run.assert_awaited_once()


def test_a_dead_request_is_not_run_again() -> None:
    """Each improver call is billed; a request its worker died under reads as failed."""
    assert jobs.RUN_AUTHORING.max_attempts == 1
    assert jobs.RUN_AUTHORING.kind in production()
