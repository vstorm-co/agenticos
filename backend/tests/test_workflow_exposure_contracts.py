"""The shapes a workflow exposure accepts, and a chat run's answer (#1792).

The database CHECK says the same things about the columns; these are the 422s
a request gets instead of an IntegrityError, and the one branch of a chat
answer the end-to-end suite does not reach - a run with a text answer.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.workflow_exposure import WorkflowExposureCreate, WorkflowExposureUpdate
from app.services.workflow_execution import delivery

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "fields",
    [
        {"adapter": "webhook", "schedule_kind": "interval", "interval_seconds": 60},
        {"adapter": "webhook", "run_input": {"a": 1}},
        {"adapter": "schedule"},
        {"adapter": "schedule", "schedule_kind": "interval"},
        {"adapter": "schedule", "schedule_kind": "interval", "interval_seconds": 30},
        {
            "adapter": "schedule",
            "schedule_kind": "interval",
            "interval_seconds": 60,
            "cron_expression": "* * * * *",
        },
        {"adapter": "schedule", "schedule_kind": "cron"},
        {
            "adapter": "schedule",
            "schedule_kind": "cron",
            "cron_expression": "* * * * *",
            "interval_seconds": 60,
        },
        {"adapter": "schedule", "schedule_kind": "cron", "cron_expression": "0 0 31 2 *"},
    ],
    ids=[
        "webhook-with-cadence",
        "webhook-with-input",
        "schedule-without-kind",
        "interval-without-seconds",
        "interval-under-the-floor",
        "interval-with-cron",
        "cron-without-expression",
        "cron-with-interval",
        "cron-that-never-fires",
    ],
)
def test_a_create_that_could_never_be_stored_is_a_422(fields):
    with pytest.raises(ValidationError):
        WorkflowExposureCreate.model_validate(fields)


def test_an_update_names_a_cadence_with_its_kind():
    with pytest.raises(ValidationError, match="needs its schedule_kind"):
        WorkflowExposureUpdate(interval_seconds=120)
    assert WorkflowExposureUpdate(is_active=False).schedule_kind is None


async def test_a_chat_run_with_a_text_answer_says_it_in_the_message():
    run = MagicMock(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        reply_conversation_id=uuid.uuid4(),
        status="failed",
        output={"text": "Three leads are ready."},
        error={"code": "X", "message": "The last step failed"},
    )
    with (
        patch.object(delivery.conversation_repo, "create_message", new=AsyncMock()) as write,
        patch.object(delivery.workflow_repo, "get", new=AsyncMock(return_value=None)),
    ):
        await delivery.deliver_result(MagicMock(), run=run)
    kwargs = write.await_args.kwargs
    assert kwargs["content"] == "Three leads are ready."
    # A workflow deleted under a finishing run leaves the card without a name.
    card, words = kwargs["parts"]
    assert "workflow_name" not in card
    assert card["error"] == "The last step failed"
    assert words == {"type": "text", "text": "Three leads are ready."}


async def test_a_runs_files_are_listed_from_what_the_query_answers():
    """The listing's own return, which the end-to-end suites reach only after an await
    the coverage tracer loses."""
    from app.repositories import workflow_file as workflow_file_repo

    row = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = MagicMock(execute=AsyncMock(return_value=result))
    assert await workflow_file_repo.list_for_run(
        db, workflow_run_id=uuid.uuid4(), organization_id=uuid.uuid4()
    ) == [row]
