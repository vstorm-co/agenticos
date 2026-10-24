"""`app.worker.tasks.workflow_tasks`: the dispatch job and the sweeps' bodies.

The phases `dispatch_node` sequences are exercised end to end against a real
Postgres by `tests/integration/test_workflow_run_dispatch.py` and
`tests/integration/test_workflow_job_dispatch.py`. What is worth unit-testing in
isolation is what this module owns: the status word each outcome answers, that
the poll stamps and queues in one session, that the sweeps report what the
services admitted, and the lease renewer.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_execution.context import ClaimState
from app.worker.jobs import DispatchWorkflowNode
from app.worker.tasks import workflow_tasks

pytestmark = pytest.mark.anyio

TASKS_PATH = "app.worker.tasks.workflow_tasks"
DISPATCHER_PATH = "app.services.workflow_execution.dispatcher"


class _AsyncDBContext:
    """A stand-in for `get_worker_db_context()` that hands back a plain mock session."""

    def __init__(self, db: object) -> None:
        self._db = db

    async def __aenter__(self) -> object:
        return self._db

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


def _job() -> DispatchWorkflowNode:
    return DispatchWorkflowNode(workflow_run_id=uuid.uuid4(), node_run_id=uuid.uuid4())


class TestDispatchNode:
    @pytest.fixture(autouse=True)
    def _session(self):
        with patch(
            f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())
        ):
            yield

    async def test_a_row_nobody_can_claim_answers_nothing_to_claim(self):
        with patch(f"{DISPATCHER_PATH}.claim", new=AsyncMock(return_value=None)):
            outcome = await workflow_tasks.dispatch_node(_job())

        assert outcome.status == "nothing_to_claim"

    async def test_an_attempt_that_is_not_begun_answers_not_dispatched(self):
        claimed = MagicMock(claimed_by=uuid.uuid4())
        with (
            patch(f"{DISPATCHER_PATH}.claim", new=AsyncMock(return_value=claimed)),
            patch(f"{DISPATCHER_PATH}.begin_attempt", new=AsyncMock(return_value=None)),
            patch(f"{DISPATCHER_PATH}.call_handler", new=AsyncMock()) as call_handler,
        ):
            outcome = await workflow_tasks.dispatch_node(_job())

        assert outcome.status == "not_dispatched"
        call_handler.assert_not_awaited()

    async def test_a_node_that_runs_is_settled_with_the_handlers_outcome(self):
        job = _job()
        claimed = MagicMock(claimed_by=uuid.uuid4())
        begun, outcome = MagicMock(), MagicMock()
        with (
            patch(f"{DISPATCHER_PATH}.claim", new=AsyncMock(return_value=claimed)),
            patch(f"{DISPATCHER_PATH}.begin_attempt", new=AsyncMock(return_value=begun)) as begin,
            patch(f"{DISPATCHER_PATH}.call_handler", new=AsyncMock(return_value=outcome)),
            patch(f"{DISPATCHER_PATH}.settle", new=AsyncMock(return_value=[])) as settle,
        ):
            answered = await workflow_tasks.dispatch_node(job)

        assert answered.status == "settled"
        assert begin.await_args.kwargs["workflow_run_id"] == job.workflow_run_id
        assert begin.await_args.kwargs["node_run_id"] == job.node_run_id
        assert begin.await_args.kwargs["token"] == claimed.claimed_by
        assert settle.await_args.kwargs == {"begun": begun, "outcome": outcome}


class TestPollDueDispatches:
    async def test_queues_a_job_for_each_row_it_took_in_the_session_that_stamped_them(self):
        rows = [MagicMock(), MagicMock()]
        db = MagicMock()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(db)),
            patch(
                "app.repositories.workflow_run.take_due_for_submission",
                new=AsyncMock(return_value=rows),
            ) as taken,
            patch(
                "app.services.workflow_execution.dispatch_queue.queue_dispatch_job",
                new=AsyncMock(),
            ) as queue,
        ):
            count = await workflow_tasks.poll_due_dispatches()

        assert count == 2
        assert taken.await_args.args[0] is db
        assert [call.args for call in queue.await_args_list] == [(db, rows[0]), (db, rows[1])]

    async def test_a_poll_with_nothing_due_queues_nothing(self):
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.repositories.workflow_run.take_due_for_submission",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.workflow_execution.dispatch_queue.queue_dispatch_job",
                new=AsyncMock(),
            ) as queue,
        ):
            assert await workflow_tasks.poll_due_dispatches() == 0

        queue.assert_not_awaited()


class TestReconcile:
    def _reconciler(self, *, stale: int = 0, resolved: int = 0) -> MagicMock:
        reconciler = MagicMock()
        reconciler.stale_claims = AsyncMock(return_value=stale)
        reconciler.resolve_orphaned_attempts = AsyncMock(return_value=resolved)
        reconciler.wake_stale_approval_decisions = AsyncMock(return_value=0)
        reconciler.wake_stale_step_approvals = AsyncMock(return_value=0)
        return reconciler

    async def test_reports_what_each_of_the_four_sweeps_did(self):
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.reconciler.WorkflowReconcilerService",
                return_value=self._reconciler(stale=2, resolved=1),
            ),
        ):
            result = await workflow_tasks.reconcile()

        assert result == {
            "reclaimed_claims": 2,
            "resolved_attempts": 1,
            "woken_approvals": 0,
            "woken_step_approvals": 0,
        }

    async def test_a_quiet_sweep_reports_zeros(self):
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.reconciler.WorkflowReconcilerService",
                return_value=self._reconciler(),
            ),
        ):
            assert not any((await workflow_tasks.reconcile()).values())


class TestLeaseRenewal:
    @pytest.fixture(autouse=True)
    def _fast_ticks(self, monkeypatch):
        monkeypatch.setattr(workflow_tasks.settings, "WORKFLOW_DISPATCH_LEASE_SECONDS", 0.03)

    async def test_a_lost_claim_stops_renewing_and_tells_the_handler(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(side_effect=[True, False]),
            ) as renew,
        ):
            await workflow_tasks._renew_until_lost(uuid.uuid4(), uuid.uuid4(), claim)

        assert renew.await_count == 2
        assert claim.lost is True

    async def test_a_failed_renewal_is_retried_rather_than_giving_the_claim_up(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(side_effect=[RuntimeError("db blip"), False]),
            ) as renew,
        ):
            await workflow_tasks._renew_until_lost(uuid.uuid4(), uuid.uuid4(), claim)

        assert renew.await_count == 2
        assert claim.lost is True

    async def test_renewal_stops_when_the_block_ends(self):
        claim = ClaimState()
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.workflow_execution.dispatcher.renew_lease",
                new=AsyncMock(return_value=True),
            ) as renew,
        ):
            async with workflow_tasks._lease_kept_alive(uuid.uuid4(), uuid.uuid4(), claim):
                await asyncio.sleep(0.05)
            renewals = renew.await_count
            await asyncio.sleep(0.05)

        assert renewals >= 1
        assert renew.await_count == renewals
        assert claim.lost is False


class TestWorkflowSchedulesCheck:
    async def test_it_fires_due_schedules_and_counts_the_runs_it_admitted(self):
        pair = (uuid.uuid4(), uuid.uuid4())
        service = MagicMock(fire_due=AsyncMock(return_value=[pair]))
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch("app.services.workflow_exposure.WorkflowExposureService", return_value=service),
        ):
            assert await workflow_tasks.check_workflow_schedules() == 1
            service.fire_due.return_value = []
            assert await workflow_tasks.check_workflow_schedules() == 0


class TestWorkflowTableTriggers:
    async def test_it_consumes_added_records_and_counts_the_runs_it_admitted(self):
        pair = (uuid.uuid4(), uuid.uuid4())
        consumer = MagicMock(consume=AsyncMock(return_value=[pair]))
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.services.virtual_tables.triggers.TableTriggerConsumer", return_value=consumer
            ),
        ):
            assert await workflow_tasks.consume_table_triggers() == 1
            consumer.consume.return_value = []
            assert await workflow_tasks.consume_table_triggers() == 0


class TestWorkflowRunRetention:
    async def test_it_removes_batches_until_none_is_left_then_unlinks_their_files(self):
        first = uuid.uuid4()
        taken = AsyncMock(side_effect=[[(first, ["a", "b"])], [(uuid.uuid4(), [])], []])
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch("app.repositories.workflow_run.take_expired_runs", new=taken),
            patch("app.services.file_storage.delete_files_best_effort", new=AsyncMock()) as unlink,
        ):
            assert await workflow_tasks.sweep_workflow_run_retention() == 2

        assert [call.args[0] for call in unlink.await_args_list] == [["a", "b"], []]

    async def test_a_sweep_with_nothing_to_remove_removes_nothing(self):
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch(
                "app.repositories.workflow_run.take_expired_runs", new=AsyncMock(return_value=[])
            ),
            patch("app.services.file_storage.delete_files_best_effort", new=AsyncMock()) as unlink,
        ):
            assert await workflow_tasks.sweep_workflow_run_retention() == 0
        unlink.assert_not_awaited()

    async def test_a_backlog_is_cleared_a_bounded_number_of_batches_per_sweep(self):
        """A workflow whose retention was just shortened clears over several days,
        not in one long hold."""
        taken = AsyncMock(return_value=[(uuid.uuid4(), [])])
        with (
            patch(f"{TASKS_PATH}.get_worker_db_context", return_value=_AsyncDBContext(MagicMock())),
            patch("app.repositories.workflow_run.take_expired_runs", new=taken),
            patch("app.services.file_storage.delete_files_best_effort", new=AsyncMock()),
        ):
            assert await workflow_tasks.sweep_workflow_run_retention() == (
                workflow_tasks.RETENTION_BATCHES
            )

        assert taken.await_count == workflow_tasks.RETENTION_BATCHES
