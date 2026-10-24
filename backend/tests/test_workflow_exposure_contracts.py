"""The schedule a trigger node accepts, and a chat run's answer (#1792).

The database CHECK says the same things about an exposure's columns; these are
the problems a publish reports on the node instead of an IntegrityError, and
the one branch of a chat answer the end-to-end suite does not reach - a run
with a text answer.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.services.workflow_execution import delivery
from app.workflows.nodes._triggers import ScheduleTriggerConfig

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "fields",
    [
        {"schedule_kind": "interval", "interval_seconds": None},
        {"schedule_kind": "interval", "interval_seconds": 30},
        {"schedule_kind": "cron"},
        {"schedule_kind": "cron", "cron_expression": "0 0 31 2 *"},
        {"schedule_kind": "cron", "cron_expression": "not cron"},
    ],
    ids=[
        "interval-without-seconds",
        "interval-under-the-floor",
        "cron-without-expression",
        "cron-that-never-fires",
        "cron-that-does-not-parse",
    ],
)
def test_a_schedule_trigger_that_could_never_fire_is_refused(fields):
    with pytest.raises(ValidationError):
        ScheduleTriggerConfig.model_validate(fields)


def test_a_schedule_trigger_defaults_to_hourly():
    config = ScheduleTriggerConfig()
    assert (config.schedule_kind, config.interval_seconds, config.input) == ("interval", 3600, {})
    # A cron schedule keeps the interval's default, which switching it on ignores.
    assert (
        ScheduleTriggerConfig(schedule_kind="cron", cron_expression="0 9 * * 1-5").cron_expression
        == "0 9 * * 1-5"
    )


async def test_a_chat_run_with_a_text_answer_says_it_in_the_message():
    run = MagicMock(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        reply_conversation_id=uuid.uuid4(),
        parent_node_run_id=None,
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


@pytest.mark.security
@pytest.mark.parametrize("active", [None, False])
async def test_background_authority_refuses_a_user_lost_after_membership_read(monkeypatch, active):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module("app.services.workflow_exposure")
    monkeypatch.setattr(
        module.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role="viewer"))
    )
    user = None if active is None else SimpleNamespace(is_active=False, is_app_admin=True)
    monkeypatch.setattr(module.user_repo, "get_by_id", AsyncMock(return_value=user))
    exposure = SimpleNamespace(
        execution_principal_user_id=uuid.uuid4(), organization_id=uuid.uuid4()
    )
    assert await module.WorkflowExposureService(MagicMock())._fire_context(exposure) is None
