"""`dispatch_queue.priority_for`: which queue priority a run's nodes take."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.workflow_run import WorkflowRunTrigger
from app.services.workflow_execution import dispatch_queue
from app.worker.jobs import Priority

pytestmark = pytest.mark.anyio

PATH = "app.services.workflow_execution.dispatch_queue"


def _run(trigger: WorkflowRunTrigger, caller: MagicMock | None = None) -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.organization_id = uuid.uuid4()
    run.triggered_by = trigger.value
    run.causation_run_id = caller.id if caller else None
    return run


@pytest.mark.parametrize(
    ("trigger", "priority"),
    [
        (WorkflowRunTrigger.WEBHOOK, Priority.INTERACTIVE),
        (WorkflowRunTrigger.APP, Priority.INTERACTIVE),
        (WorkflowRunTrigger.SCHEDULE, Priority.SCHEDULED),
    ],
)
async def test_a_run_takes_its_priority_from_what_started_it(trigger, priority) -> None:
    assert await dispatch_queue.priority_for(AsyncMock(), _run(trigger)) == priority


async def test_a_called_workflow_takes_its_callers_priority_up_the_chain() -> None:
    webhook = _run(WorkflowRunTrigger.WEBHOOK)
    middle = _run(WorkflowRunTrigger.WORKFLOW_CALL, webhook)
    leaf = _run(WorkflowRunTrigger.WORKFLOW_CALL, middle)
    runs = {middle.id: middle, webhook.id: webhook}

    async def get_run(_db, run_id, *, organization_id):
        return runs[run_id]

    with patch(f"{PATH}.workflow_run_repo.get_run", new=get_run):
        assert await dispatch_queue.priority_for(AsyncMock(), leaf) is Priority.INTERACTIVE


async def test_a_called_workflow_of_a_scheduled_run_stays_scheduled() -> None:
    schedule = _run(WorkflowRunTrigger.SCHEDULE)
    leaf = _run(WorkflowRunTrigger.WORKFLOW_CALL, schedule)

    with patch(f"{PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=schedule)):
        assert await dispatch_queue.priority_for(AsyncMock(), leaf) is Priority.SCHEDULED


async def test_a_call_whose_caller_is_gone_is_scheduled() -> None:
    orphan = _run(WorkflowRunTrigger.WORKFLOW_CALL, _run(WorkflowRunTrigger.API))

    with patch(f"{PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)):
        assert await dispatch_queue.priority_for(AsyncMock(), orphan) is Priority.SCHEDULED


async def test_a_call_with_no_recorded_caller_is_scheduled() -> None:
    assert (
        await dispatch_queue.priority_for(AsyncMock(), _run(WorkflowRunTrigger.WORKFLOW_CALL))
        is Priority.SCHEDULED
    )


async def test_the_backstop_job_for_a_row_keeps_its_runs_priority() -> None:
    webhook = _run(WorkflowRunTrigger.WEBHOOK)
    row = MagicMock(
        workflow_run_id=webhook.id,
        node_run_id=uuid.uuid4(),
        organization_id=webhook.organization_id,
    )

    with (
        patch(f"{PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=webhook)),
        patch(f"{PATH}.enqueue", new=AsyncMock()) as enqueue,
    ):
        await dispatch_queue.queue_dispatch_job(AsyncMock(), row)
        assert enqueue.await_args.kwargs["priority"] is Priority.INTERACTIVE

    with (
        patch(f"{PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)),
        patch(f"{PATH}.enqueue", new=AsyncMock()) as enqueue,
    ):
        await dispatch_queue.queue_dispatch_job(AsyncMock(), row)
        assert enqueue.await_args.kwargs["priority"] is Priority.SCHEDULED


async def test_a_chain_of_calls_that_loops_back_ends_at_the_hop_limit() -> None:
    """A corrupt chain cannot send the walk round for ever."""
    looped = _run(WorkflowRunTrigger.WORKFLOW_CALL)
    looped.causation_run_id = looped.id

    with patch(f"{PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=looped)) as get:
        assert await dispatch_queue.priority_for(AsyncMock(), looped) is Priority.SCHEDULED

    assert get.await_count == dispatch_queue._MAX_CALL_HOPS
