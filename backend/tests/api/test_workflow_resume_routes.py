"""The resume link's door, through the app: no sign-in, and what it hands the service (#1947).

`tests/integration/test_workflow_resume.py` drives the real service; this is the
wire contract with it mocked.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app
from app.schemas.workflow_run import WorkflowResumed
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError

pytestmark = pytest.mark.anyio


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    service = MagicMock()
    app.dependency_overrides[deps.get_workflow_resume_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service
    app.dependency_overrides.clear()


async def test_a_call_needs_no_sign_in_and_hands_on_the_body_as_sent(wired):
    client, service = wired
    run_id = uuid.uuid4()
    service.resume = AsyncMock(return_value=WorkflowResumed(run_id=run_id, resumed=1))

    answered = await client.post(
        f"{settings.API_V1_STR}/workflow-resume/{run_id}/the-token", content=b'{"ok": true}'
    )

    assert answered.status_code == 202
    assert answered.json() == {"run_id": str(run_id), "resumed": 1}
    service.resume.assert_awaited_once_with(run_id, "the-token", body=b'{"ok": true}')


@pytest.mark.security
async def test_a_link_that_is_not_the_runs_answers_not_found(wired):
    client, service = wired
    run_id = uuid.uuid4()
    service.resume = AsyncMock(side_effect=WorkflowRunNotFoundError(run_id=run_id))

    answered = await client.post(f"{settings.API_V1_STR}/workflow-resume/{run_id}/guess")

    assert answered.status_code == 404
    assert answered.json()["error"]["code"] == "WORKFLOW_RUN_NOT_FOUND"
