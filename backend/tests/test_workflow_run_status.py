"""`run_status.derive_status`: a run reads as the most severe of its live steps."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.workflow_run import NodeRunStatus, WaitingReason, WorkflowRunStatus
from app.services.workflow_execution import run_status
from app.services.workflow_execution.run_status import DerivedStatus, derive_status

pytestmark = pytest.mark.anyio

RUNNING = (NodeRunStatus.RUNNING, None)
APPROVAL = (NodeRunStatus.WAITING, WaitingReason.APPROVAL)
BACKOFF = (NodeRunStatus.WAITING, WaitingReason.RETRY_BACKOFF)
TIMER = (NodeRunStatus.WAITING, WaitingReason.TIMER)
CALLED = (NodeRunStatus.WAITING, WaitingReason.EXTERNAL_EVENT)
ATTENTION = (NodeRunStatus.NEEDS_ATTENTION, None)


def test_needs_attention_outranks_every_wait():
    assert derive_status([APPROVAL, BACKOFF, RUNNING, ATTENTION]) == DerivedStatus(
        WorkflowRunStatus.NEEDS_ATTENTION, None
    )


def test_an_approval_wait_outranks_a_running_sibling():
    assert derive_status([RUNNING, APPROVAL]) == DerivedStatus(
        WorkflowRunStatus.WAITING_APPROVAL, "approval"
    )
    assert derive_status([BACKOFF, APPROVAL]).status is WorkflowRunStatus.WAITING_APPROVAL


def test_a_retry_wait_outranks_a_running_sibling_but_not_an_approval():
    assert derive_status([RUNNING, BACKOFF]) == DerivedStatus(
        WorkflowRunStatus.WAITING_RETRY, "retry_backoff"
    )


@pytest.mark.parametrize("state", [TIMER, CALLED, (NodeRunStatus.PENDING, None), RUNNING])
def test_a_timer_or_a_called_run_reads_as_running(state):
    assert derive_status([state]) == DerivedStatus(WorkflowRunStatus.RUNNING, None)


def test_no_live_rows_reads_as_running():
    assert derive_status([]) == DerivedStatus(WorkflowRunStatus.RUNNING, None)


async def test_refreshing_writes_only_what_changed():
    run = MagicMock(status=WorkflowRunStatus.RUNNING.value, paused_reason=None)
    update = AsyncMock(return_value=run)
    with (
        patch.object(
            run_status.workflow_run_repo,
            "list_live_node_states",
            AsyncMock(return_value=[APPROVAL]),
        ),
        patch.object(run_status.workflow_run_repo, "update_run", update),
    ):
        await run_status.refresh_run_status(MagicMock(), run=run)
        update.assert_awaited_once()
        assert update.await_args.kwargs["update_data"] == {
            "status": "waiting_approval",
            "paused_reason": "approval",
        }
        run.status, run.paused_reason = "waiting_approval", "approval"
        update.reset_mock()
        await run_status.refresh_run_status(MagicMock(), run=run)
        update.assert_not_awaited()


async def test_refreshing_a_terminal_run_changes_nothing():
    run = MagicMock(status=WorkflowRunStatus.FAILED.value, paused_reason=None)
    with (
        patch.object(run_status.workflow_run_repo, "list_live_node_states", AsyncMock()) as live,
        patch.object(run_status.workflow_run_repo, "update_run", AsyncMock()) as update,
    ):
        assert await run_status.refresh_run_status(MagicMock(), run=run) is run
    live.assert_not_awaited()
    update.assert_not_awaited()
