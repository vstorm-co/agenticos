"""An eval run is a job of its own, and the worker runs it."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import jobs
from app.worker.handlers import production
from app.worker.jobs import RunEval
from app.worker.tasks import eval_tasks

pytestmark = pytest.mark.anyio


async def test_the_job_runs_the_worker_for_that_run() -> None:
    run_id, org_id = uuid.uuid4(), uuid.uuid4()
    worker = MagicMock(run=AsyncMock())
    with patch("app.services.eval_run_worker.EvalRunWorker", return_value=worker) as built:
        await eval_tasks.run_eval(RunEval(eval_run_id=run_id, organization_id=org_id))

    built.assert_called_once_with(run_id, org_id)
    worker.run.assert_awaited_once()


def test_a_dead_eval_is_not_run_again() -> None:
    """Its answered cases were paid for; the abandoned-eval sweep fails it instead."""
    assert jobs.RUN_EVAL.max_attempts == 1
    assert jobs.RUN_EVAL.kind in production()
