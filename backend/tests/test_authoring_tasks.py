"""An Improve or Verify is handed to the worker as its own flow run, and the flow runs it."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks import authoring_tasks

pytestmark = pytest.mark.anyio


async def test_dispatch_submits_the_request_and_does_not_wait() -> None:
    with patch.object(authoring_tasks, "run_deployment", new=AsyncMock()) as submit:
        await authoring_tasks.dispatch_authoring_request("request-1", "org-1")

    submit.assert_awaited_once_with(
        name="run-authoring/run-authoring",
        parameters={"request_id": "request-1", "organization_id": "org-1"},
        timeout=0,
    )


async def test_the_flow_runs_the_worker_for_that_request() -> None:
    request_id, org_id = uuid.uuid4(), uuid.uuid4()
    worker = MagicMock(run=AsyncMock())
    with (
        patch.object(authoring_tasks, "setup_logging"),
        patch.object(authoring_tasks, "setup_worker_observability"),
        patch("app.services.authoring_worker.AuthoringWorker", return_value=worker) as built,
    ):
        await authoring_tasks.run_authoring_flow.fn(str(request_id), str(org_id))

    built.assert_called_once_with(request_id, org_id)
    worker.run.assert_awaited_once()
