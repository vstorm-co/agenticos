"""What an eval or authoring job that ended for good leaves behind, settled.

A job withdrawn from the queue, timed out or whose worker died never reaches
the code that closes its eval run or its authoring request, which would hold
the suite, the gate and the organization's eval slots. The worker hands the
ending to these.
"""

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import handlers
from app.worker.jobs import RUN_AUTHORING, RUN_EVAL, RunAuthoring, RunEval

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _db() -> Any:
    yield MagicMock()


async def test_a_lost_eval_job_settles_its_run_in_its_organization() -> None:
    job = RunEval(eval_run_id=uuid.uuid4(), organization_id=uuid.uuid4())
    reaper = MagicMock(settle_lost_eval=AsyncMock())
    with (
        patch("app.worker.tasks.eval_tasks.get_worker_db_context", _db),
        patch("app.worker.tasks.eval_tasks.RunReaperService", return_value=reaper),
    ):
        await handlers.settle_ended(RUN_EVAL.kind, RUN_EVAL.dump(job), "cancelled")

    reaper.settle_lost_eval.assert_awaited_once_with(
        job.eval_run_id, organization_id=job.organization_id, why="cancelled"
    )


async def test_a_lost_authoring_job_settles_its_request_in_its_organization() -> None:
    job = RunAuthoring(request_id=uuid.uuid4(), organization_id=uuid.uuid4())
    reaper = MagicMock(settle_lost_authoring=AsyncMock())
    with (
        patch("app.worker.tasks.authoring_tasks.get_worker_db_context", _db),
        patch("app.worker.tasks.authoring_tasks.RunReaperService", return_value=reaper),
    ):
        await handlers.settle_ended(RUN_AUTHORING.kind, RUN_AUTHORING.dump(job), "killed")

    reaper.settle_lost_authoring.assert_awaited_once_with(
        job.request_id, organization_id=job.organization_id, why="killed"
    )
