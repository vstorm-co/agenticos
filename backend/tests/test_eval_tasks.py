"""An eval run is handed to the worker as its own flow run, and the flow runs it."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks import eval_tasks

pytestmark = pytest.mark.anyio


async def test_dispatch_submits_the_run_and_does_not_wait() -> None:
    with patch.object(eval_tasks, "run_deployment", new=AsyncMock()) as submit:
        await eval_tasks.dispatch_eval_run("run-1", "org-1")

    submit.assert_awaited_once_with(
        name="run-eval/run-eval",
        parameters={"eval_run_id": "run-1", "organization_id": "org-1"},
        timeout=0,
    )


async def test_the_flow_runs_the_worker_for_that_run() -> None:
    run_id, org_id = uuid.uuid4(), uuid.uuid4()
    worker = MagicMock(run=AsyncMock())
    with (
        patch.object(eval_tasks, "setup_logging"),
        patch.object(eval_tasks, "setup_worker_observability"),
        patch("app.services.eval_run_worker.EvalRunWorker", return_value=worker) as built,
    ):
        await eval_tasks.run_eval_flow.fn(str(run_id), str(org_id))

    built.assert_called_once_with(run_id, org_id)
    worker.run.assert_awaited_once()
