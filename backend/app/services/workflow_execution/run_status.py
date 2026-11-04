"""A run's status, derived from its live steps.

Several steps of one run can be live at once - side by side after a fork, or inside a
loop - each waiting in its own way. The run's status is the most severe of them, so it
is never written by one step's transition alone: every transition re-derives it from the
run's live rows, under the run's lock.

Severity, highest first: a step needing attention, an approval wait, a retry backoff,
running. A step parked on a timer, or on a run it called, is not a wait the run reports:
the run reads as running. A run with no live rows reads as running too; it ends through
its own paths (`succeeded`, `failed`, `cancelled`, `budget_exceeded`), never through here.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import NodeRunStatus, WaitingReason, WorkflowRun, WorkflowRunStatus
from app.repositories import workflow_run as workflow_run_repo
from app.repositories.workflow_run import LiveNodeState

__all__ = ["DerivedStatus", "LiveNodeState", "derive_status", "refresh_run_status"]


@dataclass(frozen=True, slots=True)
class DerivedStatus:
    """What a run reads as, and why it is paused, if it is."""

    status: WorkflowRunStatus
    paused_reason: str | None


_RUNNING = DerivedStatus(WorkflowRunStatus.RUNNING, None)
_RETRY = DerivedStatus(WorkflowRunStatus.WAITING_RETRY, WaitingReason.RETRY_BACKOFF.value)
_APPROVAL = DerivedStatus(WorkflowRunStatus.WAITING_APPROVAL, WaitingReason.APPROVAL.value)
_ATTENTION = DerivedStatus(WorkflowRunStatus.NEEDS_ATTENTION, None)


def _read(state: LiveNodeState) -> DerivedStatus:
    status, reason = state
    if status is NodeRunStatus.NEEDS_ATTENTION:
        return _ATTENTION
    if status is NodeRunStatus.WAITING and reason is WaitingReason.APPROVAL:
        return _APPROVAL
    if status is NodeRunStatus.WAITING and reason is WaitingReason.RETRY_BACKOFF:
        return _RETRY
    return _RUNNING


_SEVERITY = (_RUNNING, _RETRY, _APPROVAL, _ATTENTION)


def derive_status(live: Sequence[LiveNodeState]) -> DerivedStatus:
    """The most severe status among `live` steps; `running` when there are none."""
    return max((_read(state) for state in live), key=_SEVERITY.index, default=_RUNNING)


async def refresh_run_status(db: AsyncSession, *, run: WorkflowRun) -> WorkflowRun:
    """Write the status `run`'s live steps derive, if it differs from the stored one.

    The caller holds the run's lock. A terminal run is left as it ended.
    """
    if WorkflowRunStatus(run.status).is_terminal:
        return run
    derived = derive_status(
        await workflow_run_repo.list_live_node_states(db, workflow_run_id=run.id)
    )
    if run.status == derived.status.value and run.paused_reason == derived.paused_reason:
        return run
    return await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={"status": derived.status.value, "paused_reason": derived.paused_reason},
    )
