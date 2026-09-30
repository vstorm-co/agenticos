"""How a webhook delivery waits for its graph's answer, called directly.

The integration tests drive a real run; these pin each outcome of the wait
without one, so none depends on how fast a background drive gets scheduled.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.schemas.workflow_exposure import WebhookAdmitted, WebhookAnswer
from app.services.workflow_execution.exceptions import WorkflowWebhookUnansweredError
from app.services.workflow_exposure import WorkflowExposureService

pytestmark = pytest.mark.anyio

_ANSWER = {"status_code": 201, "headers": {"X-Lead": "yes"}, "body": {"id": 1}}
_REPO = "app.services.workflow_exposure.workflow_run_repo.get_run_answer"


def _service() -> WorkflowExposureService:
    db = MagicMock(commit=AsyncMock(), info={})
    return WorkflowExposureService(db)


async def test_a_retry_gets_the_answer_its_first_run_gave():
    with patch(_REPO, new=AsyncMock(return_value=("running", _ANSWER))):
        assert await _service()._replay(uuid.uuid4()) == WebhookAnswer.model_validate(_ANSWER)


async def test_a_retry_of_a_run_that_has_not_answered_is_a_duplicate():
    run_id = uuid.uuid4()
    with patch(_REPO, new=AsyncMock(return_value=("running", None))):
        assert await _service()._replay(run_id) == WebhookAdmitted(run_id=run_id, duplicate=True)


async def test_the_wait_returns_the_answer_once_the_run_records_one():
    answers = AsyncMock(side_effect=[("running", None), ("running", _ANSWER)])
    with (
        patch(_REPO, new=answers),
        patch("app.services.workflow_exposure.anyio.sleep", new=AsyncMock()),
    ):
        answer = await _service()._answer(uuid.uuid4())
    assert answer == WebhookAnswer.model_validate(_ANSWER)


@pytest.mark.parametrize("status", ["failed", "cancelled", "budget_exceeded"])
async def test_a_run_that_ends_badly_without_answering_is_an_error(status):
    with (
        patch(_REPO, new=AsyncMock(return_value=(status, None))),
        pytest.raises(WorkflowWebhookUnansweredError) as refused,
    ):
        await _service()._answer(uuid.uuid4())
    assert refused.value.details["status"] == status


async def test_a_run_that_succeeds_without_answering_answers_nothing():
    with patch(_REPO, new=AsyncMock(return_value=("succeeded", None))):
        assert await _service()._answer(uuid.uuid4()) is None


async def test_the_wait_gives_up_after_its_timeout(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS", 0.05)
    with patch(_REPO, new=AsyncMock(return_value=("running", None))):
        assert await _service()._answer(uuid.uuid4()) is None
